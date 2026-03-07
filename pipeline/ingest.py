"""
pipeline/ingest.py
------------------
Stage 1: Raw data ingestion.

Reads the CSV, validates it, and returns a clean DataFrame.
Everything downstream depends on this being correct.
"""

import pandas as pd
from pathlib import Path


# The 5 target roles we're hunting for.
# Using a list here means we can easily add more later.
TARGET_ROLES = [
    "Full Stack Engineer",
    "Software Engineer",
    "Solutions Engineer",
    "Forward Deployed Engineer",
    "Technical Product Manager",
]


def load_companies(csv_path: str | Path) -> pd.DataFrame:
    """
    Load and validate the companies CSV.

    Returns a clean DataFrame with:
    - Consistent column names (lowercase, no spaces)
    - Rows with missing career_url removed
    - Two new empty columns ready for downstream stages
    """
    df = pd.read_csv(csv_path)

    print(f"Loaded {len(df)} companies from {csv_path}")

    # --- Validation ---
    # Check that the columns we need actually exist.
    required = {"name", "career_url"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV is missing required columns: {missing}")

    # Drop rows where we have no URL to work with.
    # No URL = nothing we can do for that company.
    before = len(df)
    df = df.dropna(subset=["career_url"])
    dropped = before - len(df)
    if dropped:
        print(f"  Dropped {dropped} rows with missing career_url")

    # Strip whitespace from URLs — common data quality issue.
    df["career_url"] = df["career_url"].str.strip()

    # --- Add output columns (empty for now, filled by later stages) ---
    # role_type: which of the 5 target roles was found, if any
    # remote:    True/False/None — does the company offer remote?
    df["role_type"] = None
    df["remote"] = None
    df["match"] = None  # green check equivalent

    print(f"  {len(df)} companies ready for processing")
    print(f"  Columns: {list(df.columns)}\n")

    return df


def summary(df: pd.DataFrame) -> None:
    """Print a quick summary of the DataFrame — useful for debugging."""
    print("=== Dataset Summary ===")
    print(f"Total companies:  {len(df)}")
    print(f"Industries:       {df['industry'].nunique() if 'industry' in df.columns else 'N/A'}")
    print(f"Unique locations: {df['location'].nunique() if 'location' in df.columns else 'N/A'}")
    print(f"\nSample rows:")
    print(df[["name", "career_url"]].head(5).to_string(index=False))
    print()


if __name__ == "__main__":
    # Run this file directly to test the ingestion stage in isolation.
    # This is a good pattern: every pipeline stage should be independently testable.
    csv_path = Path(__file__).parent.parent / "data" / "Forbes_Best_Startup_Employers_2026_FINAL.csv"
    df = load_companies(csv_path)
    summary(df)
