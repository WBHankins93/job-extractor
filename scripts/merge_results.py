"""
scripts/merge_results.py
------------------------
Merge all pipeline outputs into one consolidated CSV.

Reads:
  output/rescored-jobs.csv   — ATS-sourced jobs (full JD scored)
  output/board-jobs.csv      — board-sourced jobs (Levels, YC, Getro, etc.)
  output/founding-jobs.csv   — founding engineer roles from board sources

Writes:
  output/all-jobs.csv        — unified, deduplicated, sorted by score

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

# Final column order — front-loaded with the three most-used fields
OUTPUT_COLS = [
    "Company",
    "Title",
    "URL",
    "Role",
    "Level",
    "Score",
    "Source",
    "Location",
    "Posted",
    "Salary Min",
    "Salary Max",
]


def _load_rescored(path: Path) -> pd.DataFrame:
    """Normalise rescored-jobs.csv → unified schema."""
    df = pd.read_csv(path)
    return pd.DataFrame({
        "Company":    df["company_name"],
        "Title":      df["job_title"],
        "URL":        df["job_url"],
        "Role":       df["role_type"],
        "Level":      df["level"],
        "Score":      (df["fit_score_jd"] * 100).round(1),  # 0.882 → 88.2
        "Source":     df["ats"],
        "Location":   "",
        "Posted":     "",
        "Salary Min": "",
        "Salary Max": "",
    })


def _load_board(path: Path, is_founding: bool = False) -> pd.DataFrame:
    """Normalise board-jobs.csv or founding-jobs.csv → unified schema."""
    df = pd.read_csv(path)
    role_col = "founding" if is_founding else df["role_type"]
    salary_min = df["salary_min"] if "salary_min" in df.columns else ""
    salary_max = df["salary_max"] if "salary_max" in df.columns else ""
    return pd.DataFrame({
        "Company":    df["company"],
        "Title":      df["job_title"],
        "URL":        df["job_url"],
        "Role":       role_col,
        "Level":      df["level"],
        "Score":      (df["fit_score"] * 100).round(1),
        "Source":     df["source"],
        "Location":   df["location"] if "location" in df.columns else "",
        "Posted":     df["posted_at"] if "posted_at" in df.columns else "",
        "Salary Min": salary_min,
        "Salary Max": salary_max,
    })


def main() -> None:
    frames: list[pd.DataFrame] = []

    if RESCORED.exists():
        df = _load_rescored(RESCORED)
        print(f"  rescored-jobs:  {len(df):>4} rows")
        frames.append(df)
    else:
        print("  rescored-jobs:  not found (run fetch_jds_and_rescore.py)")

    if BOARD.exists():
        df = _load_board(BOARD)
        print(f"  board-jobs:     {len(df):>4} rows")
        frames.append(df)
    else:
        print("  board-jobs:     not found (run fetch_board_jobs.py)")

    if FOUNDING.exists():
        df = _load_board(FOUNDING, is_founding=True)
        print(f"  founding-jobs:  {len(df):>4} rows")
        frames.append(df)
    else:
        print("  founding-jobs:  not found (run fetch_board_jobs.py)")

    if not frames:
        print("\nNo output files found — run the pipeline first.")
        return

    merged = pd.concat(frames, ignore_index=True)
    before = len(merged)

    # Deduplicate: same company + same URL = same job regardless of source
    merged = merged.drop_duplicates(subset=["Company", "URL"], keep="first")
    dupes = before - len(merged)

    # Sort: best score first, then alpha within ties
    merged = merged.sort_values(
        ["Score", "Company", "Title"],
        ascending=[False, True, True],
    )

    # Strip leading/trailing whitespace from text columns
    for col in ("Company", "Title", "Location"):
        merged[col] = merged[col].astype(str).str.strip()

    # Replace NaN/None/empty with blank string — no "NaN" in the CSV
    merged = merged.fillna("").replace({None: ""})

    OUTPUT_DIR.mkdir(exist_ok=True)
    merged[OUTPUT_COLS].to_csv(OUT_PATH, index=False)

    print(f"\n  {before} total → {dupes} duplicates removed → {len(merged)} unique jobs")
    print(f"\nSaved → {OUT_PATH}")

    # Summary
    print("\nBy role:")
    print(merged["Role"].value_counts().to_string())
    print("\nBy source:")
    print(merged["Source"].value_counts().to_string())
    print(f"\nTop 10 by score:")
    print(merged[["Company", "Title", "Role", "Score"]].head(10).to_string(index=False))


if __name__ == "__main__":
    print("=== Merging pipeline outputs ===\n")
    main()
