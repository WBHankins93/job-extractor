"""
scripts/fetch_jds_and_rescore.py
---------------------------------
Fetches full job descriptions for every remote position across all 93
remote-role companies and re-scores fit using the full JD text.

Run after the main pipeline:
    python main.py
    python scripts/export_remote_roles.py
    python scripts/fetch_jds_and_rescore.py

Why this exists:
    main.py scores fit using only job title + location because ATS batch APIs
    don't return full JDs inline. Greenhouse and Lever are exceptions — they
    include full content in the batch response. For Ashby, SmartRecruiters,
    and Workable, this script makes one additional API call per job to fetch
    the full description.

    Only companies that matched a target role reach this script (upstream
    filter in export_remote_roles.py). Per-job filtering via
    matches_target_role() is applied again here as a second line of defence.

Output:
    output/rescored-jobs.csv — one row per remote job, sorted by fit_score_jd

Concurrency model:
    sem_detect(20): ATS re-detection — 3-pass probe, many domains
    sem_jd(15):     Individual JD fetches — Ashby / SmartRecruiters / Workable only
    Greenhouse and Lever JDs come free from the batch call.
"""

import asyncio
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pandas as pd

# Allow importing from the parent project's pipeline package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.ats import detect_ats, PARSERS
from pipeline.embed import (
    ROLE_TO_RESUME,
    build_resume_collection,
    get_chroma_client,
    load_resumes,
    score_job_fit,
)
from pipeline.ingest import matches_target_role, parse_level, is_us_location, within_experience_cap


INPUT_CSV  = Path(__file__).resolve().parent.parent / "output" / "remote-roles.csv"
OUTPUT_CSV = Path(__file__).resolve().parent.parent / "output" / "rescored-jobs.csv"

OUTPUT_COLUMNS = [
    "company_rank",
    "company_name",
    "ats",
    "job_title",
    "job_url",
    "role_type",
    "level",
    "resume_used",
    "fit_score_title",
    "fit_score_jd",
    "jd_found",
]


# -------------------------------------------------------------------
# HTML stripping — stdlib only, no new dependencies
#
# HTMLParser walks the tag tree and collects raw text nodes,
# automatically handling HTML entities (&amp;, &lt;, etc.).
# -------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if stripped:
            self._parts.append(stripped)

    def get_text(self) -> str:
        return " ".join(self._parts)


def strip_html(html: str) -> str:
    """Strip HTML tags and decode entities. Returns plain text, or empty string."""
    if not html:
        return ""
    extractor = _TextExtractor()
    try:
        extractor.feed(html)
    except Exception:
        return html  # fallback: return as-is if parsing unexpectedly fails
    return extractor.get_text()


# -------------------------------------------------------------------
# Slug extraction from api_url
#
# Each ATS embeds the company slug at a fixed depth in the path.
# -------------------------------------------------------------------

# Zero-indexed position of slug in api_url path after strip("/").split("/")
_SLUG_INDEX = {
    "greenhouse":      2,   # /v1/boards/{slug}/jobs
    "lever":           2,   # /v0/postings/{slug}
    "ashby":           2,   # /posting-api/job-board/{slug}
    "smartrecruiters": 2,   # /v1/companies/{slug}/postings
    "workable":        3,   # /api/v1/accounts/{slug}/jobs
}


def extract_slug(ats: str, api_url: str) -> str | None:
    """Parse the company slug from the api_url path."""
    try:
        parts = urlparse(api_url).path.strip("/").split("/")
        idx = _SLUG_INDEX.get(ats)
        if idx is None or idx >= len(parts):
            return None
        return parts[idx] or None
    except Exception:
        return None


# -------------------------------------------------------------------
# Batch fetchers that preserve full JD content
# -------------------------------------------------------------------

async def fetch_greenhouse_jobs_with_content(
    api_url: str, client: httpx.AsyncClient
) -> list[dict]:
    """
    The api_url already includes ?content=true (built into pipeline/ats.py).
    Each job in the response has a 'content' field with HTML job description.
    """
    try:
        resp = await client.get(api_url, timeout=10.0)
        resp.raise_for_status()
        jobs = resp.json().get("jobs", [])
        return [
            {
                "title":    j.get("title", ""),
                "location": j.get("location", {}).get("name", ""),
                "remote":   "remote" in j.get("location", {}).get("name", "").lower(),
                "url":      j.get("absolute_url", ""),
                "jd_html":  j.get("content", ""),
            }
            for j in jobs
        ]
    except Exception:
        return []


async def fetch_lever_jobs_with_content(
    api_url: str, client: httpx.AsyncClient
) -> list[dict]:
    """
    Lever batch responses include 'descriptionPlain' and 'description' per posting.
    Prefer descriptionPlain (already plain text); fall back to description (HTML).
    """
    try:
        resp = await client.get(api_url, timeout=10.0)
        resp.raise_for_status()
        jobs = resp.json()
        result = []
        for j in jobs:
            location  = j.get("categories", {}).get("location", "")
            workplace = j.get("workplaceType", "")
            is_remote = (
                "remote" in location.lower()
                or workplace.lower() == "remote"
            )
            jd = j.get("descriptionPlain", "") or j.get("description", "")
            result.append({
                "title":    j.get("text", ""),
                "location": location,
                "remote":   is_remote,
                "url":      j.get("hostedUrl", ""),
                "jd_html":  jd,
            })
        return result
    except Exception:
        return []


# -------------------------------------------------------------------
# Individual JD fetchers — Ashby, SmartRecruiters, Workable
# -------------------------------------------------------------------

async def fetch_ashby_jd(
    slug: str, job: dict, client: httpx.AsyncClient
) -> str | None:
    """
    Job URL shape: https://jobs.ashbyhq.com/{slug}/{uuid}
    Individual endpoint: api.ashbyhq.com/posting-api/job-board/{slug}/jobs/{jobId}
    """
    try:
        job_id = urlparse(job.get("url", "")).path.strip("/").split("/")[-1]
        if not job_id:
            return None
        url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}/jobs/{job_id}"
        resp = await client.get(url, timeout=8.0)
        resp.raise_for_status()
        data = resp.json()
        job_data = data.get("job", data)   # Ashby may wrap in "job" key
        html = job_data.get("descriptionHtml") or job_data.get("description", "")
        return strip_html(html) or None
    except Exception:
        return None


async def fetch_smartrecruiters_jd(
    slug: str, job: dict, client: httpx.AsyncClient
) -> str | None:
    """
    ref URL shape: https://jobs.smartrecruiters.com/{Company}/{jobId}
    Individual endpoint: api.smartrecruiters.com/v1/companies/{slug}/postings/{jobId}
    Response: jobAd.sections — dict of section objects each with a "text" field.
    """
    try:
        job_id = urlparse(job.get("url", "")).path.strip("/").split("/")[-1]
        if not job_id:
            return None
        url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{job_id}"
        resp = await client.get(url, timeout=8.0)
        resp.raise_for_status()
        sections = resp.json().get("jobAd", {}).get("sections", {})
        parts = [
            strip_html(v.get("text", ""))
            for v in sections.values()
            if isinstance(v, dict) and v.get("text")
        ]
        return " ".join(parts) or None
    except Exception:
        return None


async def fetch_workable_jd(
    slug: str, job: dict, client: httpx.AsyncClient
) -> str | None:
    """
    Job URL shape: https://apply.workable.com/{slug}/j/{shortcode}/
    Individual endpoint: apply.workable.com/api/v1/accounts/{slug}/jobs/{shortcode}
    Response: {"description": "...", "requirements": "..."}
    """
    try:
        parts = [p for p in urlparse(job.get("url", "")).path.split("/") if p]
        # parts: [slug, "j", shortcode]
        if len(parts) < 3:
            return None
        shortcode = parts[2]
        url = f"https://apply.workable.com/api/v1/accounts/{slug}/jobs/{shortcode}"
        resp = await client.get(url, timeout=8.0)
        resp.raise_for_status()
        data = resp.json()
        description  = strip_html(data.get("description", ""))
        requirements = strip_html(data.get("requirements", ""))
        combined = f"{description} {requirements}".strip()
        return combined or None
    except Exception:
        return None


async def fetch_jd_text(
    ats: str, slug: str | None, job: dict, client: httpx.AsyncClient
) -> str | None:
    """Dispatch to the correct individual JD fetcher for Ashby/SmartRecruiters/Workable."""
    if not slug:
        return None
    if ats == "ashby":
        return await fetch_ashby_jd(slug, job, client)
    if ats == "smartrecruiters":
        return await fetch_smartrecruiters_jd(slug, job, client)
    if ats == "workable":
        return await fetch_workable_jd(slug, job, client)
    return None


# -------------------------------------------------------------------
# Per-company orchestration
# -------------------------------------------------------------------

async def process_company(
    row: pd.Series,
    client: httpx.AsyncClient,
    sem_detect: asyncio.Semaphore,
    sem_jd: asyncio.Semaphore,
    resume_collection,
    all_resume_files: list[str],
) -> list[dict]:
    """
    For one remote company:
      1. Re-detect ATS to recover working api_url
      2. Fetch batch jobs (inline JD for GH/Lever; standard batch for others)
      3. Filter to remote=True
      4. Per remote job: fetch full JD → score → build output row
    """

    # Step 1: Re-detect ATS
    async with sem_detect:
        ats, api_url = await detect_ats(row["career_url"], client)

    if ats == "unknown" or not api_url:
        print(f"  [SKIP] {row['name']} — ATS not re-detected")
        return []

    # Step 2: Fetch batch (with inline JD where available)
    try:
        if ats == "greenhouse":
            jobs = await fetch_greenhouse_jobs_with_content(api_url, client)
        elif ats == "lever":
            jobs = await fetch_lever_jobs_with_content(api_url, client)
        else:
            resp = await client.get(api_url, timeout=10.0)
            resp.raise_for_status()
            jobs = PARSERS[ats](resp.json())
    except Exception:
        return []

    # Step 3: Filter to remote-only US jobs
    remote_jobs = [j for j in jobs if j.get("remote") and is_us_location(j.get("location", ""))]
    if not remote_jobs:
        return []

    slug = extract_slug(ats, api_url)

    # Step 4: Score each remote job
    async def process_job(job: dict) -> dict | None:
        role = matches_target_role(job["title"])
        if not role:
            return None  # skip non-target-role jobs entirely
        if not within_experience_cap(job["title"]):
            return None

        # Decide which resume to score against
        mapped = ROLE_TO_RESUME.get(role)
        resumes_to_try = [mapped] if mapped else all_resume_files

        # Baseline: title + location only
        title_text = f"{job['title']} {job.get('location', '')}".strip()
        title_scores = {
            rf: score_job_fit(title_text, rf, resume_collection)
            for rf in resumes_to_try
        }
        fit_score_title = max(title_scores.values())

        # Fetch full JD
        if "jd_html" in job:
            # Greenhouse or Lever — came free from batch
            jd_text = strip_html(job["jd_html"])
            jd_found = bool(jd_text.strip())
        else:
            async with sem_jd:
                jd_text = await fetch_jd_text(ats, slug, job, client) or ""
            jd_found = bool(jd_text.strip())

        if jd_found and not within_experience_cap(job["title"], jd_text=jd_text):
            return None

        # Score with full JD (or fall back to title baseline if not found)
        if jd_found:
            jd_scores = {
                rf: score_job_fit(jd_text, rf, resume_collection)
                for rf in resumes_to_try
            }
            fit_score_jd = max(jd_scores.values())
            best_resume  = max(jd_scores, key=jd_scores.get)
        else:
            fit_score_jd = fit_score_title
            best_resume  = max(title_scores, key=title_scores.get)

        return {
            "company_rank":    row["rank"],
            "company_name":    row["name"],
            "ats":             ats,
            "job_title":       job["title"],
            "job_url":         job.get("url", ""),
            "role_type":       role,
            "level":           parse_level(job["title"]),
            "resume_used":     best_resume,
            "fit_score_title": round(fit_score_title, 3),
            "fit_score_jd":    round(fit_score_jd, 3),
            "jd_found":        jd_found,
        }

    job_tasks  = [process_job(job) for job in remote_jobs]
    job_results = await asyncio.gather(*job_tasks)
    return [r for r in job_results if r is not None]


# -------------------------------------------------------------------
# Entry point
# -------------------------------------------------------------------

async def main() -> None:
    if not INPUT_CSV.exists():
        print(f"Input file not found: {INPUT_CSV}")
        print("Run `python main.py` then `python scripts/export_remote_roles.py` first.")
        return

    df = pd.read_csv(INPUT_CSV)

    print("=== JD Fetch + Rescore ===\n")
    print(f"Loaded {len(df)} remote companies from {INPUT_CSV.name}")

    print("\nLoading resumes and building vector index...")
    resumes = load_resumes()
    chroma  = get_chroma_client()
    resume_collection = build_resume_collection(chroma, resumes)
    all_resume_files  = list(resumes.keys())
    print()

    async with httpx.AsyncClient(
        headers={"User-Agent": "job-search-tool/1.0"},
        follow_redirects=True,
    ) as client:

        sem_detect = asyncio.Semaphore(20)
        sem_jd     = asyncio.Semaphore(15)

        print(f"Processing {len(df)} companies (re-detecting ATS + fetching JDs)...")
        tasks = [
            process_company(row, client, sem_detect, sem_jd, resume_collection, all_resume_files)
            for _, row in df.iterrows()
        ]
        results = await asyncio.gather(*tasks)

    # Flatten list-of-lists → one row per job
    all_jobs = [job for company_jobs in results for job in company_jobs]
    print(f"\nTotal remote jobs: {len(all_jobs)}")

    if not all_jobs:
        print("No jobs found.")
        return

    out = pd.DataFrame(all_jobs, columns=OUTPUT_COLUMNS)
    out = out.sort_values("fit_score_jd", ascending=False)
    OUTPUT_CSV.parent.mkdir(exist_ok=True)
    out.to_csv(OUTPUT_CSV, index=False)

    jd_count  = int(out["jd_found"].sum())
    print(f"  {jd_count}/{len(out)} had full JD fetched")
    print(f"\nSaved → {OUTPUT_CSV}")

    print(f"\nTop 15 by fit_score_jd:")
    display_cols = ["company_name", "job_title", "role_type", "fit_score_title", "fit_score_jd", "jd_found"]
    print(out[display_cols].head(15).to_string(index=False))


if __name__ == "__main__":
    asyncio.run(main())
