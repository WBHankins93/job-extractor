"""
scripts/export_remote_roles.py
------------------------------
Extract all remote-role companies from pipeline results and save to a
separate CSV for focused review.

Run after the pipeline:  python main.py
Then:                    python scripts/export_remote_roles.py

Output: output/remote-roles.csv
"""

import pandas as pd
from pathlib import Path

INPUT_CSV  = Path(__file__).resolve().parent.parent / "output" / "results.csv"
OUTPUT_CSV = Path(__file__).resolve().parent.parent / "output" / "remote-roles.csv"


def main() -> None:
    if not INPUT_CSV.exists():
        print(f"Results file not found: {INPUT_CSV}")
        print("Run `python main.py` first.")
        return

    df = pd.read_csv(INPUT_CSV)

    # Only export companies that are remote AND matched a target role.
    # Without the match filter, non-matched companies (match=NaN) flow into
    # fetch_jds_and_rescore.py and can appear in the report via semantic
    # similarity on unrelated job titles.
    remote = df[(df["remote"] == True) & (df["match"] == "✓")].copy()

    remote.to_csv(OUTPUT_CSV, index=False)

    print(f"Saved {len(remote)} remote+matched companies → {OUTPUT_CSV}")
    all_remote = (df["remote"] == True).sum()
    unmatched  = all_remote - len(remote)
    if unmatched:
        print(f"  (filtered out {unmatched} remote companies with no role match)")


if __name__ == "__main__":
    main()
