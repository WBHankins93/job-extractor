"""
pipeline/sources/yc.py
----------------------
Fetches jobs from the Y Combinator job board (ycombinator.com/jobs).

YC uses Algolia for job search. The page JS bundle embeds a search-only API
key and application ID. We extract these from the page HTML and query the
Algolia index directly — no browser required.

The Algolia search-only key is public and stable (embedded in the JS bundle);
it can only query, not mutate, the index.
"""

import json
import re
import httpx

from pipeline.ats import _is_remote

YC_JOBS_URL  = "https://www.ycombinator.com/jobs"
SOURCE_NAME  = "yc"
PAGE_SIZE    = 50

# Patterns to extract Algolia credentials from the page/bundle JS
_ALGOLIA_APP_RE  = re.compile(r'["\']([A-Z0-9]{10})["\']')   # 10-char uppercase alphanum
_ALGOLIA_KEY_RE  = re.compile(r'["\']([a-f0-9]{32})["\']')   # 32-char hex search-only key
_ALGOLIA_IDX_RE  = re.compile(r'["\'](?:index|indexName)["\']:\s*["\']([^"\']+)["\']', re.I)


def _extract_algolia_creds(html: str) -> tuple[str, str, str] | None:
    """
    Extract (app_id, api_key, index_name) from the YC jobs page HTML.
    Returns None if extraction fails.
    """
    # Look for window.AlgoliaOpts or similar config blob
    algolia_block = re.search(r'AlgoliaOpts\s*[=:]\s*(\{[^}]+\})', html, re.S)
    if algolia_block:
        blob = algolia_block.group(1)
        app_match  = re.search(r'appId["\']?\s*:\s*["\']([^"\']+)["\']', blob)
        key_match  = re.search(r'(?:apiKey|searchKey)["\']?\s*:\s*["\']([^"\']+)["\']', blob)
        idx_match  = re.search(r'indexName["\']?\s*:\s*["\']([^"\']+)["\']', blob)
        if app_match and key_match and idx_match:
            return app_match.group(1), key_match.group(1), idx_match.group(1)

    # Fallback: scan for Algolia config patterns anywhere in the page
    app_ids = _ALGOLIA_APP_RE.findall(html)
    api_keys = _ALGOLIA_KEY_RE.findall(html)
    idx_names = _ALGOLIA_IDX_RE.findall(html)

    if app_ids and api_keys and idx_names:
        return app_ids[0], api_keys[0], idx_names[0]

    return None


def _parse_hit(hit: dict) -> dict:
    """Normalize an Algolia search hit to the shared job contract."""
    location = hit.get("location") or hit.get("city") or ""
    remote_flag = hit.get("remote") or hit.get("isRemote")

    return {
        "title":      hit.get("title") or hit.get("jobTitle", ""),
        "company":    hit.get("company") or hit.get("companyName", ""),
        "location":   location,
        "remote":     _is_remote(location, bool(remote_flag) if remote_flag is not None else None),
        "url":        hit.get("url") or hit.get("jobUrl", ""),
        "posted_at":  hit.get("publishedAt") or hit.get("createdAt", ""),
        "source":     SOURCE_NAME,
        "salary_min": None,
        "salary_max": None,
    }


async def _query_algolia(
    client: httpx.AsyncClient,
    app_id: str,
    api_key: str,
    index_name: str,
    query: str = "",
    filters: str = "",
    page: int = 0,
) -> dict:
    """POST a search query to the Algolia index."""
    url = f"https://{app_id}-dsn.algolia.net/1/indexes/{index_name}/query"
    payload = {
        "query":            query,
        "filters":          filters,
        "hitsPerPage":      PAGE_SIZE,
        "page":             page,
        "attributesToRetrieve": [
            "title", "company", "companyName", "location", "city",
            "remote", "isRemote", "url", "jobUrl",
            "publishedAt", "createdAt", "jobTitle",
        ],
    }
    resp = await client.post(
        url,
        json=payload,
        headers={
            "X-Algolia-Application-Id": app_id,
            "X-Algolia-API-Key":        api_key,
        },
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()


async def fetch_jobs(client: httpx.AsyncClient) -> list[dict]:
    """
    Fetch remote jobs from the YC job board via Algolia.
    Extracts Algolia credentials from the page HTML on each run.
    Returns only remote jobs.
    """
    # Step 1: load the page and extract Algolia credentials
    try:
        resp = await client.get(YC_JOBS_URL, timeout=15.0)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [yc] failed to load job page: {e}")
        return []

    creds = _extract_algolia_creds(resp.text)
    if not creds:
        print("  [yc] could not extract Algolia credentials from page")
        return []

    app_id, api_key, index_name = creds

    # Step 2: paginate through results, filtering to remote jobs
    all_jobs: list[dict] = []
    page = 0
    while True:
        try:
            data = await _query_algolia(
                client, app_id, api_key, index_name,
                filters="remote:true",
                page=page,
            )
        except Exception as e:
            print(f"  [yc] Algolia query failed (page {page}): {e}")
            break

        hits = data.get("hits", [])
        all_jobs.extend(_parse_hit(h) for h in hits)

        if page >= data.get("nbPages", 1) - 1 or not hits:
            break
        page += 1

    return all_jobs
