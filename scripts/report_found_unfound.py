"""
scripts/report_found_unfound.py
-------------------------------
Print found vs unfound job counts from pipeline results.

Run after the pipeline: python main.py
Then: python scripts/report_found_unfound.py

Reads output/results.csv and prints the same summary (found, unfound, breakdown)
without re-running the pipeline.
"""

import pandas as pd
from pathlib import Path

OUTPUT_CSV = Path(__file__).resolve().parent.parent / "output" / "results.csv"


def main() -> None:
    if not OUTPUT_CSV.exists():
        print(f"Results file not found: {OUTPUT_CSV}")
        print("Run `python main.py` first.")
        return

    df = pd.read_csv(OUTPUT_CSV)

    # Normalize boolean columns (CSV may have "True"/"False" strings)
    df["remote"] = df["remote"].map(
        lambda x: {"True": True, "False": False}.get(str(x), x) if pd.notna(x) else x
    )

    found = (df["match"] == "✓").sum()
    unfound = len(df) - found

    unknown_ats = (df["ats"] == "unknown").sum()
    known_no_jobs = ((df["ats"] != "unknown") & df["remote"].isna()).sum()
    no_remote = ((df["ats"] != "unknown") & (df["remote"] == False)).sum()
    remote_no_role = (
        (df["ats"] != "unknown")
        & (df["remote"] == True)
        & (df["match"] != "✓")
    ).sum()

    print("=== Found vs Unfound (from output/results.csv) ===")
    print(f"Total companies: {len(df)}")
    print(f"Found (role match): {found}")
    print(f"Unfound: {unfound}")
    print(
        f"  unknown ATS: {unknown_ats}, known ATS no jobs: {known_no_jobs}, "
        f"no remote: {no_remote}, remote but no role: {remote_no_role}"
    )


if __name__ == "__main__":
    main()
