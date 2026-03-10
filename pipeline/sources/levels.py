"""
pipeline/sources/levels.py
--------------------------
Scrapes levels.fyi/jobs for US remote tech roles.

Levels uses Next.js SSR — the full job dataset is embedded in the page HTML
inside a <script id="__NEXT_DATA__"> tag as JSON. No separate API call needed
for the initial page load; pagination uses offset query params.

Fields returned include salary (base + total comp), making this the richest
source in the pipeline.
"""

import json
import re
import httpx

from pipeline.ats import _is_remote

BASE_URL    = "https://www.levels.fyi/jobs/location/united-states"
PAGE_SIZE   = 25          # levels.fyi default page size
MAX_PAGES   = 40          # cap at 1,000 jobs (~40 pages); full set is 73k but mostly irrelevant
SOURCE_NAME = "levels"


def _extract_next_data(html: str) -> dict:
    """Pull the __NEXT_DATA__ JSON blob from page HTML."""
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}


def _parse_job(j: dict) -> dict:
    """Normalize a single levels.fyi job object to the shared contract."""
    # Work arrangement: "remote", "hybrid", "office" (or similar)
    arrangement = (j.get("workArrangement") or "").lower()
    is_remote = _is_remote(arrangement, True if arrangement == "remote" else None)

    # Location: may be a list of strings
    locations = j.get("locations") or []
    location_str = ", ".join(locations) if isinstance(locations, list) else str(locations)

    # Salary (base range, USD)
    sal = j.get("salary") or {}
    salary_min = sal.get("minBase") or sal.get("min")
    salary_max = sal.get("maxBase") or sal.get("max")

    return {
        "title":      j.get("title", ""),
        "company":    j.get("company", {}).get("name", "") if isinstance(j.get("company"), dict) else str(j.get("company", "")),
        "location":   location_str,
        "remote":     is_remote,
        "url":        j.get("url") or j.get("applyUrl", ""),
        "posted_at":  j.get("postedAt") or j.get("createdAt", ""),
        "source":     SOURCE_NAME,
        "salary_min": salary_min,
        "salary_max": salary_max,
    }


async def fetch_jobs(client: httpx.AsyncClient) -> list[dict]:
    """
    Fetch all levels.fyi US job listings, paginating until empty or MAX_PAGES.
    Filters to remote jobs only (arrangement == "remote").
    """
    all_jobs: list[dict] = []

    for page in range(MAX_PAGES):
        offset = page * PAGE_SIZE
        url = f"{BASE_URL}?offset={offset}&limit={PAGE_SIZE}"
        try:
            resp = await client.get(url, timeout=15.0)
            resp.raise_for_status()
        except Exception:
            break

        data = _extract_next_data(resp.text)
        # Path: props → pageProps → initialJobsData (list of company buckets or flat jobs)
        page_props = data.get("props", {}).get("pageProps", {})
        raw_jobs   = page_props.get("initialJobsData") or page_props.get("jobs") or []

        if not raw_jobs:
            break

        # initialJobsData can be a flat list of jobs OR a list of company buckets
        for item in raw_jobs:
            # Company bucket shape: {"company": {...}, "jobs": [...]}
            if "jobs" in item and isinstance(item["jobs"], list):
                for j in item["jobs"]:
                    parsed = _parse_job(j)
                    if parsed["remote"]:
                        all_jobs.append(parsed)
            else:
                parsed = _parse_job(item)
                if parsed["remote"]:
                    all_jobs.append(parsed)

        # Stop if we got fewer results than a full page
        if len(raw_jobs) < PAGE_SIZE:
            break

    return all_jobs
