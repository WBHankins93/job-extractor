"""
pipeline/sources/hiringcafe.py
------------------------------
Fetch remote software jobs from hiring.cafe via their JSON search API.

The API is a POST endpoint that accepts a `searchState` payload mirroring
the URL search state (same object that appears in the site's query string).
We request Remote-only jobs from the past `days` days and paginate until
the response returns fewer results than the page size.

No extra dependencies — httpx only.
"""

import httpx

_API_URL   = "https://hiring.cafe/api/search-jobs"
_PAGE_SIZE = 1000

_HEADERS = {
    "Content-Type": "application/json",
    "Accept":       "application/json",
    "Referer":      "https://hiring.cafe/",
    "Origin":       "https://hiring.cafe",
    # Mimic a browser session so the API doesn't treat us as a bot
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
}


async def fetch_jobs(client: httpx.AsyncClient, days: int = 61) -> list[dict]:
    """
    Return a list of normalized remote job dicts from hiring.cafe.

    `days` mirrors the `dateFetchedPastNDays` filter in the site's URL
    searchState (default 61, matching the user-provided URL).
    """
    all_jobs: list[dict] = []
    page = 0

    while True:
        payload = {
            "searchState": {
                "dateFetchedPastNDays": days,
                "workplaceTypes": ["Remote"],
            },
            "size": _PAGE_SIZE,
            "page": page,
        }

        try:
            resp = await client.post(
                _API_URL, json=payload, headers=_HEADERS, timeout=20.0
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            if page == 0:
                print(f"  [hiringcafe] error on page {page}: {exc}")
            break

        # hiring.cafe has used multiple response shapes — try each in order.
        raw: list[dict] = (
            data.get("results")
            or data.get("jobs")
            or data.get("data")
            or data.get("items")
            or data.get("content")
            or []
        )

        # Elasticsearch _hits wrapper (used by some versions)
        if not raw:
            hits = data.get("hits", {})
            if isinstance(hits, dict):
                raw = [h.get("_source", h) for h in hits.get("hits", [])]
            elif isinstance(hits, list):
                raw = [h.get("_source", h) for h in hits]

        if not raw:
            break

        for j in raw:
            norm = _normalize(j)
            if norm:
                all_jobs.append(norm)

        # Stop paginating when we've received a partial page
        if len(raw) < _PAGE_SIZE:
            break
        page += 1

    return all_jobs


def _normalize(j: dict) -> dict | None:
    """
    Normalize a raw hiring.cafe job record to the shared pipeline schema.
    Returns None if essential fields (title, company) are missing.
    """
    title = (
        j.get("title") or j.get("jobTitle") or j.get("job_title") or ""
    ).strip()
    company = (
        j.get("company") or j.get("companyName") or j.get("company_name")
        or j.get("employer") or j.get("organization") or ""
    ).strip()

    if not title or not company:
        return None

    url = (
        j.get("url") or j.get("jobUrl") or j.get("job_url")
        or j.get("applyUrl") or j.get("apply_url")
        or j.get("applicationUrl") or ""
    ).strip()

    location = (
        j.get("location") or j.get("locationName") or j.get("location_name")
        or "Remote"
    ).strip()

    posted_at = (
        j.get("postedAt") or j.get("posted_at")
        or j.get("createdAt") or j.get("created_at")
        or j.get("datePosted") or ""
    )

    salary_min = (
        j.get("salaryMin") or j.get("salary_min")
        or j.get("compensationMin") or j.get("compensation_min")
        or j.get("minSalary")
    )
    salary_max = (
        j.get("salaryMax") or j.get("salary_max")
        or j.get("compensationMax") or j.get("compensation_max")
        or j.get("maxSalary")
    )

    return {
        "source":     "hiringcafe",
        "company":    company,
        "title":      title,
        "url":        url,
        "location":   location,
        "remote":     True,   # workplaceTypes=["Remote"] in the search payload
        "posted_at":  str(posted_at) if posted_at else "",
        "salary_min": salary_min,
        "salary_max": salary_max,
    }
