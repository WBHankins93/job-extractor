"""
pipeline/ats.py
---------------
Stage 2 & 3: ATS detection and job fetching.

Detects which ATS platform a company uses — first by URL pattern,
then by fetching the career page and scanning the HTML for fingerprints.
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


ATS_REGISTRY = {
    "greenhouse": _greenhouse_api,
    "lever":      _lever_api,
    "ashby":      _ashby_api,
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


async def detect_ats(career_url: str, client: httpx.AsyncClient) -> tuple[str, str | None]:
    """
    Full ATS detection:
      1. Fast path — does the URL itself reveal the ATS? (no network)
      2. Slow path — fetch the career page, scan the HTML for fingerprints
    """
    # Fast path: URL is a direct ATS link
    for name, builder in ATS_REGISTRY.items():
        api_url = builder(career_url)
        if api_url:
            return name, api_url

    # Slow path: branded career page — fetch and scan
    try:
        response = await client.get(career_url, timeout=12.0)
        return detect_ats_from_html(response.text)
    except Exception:
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


PARSERS = {
    "greenhouse": _parse_greenhouse,
    "lever":      _parse_lever,
    "ashby":      _parse_ashby,
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
