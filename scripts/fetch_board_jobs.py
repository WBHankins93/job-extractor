"""
scripts/fetch_board_jobs.py
---------------------------
Fetch jobs from external board sources (Levels.fyi, YC, Getro) and score
them against resumes using the same embedding pipeline as main.py.

Run after main.py / fetch_jds_and_rescore.py:
    python scripts/fetch_board_jobs.py

Output: output/board-jobs.csv
Columns: source, company, job_title, job_url, location, remote,
         posted_at, salary_min, salary_max, role_type, resume_used,
         fit_score
"""

import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import pandas as pd

from pipeline.ingest import (
    matches_target_role,
    matches_founding_role,
    parse_level,
    is_us_location,
    within_experience_cap,
)
from pipeline.embed import (
    load_resumes, get_chroma_client, build_resume_collection,
    score_job_fit, ROLE_TO_RESUME,
)
from pipeline.sources import levels, yc, getro, hiringcafe, hnhiring
from main import MAX_AGE_DAYS, _is_fresh

OUTPUT_DIR   = Path("output")
OUT_PATH     = OUTPUT_DIR / "board-jobs.csv"
FOUNDING_OUT = OUTPUT_DIR / "founding-jobs.csv"


async def run(resume_collection) -> list[dict]:
    async with httpx.AsyncClient(
        headers={"User-Agent": "job-search-tool/1.0"},
        follow_redirects=True,
    ) as client:
        print("Fetching board sources concurrently...")
        results = await asyncio.gather(
            levels.fetch_jobs(client),
            yc.fetch_jobs(client),
            getro.fetch_jobs(client),
            hiringcafe.fetch_jobs(client),
            hnhiring.fetch_jobs(client),
            return_exceptions=True,
        )

    all_jobs: list[dict] = []
    names = ["levels", "yc", "getro", "hiringcafe", "hnhiring"]
    for name, result in zip(names, results):
        if isinstance(result, Exception):
            print(f"  [{name}] error: {result}")
        else:
            print(f"  [{name}] {len(result)} remote jobs fetched")
            all_jobs.extend(result)

    print(f"\nTotal across all boards: {len(all_jobs)} remote jobs")

    # --- Filter: freshness ---
    fresh = [j for j in all_jobs if _is_fresh(j.get("posted_at", ""))]
    stale = len(all_jobs) - len(fresh)
    print(f"Filtered {stale} stale jobs (>{MAX_AGE_DAYS}d old) → {len(fresh)} remaining\n")

    # --- Filter + score: role match ---
    print("Matching roles and scoring resume fit...")
    scored: list[dict] = []

    for job in fresh:
        role = matches_target_role(job["title"])
        if not role:
            continue
        if not within_experience_cap(job["title"]):
            continue
        if not is_us_location(job.get("location", "")):
            continue

        resume_file = ROLE_TO_RESUME.get(role)
        if not resume_file:
            # Try all resumes, take best
            best_score, best_resume = 0.0, None
            jd_text = f"{job['title']} {job.get('location', '')}".strip()
            for r_file in set(ROLE_TO_RESUME.values()):
                s = score_job_fit(jd_text, r_file, resume_collection)
                if s > best_score:
                    best_score, best_resume = s, r_file
        else:
            jd_text = f"{job['title']} {job.get('location', '')}".strip()
            best_score  = score_job_fit(jd_text, resume_file, resume_collection)
            best_resume = resume_file

        scored.append({
            "source":      job["source"],
            "company":     job["company"],
            "job_title":   job["title"],
            "job_url":     job["url"],
            "location":    job["location"],
            "remote":      job["remote"],
            "posted_at":   job.get("posted_at", ""),
            "salary_min":  job.get("salary_min"),
            "salary_max":  job.get("salary_max"),
            "role_type":   role,
            "level":       parse_level(job["title"]),
            "resume_used": best_resume,
            "fit_score":   round(best_score, 3),
        })

    print(f"  {len(scored)} jobs matched a target role")

    # --- Second pass: Founding Engineer (standalone, not already in main table) ---
    founding_scored: list[dict] = []
    all_resume_files = list(set(ROLE_TO_RESUME.values()))

    for job in fresh:
        if not matches_founding_role(job["title"]):
            continue
        if not is_us_location(job.get("location", "")):
            continue
        best_score, best_resume = 0.0, None
        jd_text = f"{job['title']} {job.get('location', '')}".strip()
        for r_file in all_resume_files:
            s = score_job_fit(jd_text, r_file, resume_collection)
            if s > best_score:
                best_score, best_resume = s, r_file
        founding_scored.append({
            "source":      job["source"],
            "company":     job["company"],
            "job_title":   job["title"],
            "job_url":     job["url"],
            "location":    job["location"],
            "remote":      job["remote"],
            "posted_at":   job.get("posted_at", ""),
            "salary_min":  job.get("salary_min"),
            "salary_max":  job.get("salary_max"),
            "role_type":   "founding",
            "level":       parse_level(job["title"]),
            "resume_used": best_resume,
            "fit_score":   round(best_score, 3),
        })

    print(f"  {len(founding_scored)} founding engineer roles found\n")
    return scored, founding_scored


def save(rows: list[dict], founding_rows: list[dict]) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)

    df = pd.DataFrame(rows).sort_values("fit_score", ascending=False)
    df.to_csv(OUT_PATH, index=False)
    print(f"Saved → {OUT_PATH}")

    strong = (df["fit_score"] >= 0.85).sum()
    good   = ((df["fit_score"] >= 0.75) & (df["fit_score"] < 0.85)).sum()
    print(f"  Strong (≥0.85): {strong}  Good (≥0.75): {good}  Total: {len(df)}")

    by_source = df.groupby("source")["fit_score"].count().to_dict()
    print(f"  By source: {by_source}")

    if founding_rows:
        fdf = pd.DataFrame(founding_rows).sort_values("fit_score", ascending=False)
        fdf.to_csv(FOUNDING_OUT, index=False)
        print(f"\nSaved {len(fdf)} founding roles → {FOUNDING_OUT}")


def main() -> None:
    print("=== Board Job Fetcher ===\n")

    print("Loading resumes and building vector index...")
    resumes           = load_resumes()
    chroma            = get_chroma_client()
    resume_collection = build_resume_collection(chroma, resumes)
    print()

    rows, founding_rows = asyncio.run(run(resume_collection))

    if rows:
        save(rows, founding_rows)
    else:
        print("No matching jobs found.")
        if founding_rows:
            save([], founding_rows)


if __name__ == "__main__":
    main()
