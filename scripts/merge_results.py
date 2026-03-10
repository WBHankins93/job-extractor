"""
scripts/merge_results.py
------------------------
Merge all pipeline outputs into one consolidated CSV.

Reads:
  output/rescored-jobs.csv   — ATS-sourced jobs (full JD scored)
  output/board-jobs.csv      — board-sourced jobs (Levels, YC, Getro, etc.)
  output/founding-jobs.csv   — founding engineer roles from board sources

Writes:
  output/all-jobs.csv        — unified, deduplicated, sorted by fit score

Run after the full pipeline:
    python3 scripts/merge_results.py
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT       = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"

RESCORED  = OUTPUT_DIR / "rescored-jobs.csv"
BOARD     = OUTPUT_DIR / "board-jobs.csv"
FOUNDING  = OUTPUT_DIR / "founding-jobs.csv"
OUT_PATH  = OUTPUT_DIR / "all-jobs.csv"

# Columns in the final unified CSV — order matters for readability
OUTPUT_COLS = [
    "source",
    "company",
    "job_title",
    "job_url",
    "location",
    "role_type",
    "level",
    "fit_score",
    "posted_at",
    "salary_min",
    "salary_max",
    "resume_used",
]


def _load_rescored(path: Path) -> pd.DataFrame:
    """Normalise rescored-jobs.csv → unified schema."""
    df = pd.read_csv(path)
    return pd.DataFrame({
        "source":      df["ats"],
        "company":     df["company_name"],
        "job_title":   df["job_title"],
        "job_url":     df["job_url"],
        "location":    "",                        # ATS batch APIs don't include location
        "role_type":   df["role_type"],
        "level":       df["level"],
        "fit_score":   df["fit_score_jd"],        # prefer full-JD score
        "posted_at":   "",
        "salary_min":  None,
        "salary_max":  None,
        "resume_used": df["resume_used"],
    })


def _load_board(path: Path, is_founding: bool = False) -> pd.DataFrame:
    """Normalise board-jobs.csv or founding-jobs.csv → unified schema."""
    df = pd.read_csv(path)
    if is_founding:
        df["role_type"] = "founding"
    return pd.DataFrame({
        "source":      df["source"],
        "company":     df["company"],
        "job_title":   df["job_title"],
        "job_url":     df["job_url"],
        "location":    df.get("location", ""),
        "role_type":   df["role_type"],
        "level":       df["level"],
        "fit_score":   df["fit_score"],
        "posted_at":   df.get("posted_at", ""),
        "salary_min":  df.get("salary_min"),
        "salary_max":  df.get("salary_max"),
        "resume_used": df["resume_used"],
    })


def main() -> None:
    frames: list[pd.DataFrame] = []

    if RESCORED.exists():
        df = _load_rescored(RESCORED)
        print(f"  rescored-jobs:  {len(df):>4} rows")
        frames.append(df)
    else:
        print(f"  rescored-jobs:  not found (run fetch_jds_and_rescore.py)")

    if BOARD.exists():
        df = _load_board(BOARD)
        print(f"  board-jobs:     {len(df):>4} rows")
        frames.append(df)
    else:
        print(f"  board-jobs:     not found (run fetch_board_jobs.py)")

    if FOUNDING.exists():
        df = _load_board(FOUNDING, is_founding=True)
        print(f"  founding-jobs:  {len(df):>4} rows")
        frames.append(df)
    else:
        print(f"  founding-jobs:  not found (run fetch_board_jobs.py)")

    if not frames:
        print("\nNo output files found — run the pipeline first.")
        return

    merged = pd.concat(frames, ignore_index=True)
    before = len(merged)

    # Deduplicate: same company + same URL is the same job regardless of source
    merged = merged.drop_duplicates(subset=["company", "job_url"], keep="first")
    dupes = before - len(merged)

    # Sort: best fit score first, then alphabetically within ties
    merged = merged.sort_values(
        ["fit_score", "company", "job_title"],
        ascending=[False, True, True],
    )

    OUTPUT_DIR.mkdir(exist_ok=True)
    merged[OUTPUT_COLS].to_csv(OUT_PATH, index=False)

    print(f"\n  {before} total → {dupes} duplicates removed → {len(merged)} unique jobs")
    print(f"\nSaved → {OUT_PATH}")

    # Quick breakdown
    print("\nBy role type:")
    print(merged["role_type"].value_counts().to_string())
    print("\nBy source:")
    print(merged["source"].value_counts().to_string())
    print(f"\nTop 10 by fit score:")
    display_cols = ["company", "job_title", "role_type", "fit_score", "source"]
    print(merged[display_cols].head(10).to_string(index=False))


if __name__ == "__main__":
    print("=== Merging pipeline outputs ===\n")
    main()
