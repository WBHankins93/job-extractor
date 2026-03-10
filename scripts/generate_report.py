"""
scripts/generate_report.py
--------------------------
Print a Rich terminal report combining:
  - output/rescored-jobs.csv  (ATS pipeline: Forbes 500 companies)
  - output/board-jobs.csv     (board sources: Levels, YC, Getro — optional)

Groups jobs by company ordered by best fit score. Shows tier, score delta,
source tag, salary (where available), and apply link.

Usage:
    python scripts/generate_report.py                  # default: >= 0.75
    python scripts/generate_report.py --min-score 0.85 # strong matches only
    python scripts/generate_report.py --ats-only       # skip board sources
    python scripts/generate_report.py --boards-only    # skip ATS results
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

RESCORED_CSV  = Path("output/rescored-jobs.csv")
BOARD_CSV     = Path("output/board-jobs.csv")
FOUNDING_CSV  = Path("output/founding-jobs.csv")


def _tier(score: float) -> tuple[str, str]:
    if score >= 0.85:
        return "Strong", "bold green"
    if score >= 0.75:
        return "Good", "yellow"
    return "Weak", "dim"


def _fmt_delta(delta: float | None) -> Text:
    if delta is None:
        return Text("—", style="dim")
    s = f"+{delta:.3f}" if delta > 0 else f"{delta:.3f}"
    color = "green" if delta > 0.005 else ("dim" if abs(delta) <= 0.005 else "red")
    return Text(s, style=color)


def _fmt_salary(salary_min, salary_max) -> str:
    if pd.isna(salary_min) and pd.isna(salary_max):
        return ""
    lo = f"${int(salary_min):,}" if not pd.isna(salary_min) else "?"
    hi = f"${int(salary_max):,}" if not pd.isna(salary_max) else "?"
    return f"{lo}–{hi}"


def _truncate(url: str, max_len: int = 60) -> str:
    return url if len(url) <= max_len else url[: max_len - 3] + "..."


def _source_badge(source: str) -> Text:
    colors = {
        "levels":  "bright_blue",
        "yc":      "bright_yellow",
        "getro":   "bright_magenta",
        "ats":     "dim",
    }
    return Text(source.upper(), style=colors.get(source, "white"))


def _fmt_level(level: str) -> Text:
    if level == "senior":
        return Text("senior", style="cyan bold")
    if level == "junior":
        return Text("junior", style="dim")
    return Text("mid", style="white")


def _load_rescored(min_score: float) -> pd.DataFrame:
    """Load rescored-jobs.csv and normalize to the shared display schema."""
    if not RESCORED_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(RESCORED_CSV)
    df = df[df["fit_score_jd"] >= min_score].copy()
    df["score_delta"] = (df["fit_score_jd"] - df["fit_score_title"]).round(3)
    return pd.DataFrame({
        "company":     df.get("company_name", df.get("company", "")),
        "job_title":   df.get("job_title", ""),
        "job_url":     df.get("job_url", ""),
        "fit_score":   df["fit_score_jd"],
        "score_delta": df["score_delta"],
        "jd_found":    df.get("jd_found", True),
        "source":      "ats",
        "level":       df["level"] if "level" in df.columns else "mid",
        "posted_at":   df.get("posted_at", ""),
        "salary_min":  None,
        "salary_max":  None,
    })


def _load_board(min_score: float) -> pd.DataFrame:
    """Load board-jobs.csv and normalize to the shared display schema."""
    if not BOARD_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(BOARD_CSV)
    df = df[df["fit_score"] >= min_score].copy()
    return pd.DataFrame({
        "company":     df.get("company", ""),
        "job_title":   df.get("job_title", ""),
        "job_url":     df.get("job_url", ""),
        "fit_score":   df["fit_score"],
        "score_delta": None,
        "jd_found":    True,
        "source":      df.get("source", "board"),
        "level":       df["level"] if "level" in df.columns else "mid",
        "posted_at":   df.get("posted_at", ""),
        "salary_min":  df.get("salary_min"),
        "salary_max":  df.get("salary_max"),
    })


def _load_founding() -> pd.DataFrame:
    """Load founding-jobs.csv — no minimum score filter (show all)."""
    if not FOUNDING_CSV.exists():
        return pd.DataFrame()
    return pd.read_csv(FOUNDING_CSV)


def _print_founding_table(console: Console, df: pd.DataFrame) -> None:
    """Print a separate table for Founding Engineer roles (all scores shown)."""
    df = df.sort_values("fit_score", ascending=False)
    has_salary = "salary_min" in df.columns and not df["salary_min"].isna().all()

    table = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold magenta",
        expand=False,
        padding=(0, 1),
        title="[bold magenta]Founding Engineer Roles[/bold magenta]",
        title_justify="left",
    )
    table.add_column("Company",  style="bold cyan", min_width=18, no_wrap=True)
    table.add_column("Role",     min_width=30)
    table.add_column("Src",      min_width=5,  justify="center")
    table.add_column("Score",    min_width=5,  justify="right")
    if has_salary:
        table.add_column("Salary", min_width=14, justify="right")
    table.add_column("Apply URL")

    for _, row in df.iterrows():
        score = float(row.get("fit_score", 0))
        salary_min = row.get("salary_min")
        salary_max = row.get("salary_max")
        cells = [
            str(row.get("company", "")),
            str(row.get("job_title", "")),
            _source_badge(str(row.get("source", ""))),
            f"{score:.3f}",
        ]
        if has_salary:
            cells.append(_fmt_salary(salary_min, salary_max))
        cells.append(_truncate(str(row.get("job_url", ""))))
        table.add_row(*cells)

    console.print(table)
    console.print(f"  [magenta]{len(df)}[/magenta] founding engineer role(s) found\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Print job match report")
    parser.add_argument("--min-score",   type=float, default=0.75)
    parser.add_argument("--ats-only",    action="store_true")
    parser.add_argument("--boards-only", action="store_true")
    args = parser.parse_args()

    frames = []
    if not args.boards_only:
        ats_df = _load_rescored(args.min_score)
        if not ats_df.empty:
            frames.append(ats_df)
        elif not args.ats_only:
            print(f"[warn] {RESCORED_CSV} not found or empty — run fetch_jds_and_rescore.py")

    if not args.ats_only:
        board_df = _load_board(args.min_score)
        if not board_df.empty:
            frames.append(board_df)
        elif not args.boards_only:
            print(f"[info] {BOARD_CSV} not found — run fetch_board_jobs.py to include board sources")

    if not frames:
        print("No data found. Run the pipeline first.")
        sys.exit(1)

    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values("fit_score", ascending=False)

    if df.empty:
        print(f"No jobs with fit_score >= {args.min_score}")
        sys.exit(0)

    has_salary = not df["salary_min"].isna().all()

    # Order companies by their best score
    company_order = (
        df.groupby("company")["fit_score"]
        .max()
        .sort_values(ascending=False)
        .index
    )

    console = Console()
    table = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold",
        expand=False,
        padding=(0, 1),
    )
    table.add_column("Company",  style="bold cyan", min_width=18, no_wrap=True)
    table.add_column("Role",     min_width=26)
    table.add_column("Src",      min_width=5,  justify="center")
    table.add_column("Level",    min_width=6,  justify="center")
    table.add_column("Tier",     min_width=6,  justify="center")
    table.add_column("Score",    min_width=5,  justify="right")
    table.add_column("Δ",        min_width=6,  justify="right")
    if has_salary:
        table.add_column("Salary", min_width=14, justify="right")
    table.add_column("Apply URL")

    strong_count = good_count = 0

    for company in company_order:
        group = df[df["company"] == company]
        first = True
        for _, row in group.iterrows():
            score = float(row["fit_score"])
            label, color = _tier(score)
            if label == "Strong":
                strong_count += 1
            elif label == "Good":
                good_count += 1

            delta = row.get("score_delta")
            level_val = str(row.get("level", "mid")) if not pd.isna(row.get("level", "mid")) else "mid"
            cells = [
                company if first else "",
                str(row.get("job_title", "")),
                _source_badge(str(row.get("source", ""))),
                _fmt_level(level_val),
                Text(label, style=color),
                f"{score:.3f}",
                _fmt_delta(None if pd.isna(delta) else float(delta)),
            ]
            if has_salary:
                cells.append(_fmt_salary(row.get("salary_min"), row.get("salary_max")))
            cells.append(_truncate(str(row.get("job_url", ""))))

            table.add_row(*cells)
            first = False

    console.print()
    console.print(table)

    # Summary footer
    source_counts = df.groupby("source").size().to_dict()
    src_str = "  ".join(f"[dim]{k}:{v}[/dim]" for k, v in sorted(source_counts.items()))
    console.print(
        f"  [bold green]{strong_count}[/bold green] strong  "
        f"[bold yellow]{good_count}[/bold yellow] good  "
        f"[dim](min score {args.min_score})[/dim]  {src_str}"
    )
    console.print()

    # --- Founding Engineer table (separate, no min-score filter) ---
    if not args.ats_only:
        founding_df = _load_founding()
        if not founding_df.empty:
            _print_founding_table(console, founding_df)


if __name__ == "__main__":
    main()
