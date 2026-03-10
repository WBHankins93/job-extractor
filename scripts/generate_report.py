"""
scripts/generate_report.py
--------------------------
Print a Rich terminal report from output/rescored-jobs.csv.

Groups jobs by company (ordered by best fit score), shows tier,
score delta (JD score vs title-only score), and apply link.

Usage:
    python scripts/generate_report.py                  # default: >= 0.75
    python scripts/generate_report.py --min-score 0.85 # strong matches only
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

RESCORED_CSV = Path("output/rescored-jobs.csv")


def _tier(score: float) -> tuple[str, str]:
    if score >= 0.85:
        return "Strong", "bold green"
    if score >= 0.75:
        return "Good", "yellow"
    return "Weak", "dim"


def _fmt_delta(delta: float) -> Text:
    s = f"+{delta:.3f}" if delta > 0 else f"{delta:.3f}"
    color = "green" if delta > 0.005 else ("dim" if abs(delta) <= 0.005 else "red")
    return Text(s, style=color)


def _truncate(url: str, max_len: int = 65) -> str:
    return url if len(url) <= max_len else url[: max_len - 3] + "..."


def main() -> None:
    parser = argparse.ArgumentParser(description="Print job match report")
    parser.add_argument(
        "--min-score", type=float, default=0.75,
        help="Minimum fit_score_jd to include (default: 0.75)",
    )
    args = parser.parse_args()

    if not RESCORED_CSV.exists():
        print(f"[error] {RESCORED_CSV} not found. Run fetch_jds_and_rescore.py first.")
        sys.exit(1)

    df = pd.read_csv(RESCORED_CSV)
    df = df[df["fit_score_jd"] >= args.min_score].copy()
    df = df.sort_values("fit_score_jd", ascending=False)

    if df.empty:
        print(f"No jobs with fit_score_jd >= {args.min_score}")
        sys.exit(0)

    df["score_delta"] = (df["fit_score_jd"] - df["fit_score_title"]).round(3)

    # Order companies by their best (highest) score
    company_order = df.groupby("company_name")["fit_score_jd"].max().sort_values(ascending=False).index

    console = Console()
    table = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold",
        expand=False,
        padding=(0, 1),
    )
    table.add_column("Company", style="bold cyan", min_width=18, no_wrap=True)
    table.add_column("Role", min_width=28)
    table.add_column("Tier", min_width=6, justify="center")
    table.add_column("Score", min_width=5, justify="right")
    table.add_column("Delta", min_width=6, justify="right")
    table.add_column("JD", min_width=2, justify="center")
    table.add_column("Apply URL")

    strong_count = good_count = 0

    for company in company_order:
        group = df[df["company_name"] == company]
        first = True
        for _, row in group.iterrows():
            score = float(row["fit_score_jd"])
            label, color = _tier(score)
            if label == "Strong":
                strong_count += 1
            elif label == "Good":
                good_count += 1

            jd_found = bool(row.get("jd_found", False))
            jd_cell = Text("✓", style="green") if jd_found else Text("-", style="dim")

            table.add_row(
                company if first else "",
                str(row.get("job_title", "")),
                Text(label, style=color),
                f"{score:.3f}",
                _fmt_delta(float(row["score_delta"])),
                jd_cell,
                _truncate(str(row.get("job_url", ""))),
            )
            first = False

    console.print()
    console.print(table)
    console.print(
        f"  [bold green]{strong_count}[/bold green] strong  "
        f"[bold yellow]{good_count}[/bold yellow] good  "
        f"[dim](min score {args.min_score})[/dim]"
    )
    console.print()


if __name__ == "__main__":
    main()
