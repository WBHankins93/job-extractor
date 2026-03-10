"""
pipeline/sources/
-----------------
Job board adapters — each fetches jobs from a specific board site and
normalizes them to the shared job dict contract:

    {
        "title":     str,
        "company":   str,
        "location":  str,
        "remote":    bool,
        "url":       str,
        "posted_at": str,   # ISO 8601 or ""
        "source":    str,   # adapter name ("levels", "yc", "getro")
        "salary_min": int | None,   # levels.fyi only
        "salary_max": int | None,   # levels.fyi only
    }

All adapters expose a single coroutine:
    async def fetch_jobs(client: httpx.AsyncClient) -> list[dict]
"""
