"""
main.py
-------
Orchestrates the full pipeline.

Run: python main.py
"""

import asyncio
import pandas as pd
import httpx
from pathlib import Path

from pipeline.ingest import load_companies, TARGET_ROLES
from pipeline.ats import detect_ats, fetch_jobs
from pipeline.embed import (
    load_resumes, get_chroma_client, build_resume_collection,
    score_job_fit, ROLE_TO_RESUME
)


DATA_DIR   = Path("data")
OUTPUT_DIR = Path("output")
CSV_PATH   = DATA_DIR / "Forbes_Best_Startup_Employers_2026_FINAL.csv"


def matches_target_role(title: str) -> str | None:
    """
    Check if a job title matches one of our 5 target roles.
    Case-insensitive partial match — 'Senior Software Engineer' matches 'Software Engineer'.
    Returns the matched role name, or None.
    """
    title_lower = title.lower()
    for role in TARGET_ROLES:
        if role.lower() in title_lower:
            return role
    return None


async def process_companies(df: pd.DataFrame, resume_collection) -> pd.DataFrame:
    """
    For each company:
      1. Detect which ATS they use (fetches career pages concurrently)
      2. Fetch their job listings via ATS API
      3. Check for remote positions
      4. Check for target roles
      5. Score fit against the matched resume using embeddings
    """
    OUTPUT_DIR.mkdir(exist_ok=True)

    async with httpx.AsyncClient(
        headers={"User-Agent": "job-search-tool/1.0"},
        follow_redirects=True,
    ) as client:

        # --- Stage 1: ATS detection (concurrent, throttled to avoid hammering ATS probe APIs) ---
        print("Detecting ATS platforms...")
        df["ats"] = None
        df["api_url"] = None

        # Semaphore limits concurrent detections to prevent thundering-herd on probe APIs
        # (slug-guessing probes hit greenhouse/lever/ashby/etc. for every unknown company)
        sem = asyncio.Semaphore(40)

        async def detect_throttled(url: str) -> tuple:
            async with sem:
                return await detect_ats(url, client)

        detect_tasks = [detect_throttled(row["career_url"]) for _, row in df.iterrows()]
        detect_results = await asyncio.gather(*detect_tasks)

        for idx, (ats, api_url) in zip(df.index, detect_results):
            df.at[idx, "ats"] = ats
            df.at[idx, "api_url"] = api_url

        ats_counts = df["ats"].value_counts()
        print(f"  {ats_counts.to_dict()}\n")

        # --- Stage 2: fetch jobs (concurrent, only for companies with known ATS) ---
        known = df[df["ats"] != "unknown"].copy()
        print(f"Fetching jobs for {len(known)} companies with known ATS...")
        print(f"  (Skipping {len(df) - len(known)} companies with unknown ATS)\n")

        tasks = [fetch_jobs(row["ats"], row["api_url"], client) for _, row in known.iterrows()]
        results = await asyncio.gather(*tasks)

        # --- Stage 3: match roles + score resume fit ---
        print("Matching roles and scoring resume fit...")
        matched = 0

        for (idx, row), jobs in zip(known.iterrows(), results):
            if not jobs:
                continue

            has_remote = any(j["remote"] for j in jobs)
            df.at[idx, "remote"] = has_remote

            # Collect all matching remote jobs with their titles
            matched_jobs = []
            for job in jobs:
                role = matches_target_role(job["title"])
                if role and has_remote:
                    matched_jobs.append((role, job))

            if not matched_jobs:
                continue

            # Deduplicate roles for display
            found_roles = list({role for role, _ in matched_jobs})
            df.at[idx, "role_type"] = ", ".join(found_roles)
            df.at[idx, "match"] = "✓"

            # --- Resume fit scoring ---
            # For each matched job, score the job description against
            # the resume we've mapped to that role type.
            # Take the highest score across all matched jobs.
            best_score = 0.0
            best_resume = None

            for role, job in matched_jobs:
                resume_file = ROLE_TO_RESUME.get(role)
                if not resume_file:
                    continue

                # Build a job description string from available fields
                jd_text = f"{job['title']} {job.get('location', '')}".strip()

                score = score_job_fit(jd_text, resume_file, resume_collection)
                if score > best_score:
                    best_score = score
                    best_resume = resume_file

            df.at[idx, "fit_score"] = best_score
            df.at[idx, "resume_used"] = best_resume
            matched += 1

        print(f"  {matched} companies matched (remote + target role)\n")

    return df


def save_output(df: pd.DataFrame) -> None:
    """Save enriched results to CSV, sorted by fit score descending."""
    out_path = OUTPUT_DIR / "results.csv"

    output_cols = [
        "rank", "name", "industry", "location", "career_url",
        "ats", "remote", "role_type", "resume_used", "fit_score", "match"
    ]
    # Only keep columns that exist (fit_score/resume_used may be absent if no matches)
    existing = [c for c in output_cols if c in df.columns]
    out = df[existing].copy()

    # Sort matches by fit score so best fits rise to the top
    out = out.sort_values("fit_score", ascending=False, na_position="last")
    out.to_csv(out_path, index=False)

    print(f"Saved → {out_path}")

    matches = df[df["match"] == "✓"].copy()
    matches = matches.sort_values("fit_score", ascending=False)

    found = len(matches)
    unfound = len(df) - found

    # Breakdown of unfound: why each company has no match
    unknown_ats = (df["ats"] == "unknown").sum()
    known_no_jobs = ((df["ats"] != "unknown") & df["remote"].isna()).sum()
    no_remote = ((df["ats"] != "unknown") & (df["remote"] == False)).sum()
    remote_no_role = ((df["ats"] != "unknown") & (df["remote"] == True) & (df["match"] != "✓")).sum()

    print(f"\n=== Results ===")
    print(f"Total companies processed: {len(df)}")
    print(f"Companies with known ATS:  {(df['ats'] != 'unknown').sum()}")
    print(f"Companies offering remote: {df['remote'].sum()}")
    print(f"Companies with role match: {found}")
    print(f"Unfound: {unfound}")
    print(f"  unknown ATS: {unknown_ats}, known ATS no jobs: {known_no_jobs}, no remote: {no_remote}, remote but no role: {remote_no_role}")

    if len(matches):
        print(f"\nTop matches by fit score:")
        display = matches[["name", "role_type", "resume_used", "fit_score"]].head(15)
        print(display.to_string(index=False))


async def main():
    print("=== Job Extractor Pipeline ===\n")

    # Load + clean the CSV
    df = load_companies(CSV_PATH)

    # Set up embedding layer (resume ingestion)
    print("Loading resumes and building vector index...")
    resumes = load_resumes()
    chroma = get_chroma_client()
    resume_collection = build_resume_collection(chroma, resumes)
    print()

    # Run the async pipeline
    df["fit_score"] = None
    df["resume_used"] = None
    df = await process_companies(df, resume_collection)

    save_output(df)


if __name__ == "__main__":
    asyncio.run(main())
