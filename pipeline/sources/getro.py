"""
pipeline/sources/getro.py
-------------------------
Fetches jobs from Getro-powered VC portfolio job boards.

Getro boards (jobs.generalcatalyst.com, jobs.accel.com) aggregate portfolio
company job listings into a single searchable board. The platform uses Algolia
for search; credentials are embedded in the page JS bundle.

One adapter, multiple boards — each board has its own Algolia index.
"""

import re
import httpx

from pipeline.ats import _is_remote

SOURCE_NAME = "getro"
PAGE_SIZE   = 50

# Boards to fetch — each is a (display_name, url) pair
BOARDS = [
    ("General Catalyst", "https://jobs.generalcatalyst.com/jobs"),
    ("Accel",            "https://jobs.accel.com/jobs"),
]

# Algolia credential patterns (Getro embeds these in page HTML)
_APP_ID_RE  = re.compile(r'["\']applicationId["\']\s*:\s*["\']([A-Z0-9]{10})["\']')
_API_KEY_RE = re.compile(r'["\']apiKey["\']\s*:\s*["\']([a-f0-9]{32})["\']')
_INDEX_RE   = re.compile(r'["\']indexName["\']\s*:\s*["\']([^"\']+)["\']')


def _extract_algolia_creds(html: str) -> tuple[str, str, str] | None:
    """Extract (app_id, api_key, index_name) from Getro board HTML."""
    app_match = _APP_ID_RE.search(html)
    key_match = _API_KEY_RE.search(html)
    idx_match = _INDEX_RE.search(html)
    if app_match and key_match and idx_match:
        return app_match.group(1), key_match.group(1), idx_match.group(1)
    return None


def _parse_hit(hit: dict, board_name: str) -> dict:
    """Normalize a Getro/Algolia job hit to the shared contract."""
    location = hit.get("location") or hit.get("city") or ""
    remote_flag = hit.get("remote") or hit.get("isRemote")

    # Getro sometimes encodes company as a nested object
    company = hit.get("company")
    if isinstance(company, dict):
        company = company.get("name", "")
    company = company or board_name  # fall back to the VC firm name

    return {
        "title":      hit.get("title") or hit.get("jobTitle", ""),
        "company":    company,
        "location":   location,
        "remote":     _is_remote(location, bool(remote_flag) if remote_flag is not None else None),
        "url":        hit.get("url") or hit.get("jobUrl") or hit.get("applyUrl", ""),
        "posted_at":  hit.get("publishedAt") or hit.get("createdAt", ""),
        "source":     SOURCE_NAME,
        "salary_min": None,
        "salary_max": None,
    }


async def _fetch_board(
    client: httpx.AsyncClient,
    board_name: str,
    board_url: str,
) -> list[dict]:
    """Fetch all remote jobs from a single Getro board."""
    # Load board page to extract Algolia creds
    try:
        resp = await client.get(board_url, timeout=15.0)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [getro/{board_name}] page load failed: {e}")
        return []

    creds = _extract_algolia_creds(resp.text)
    if not creds:
        print(f"  [getro/{board_name}] could not extract Algolia credentials")
        return []

    app_id, api_key, index_name = creds
    algolia_url = f"https://{app_id}-dsn.algolia.net/1/indexes/{index_name}/query"

    all_jobs: list[dict] = []
    page = 0

    while True:
        payload = {
            "query":            "",
            "filters":          "remote:true",
            "hitsPerPage":      PAGE_SIZE,
            "page":             page,
            "attributesToRetrieve": [
                "title", "jobTitle", "company", "location", "city",
                "remote", "isRemote", "url", "jobUrl", "applyUrl",
                "publishedAt", "createdAt",
            ],
        }
        try:
            r = await client.post(
                algolia_url,
                json=payload,
                headers={
                    "X-Algolia-Application-Id": app_id,
                    "X-Algolia-API-Key":        api_key,
                },
                timeout=10.0,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"  [getro/{board_name}] Algolia query failed (page {page}): {e}")
            break

        hits = data.get("hits", [])
        all_jobs.extend(_parse_hit(h, board_name) for h in hits)

        if page >= data.get("nbPages", 1) - 1 or not hits:
            break
        page += 1

    return all_jobs


async def fetch_jobs(client: httpx.AsyncClient) -> list[dict]:
    """Fetch remote jobs from all configured Getro boards concurrently."""
    import asyncio
    results = await asyncio.gather(*[
        _fetch_board(client, name, url)
        for name, url in BOARDS
    ])
    return [job for board_jobs in results for job in board_jobs]
