"""
pipeline/sources/hnhiring.py
----------------------------
Fetch remote jobs from the most recent "Ask HN: Who is hiring?" thread
via the Hacker News Algolia search API (https://hn.algolia.com/api/v1/).

Strategy:
  1. Find the most recent hiring story via Algolia full-text search.
  2. Fetch all top-level comments (job postings) with pagination.
  3. Filter to remote postings (comment contains "remote").
  4. Parse the first line of each comment — HN convention is:
         Company | Job Title | Location | ...
     Everything after the first `|` is best-effort.

The Algolia API is public, rate-limit-friendly, and returns structured
JSON — no HTML scraping required.
"""

import re
from html.parser import HTMLParser

import httpx

_ALGOLIA_SEARCH = "https://hn.algolia.com/api/v1/search_by_date"
_PAGE_SIZE      = 1000


# ---------------------------------------------------------------------------
# HTML stripping — same stdlib approach as fetch_jds_and_rescore.py
# ---------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self._parts.append(data)

    def get_text(self) -> str:
        return "\n".join(self._parts)


def _strip_html(html: str) -> str:
    p = _TextExtractor()
    try:
        p.feed(html)
    except Exception:
        return html
    return p.get_text()


# ---------------------------------------------------------------------------
# HN URL extractor
# ---------------------------------------------------------------------------

_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.I)


def _first_external_url(html: str, fallback: str) -> str:
    """Return the first non-HN href from the HTML, else fallback."""
    for url in _HREF_RE.findall(html):
        if "news.ycombinator.com" not in url:
            return url
    return fallback


# ---------------------------------------------------------------------------
# Algolia queries
# ---------------------------------------------------------------------------

async def _get_latest_hiring_story_id(client: httpx.AsyncClient) -> str | None:
    """Return the objectID of the most recent 'Ask HN: Who is hiring?' thread."""
    resp = await client.get(
        _ALGOLIA_SEARCH,
        params={
            "query":       "Ask HN: Who is hiring?",
            "tags":        "story",
            "hitsPerPage": 5,
        },
        timeout=10.0,
    )
    resp.raise_for_status()
    for hit in resp.json().get("hits", []):
        if "who is hiring" in hit.get("title", "").lower():
            return hit["objectID"]
    return None


async def _get_all_comments(client: httpx.AsyncClient, story_id: str) -> list[dict]:
    """Fetch all top-level comments for `story_id` with Algolia pagination."""
    comments: list[dict] = []
    page = 0
    while True:
        resp = await client.get(
            _ALGOLIA_SEARCH,
            params={
                "tags":        f"comment,story_{story_id}",
                "hitsPerPage": _PAGE_SIZE,
                "page":        page,
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", [])
        if not hits:
            break
        comments.extend(hits)
        if len(hits) < _PAGE_SIZE:
            break
        page += 1
    return comments


# ---------------------------------------------------------------------------
# Comment parser
# ---------------------------------------------------------------------------

def _parse_comment(comment: dict) -> dict | None:
    """
    Parse a single HN comment into a normalized job dict.

    Returns None if:
    - comment has no text
    - "remote" does not appear in the text
    - we can't identify company + title from the first line
    """
    html = comment.get("comment_text", "")
    if not html:
        return None

    text = _strip_html(html)
    if "remote" not in text.lower():
        return None

    # HN convention: first non-blank line is the header
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return None

    parts = [p.strip() for p in lines[0].split("|")]
    company  = parts[0] if len(parts) >= 1 else ""
    title    = parts[1] if len(parts) >= 2 else ""
    location = parts[2] if len(parts) >= 3 else "Remote"

    # Discard obvious non-job first lines (very short or all-caps headings)
    if not company or not title or len(company) > 120:
        return None

    hn_item_url = (
        f"https://news.ycombinator.com/item?id={comment.get('objectID', '')}"
    )
    apply_url = _first_external_url(html, hn_item_url)

    return {
        "source":     "hnhiring",
        "company":    company,
        "title":      title,
        "url":        apply_url,
        "location":   location,
        "remote":     True,
        "posted_at":  comment.get("created_at", ""),
        "salary_min": None,
        "salary_max": None,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def fetch_jobs(client: httpx.AsyncClient) -> list[dict]:
    """
    Return normalized remote job dicts from the latest HN hiring thread.

    Uses the HN Algolia API — public, no auth, rate-limit-friendly.
    """
    story_id = await _get_latest_hiring_story_id(client)
    if not story_id:
        print("  [hnhiring] could not find latest hiring story")
        return []

    print(f"  [hnhiring] story {story_id} — fetching comments...")
    comments = await _get_all_comments(client, story_id)
    print(f"  [hnhiring] {len(comments)} comments to parse")

    results: list[dict] = []
    for c in comments:
        job = _parse_comment(c)
        if job:
            results.append(job)

    return results
