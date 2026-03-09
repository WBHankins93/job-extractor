"""
pipeline/ats.py
---------------
Stage 2 & 3: ATS detection and job fetching.

Detects which ATS platform a company uses — three passes:
  1. Fast path: URL pattern matching (no network)
  2. Slow path: Fetch career page HTML and scan for fingerprints
  3. Slug probe: Derive company slug from domain, test against known ATS APIs
     (bypasses React/SPA pages where initial HTML has no fingerprints)

Then calls that platform's public API to get structured job data.
"""

import re
import httpx
from urllib.parse import urlparse


# -------------------------------------------------------------------
# ATS URL builders
# Used when the career URL IS the ATS URL (direct link).
# -------------------------------------------------------------------

def _greenhouse_api(url: str) -> str | None:
    parsed = urlparse(url)
    if "greenhouse.io" in parsed.netloc:
        slug = parsed.path.strip("/")
        return f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    return None


def _lever_api(url: str) -> str | None:
    parsed = urlparse(url)
    if "lever.co" in parsed.netloc:
        slug = parsed.path.strip("/")
        return f"https://api.lever.co/v0/postings/{slug}?mode=json"
    return None


def _ashby_api(url: str) -> str | None:
    parsed = urlparse(url)
    if "ashbyhq.com" in parsed.netloc:
        slug = parsed.path.strip("/")
        return f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    return None


def _smartrecruiters_api(url: str) -> str | None:
    parsed = urlparse(url)
    if "smartrecruiters.com" in parsed.netloc:
        slug = parsed.path.strip("/").split("/")[0]
        if slug:
            return f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
    return None


def _workable_api(url: str) -> str | None:
    parsed = urlparse(url)
    netloc = parsed.netloc
    # Subdomain: company.workable.com
    if netloc.endswith(".workable.com") and netloc != "apply.workable.com":
        slug = netloc.split(".workable.com")[0]
        return f"https://apply.workable.com/api/v1/accounts/{slug}/jobs"
    # Path: apply.workable.com/company
    if "workable.com" in netloc:
        parts = parsed.path.strip("/").split("/")
        if parts and parts[0]:
            return f"https://apply.workable.com/api/v1/accounts/{parts[0]}/jobs"
    return None


ATS_REGISTRY = {
    "greenhouse":      _greenhouse_api,
    "lever":           _lever_api,
    "ashby":           _ashby_api,
    "smartrecruiters": _smartrecruiters_api,
    "workable":        _workable_api,
}


# -------------------------------------------------------------------
# HTML fingerprints
#
# Most companies use branded career pages that *embed* an ATS.
# We fetch the HTML and search for these regex patterns to find
# which ATS is powering the page and what the company slug is.
# -------------------------------------------------------------------

ATS_PATTERNS = {
    "greenhouse": [
        r'boards\.greenhouse\.io/embed/job_board\?for=([^&"\']+)',
        r'boards\.greenhouse\.io/([^/"\'?]+)',
        r'gh_jid',   # Greenhouse job ID param — marker only, no slug
    ],
    "lever": [
        r'jobs\.lever\.co/([^/"\'?]+)',
        r'api\.lever\.co/v0/postings/([^/"\'?]+)',
    ],
    "ashby": [
        r'ashbyhq\.com/([^/"\'?]+)',
        r'jobs\.ashbyhq\.com/([^/"\'?]+)',
    ],
    "smartrecruiters": [
        r'jobs\.smartrecruiters\.com/([^/"\'?\s]+)',
        r'careers\.smartrecruiters\.com/([^/"\'?\s]+)',
        r'"companyIdentifier"\s*:\s*"([^"]+)"',
    ],
    "workable": [
        r'apply\.workable\.com/([^/"\'?\s]+)',
    ],
}


def _slug_from_html(html: str, ats_name: str) -> str | None:
    """Extract the company slug from page HTML using ATS-specific patterns."""
    for pattern in ATS_PATTERNS[ats_name]:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            try:
                return match.group(1).strip("/")
            except IndexError:
                return None  # pattern matched but has no capture group (marker-only)
    return None


def _build_api_url(ats_name: str, slug: str) -> str:
    if ats_name == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    if ats_name == "lever":
        return f"https://api.lever.co/v0/postings/{slug}?mode=json"
    if ats_name == "ashby":
        return f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    if ats_name == "smartrecruiters":
        return f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
    if ats_name == "workable":
        return f"https://apply.workable.com/api/v1/accounts/{slug}/jobs"
    return ""


def detect_ats_from_html(html: str) -> tuple[str, str | None]:
    """
    Scan page HTML for ATS fingerprints.
    Returns (ats_name, api_url) or ("unknown", None).
    """
    for ats_name in ATS_PATTERNS:
        slug = _slug_from_html(html, ats_name)
        if slug:
            return ats_name, _build_api_url(ats_name, slug)
    return "unknown", None


# -------------------------------------------------------------------
# Slug guessing
#
# Many startups use React/Next.js SPA career pages where the initial
# HTML contains no ATS fingerprints (JS loads everything dynamically).
# We derive a slug from the domain and probe each known ATS API directly.
# -------------------------------------------------------------------

def _derive_slugs(career_url: str) -> list[str]:
    """Extract candidate company slugs from the career URL domain."""
    host = urlparse(career_url).netloc.lower()
    # Strip common subdomain prefixes
    host = re.sub(r'^(www|careers|jobs|work|apply|hiring)\.', '', host)
    # Strip TLD
    name = re.sub(
        r'\.(ai|io|co|com|tech|net|org|dev|app|xyz|health|bio|energy|finance|security)$',
        '', host
    )
    slugs = [name]
    # Also try without hyphens (e.g. "spring-health" → "springhealth")
    if '-' in name:
        slugs.append(name.replace('-', ''))
    return [s for s in dict.fromkeys(slugs) if s]


async def _probe_slug(slug: str, client: httpx.AsyncClient) -> tuple[str, str | None]:
    """
    Try a slug against each known ATS API sequentially (most common first).
    Sequential rather than concurrent to avoid overwhelming the connection pool
    when hundreds of companies are probed simultaneously.
    Returns (ats_name, api_url) for the first 200 response, or ("unknown", None).
    """
    probes = [
        ("greenhouse",      f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"),
        ("lever",           f"https://api.lever.co/v0/postings/{slug}?mode=json"),
        ("ashby",           f"https://api.ashbyhq.com/posting-api/job-board/{slug}"),
        ("smartrecruiters", f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"),
        ("workable",        f"https://apply.workable.com/api/v1/accounts/{slug}/jobs"),
    ]
    for name, url in probes:
        try:
            resp = await client.get(url, timeout=5.0)
            if resp.status_code == 200:
                return name, _build_api_url(name, slug)
        except Exception:
            pass
    return "unknown", None


async def detect_ats(career_url: str, client: httpx.AsyncClient) -> tuple[str, str | None]:
    """
    Full ATS detection — three passes:
      1. Fast path: URL is a direct ATS domain link (no network)
      2. Slow path: Fetch career page, scan HTML for fingerprints
      3. Slug probe: Derive slug from domain, probe known ATS APIs directly
    """
    # Pass 1: URL is a direct ATS link
    for name, builder in ATS_REGISTRY.items():
        api_url = builder(career_url)
        if api_url:
            return name, api_url

    # Pass 2: Fetch career page and scan HTML for fingerprints
    try:
        response = await client.get(career_url, timeout=12.0)
        result = detect_ats_from_html(response.text)
        if result[0] != "unknown":
            return result
    except Exception:
        pass

    # Pass 3: Slug guessing — bypasses SPA pages with no HTML fingerprints
    for slug in _derive_slugs(career_url):
        result = await _probe_slug(slug, client)
        if result[0] != "unknown":
            return result

    return "unknown", None


# -------------------------------------------------------------------
# Job fetching + parsing
#
# Each ATS returns a different JSON shape. These normalize
# the response into a consistent list of job dicts.
# -------------------------------------------------------------------

def _parse_greenhouse(data: dict) -> list[dict]:
    jobs = data.get("jobs", [])
    return [
        {
            "title":    j.get("title", ""),
            "location": j.get("location", {}).get("name", ""),
            "remote":   "remote" in j.get("location", {}).get("name", "").lower(),
            "url":      j.get("absolute_url", ""),
        }
        for j in jobs
    ]


def _parse_lever(data: list) -> list[dict]:
    return [
        {
            "title":    j.get("text", ""),
            "location": j.get("categories", {}).get("location", ""),
            "remote":   "remote" in j.get("categories", {}).get("location", "").lower(),
            "url":      j.get("hostedUrl", ""),
        }
        for j in data
    ]


def _parse_ashby(data: dict) -> list[dict]:
    jobs = data.get("jobs", [])
    return [
        {
            "title":    j.get("title", ""),
            "location": j.get("location", ""),
            "remote":   j.get("isRemote", False),
            "url":      j.get("jobUrl", ""),
        }
        for j in jobs
    ]


def _parse_smartrecruiters(data: dict) -> list[dict]:
    jobs = data.get("content", [])
    return [
        {
            "title":    j.get("name", ""),
            "location": j.get("location", {}).get("city", ""),
            "remote":   j.get("location", {}).get("remote", False),
            "url":      j.get("ref", ""),
        }
        for j in jobs
    ]


def _parse_workable(data: dict) -> list[dict]:
    jobs = data.get("results", [])
    return [
        {
            "title":    j.get("title", ""),
            "location": j.get("location", {}).get("location_str", ""),
            "remote":   (
                j.get("location", {}).get("telecommuting", False)
                or "remote" in j.get("location", {}).get("location_str", "").lower()
            ),
            "url":      j.get("url", ""),
        }
        for j in jobs
    ]


PARSERS = {
    "greenhouse":      _parse_greenhouse,
    "lever":           _parse_lever,
    "ashby":           _parse_ashby,
    "smartrecruiters": _parse_smartrecruiters,
    "workable":        _parse_workable,
}


async def fetch_jobs(ats_name: str, api_url: str, client: httpx.AsyncClient) -> list[dict]:
    """
    Fetch job listings from an ATS API and return normalized job dicts.
    Silently returns [] on any failure — a dead company page shouldn't crash the pipeline.
    """
    try:
        response = await client.get(api_url, timeout=10.0)
        response.raise_for_status()
        parser = PARSERS.get(ats_name)
        if not parser:
            return []
        return parser(response.json())
    except Exception:
        return []
