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

    # remote column: pandas reads CSV booleans as Python True/False
    remote = df[df["remote"] == True].copy()

    remote.to_csv(OUTPUT_CSV, index=False)

    print(f"Saved {len(remote)} remote companies → {OUTPUT_CSV}")
    if len(remote):
        matched = (remote["match"] == "✓").sum()
        print(f"  {matched} with role match (✓), {len(remote) - matched} without")


if __name__ == "__main__":
    main()
