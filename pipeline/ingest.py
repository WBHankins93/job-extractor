"""
pipeline/ingest.py
------------------
Stage 1: Raw data ingestion.

Reads the CSV, validates it, and returns a clean DataFrame.
Everything downstream depends on this being correct.
"""

import re

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

# Titles matching this pattern are excluded from role matching.
# Covers management track, over-senior IC (Staff/Principal), and leadership
# roles — all inappropriate for a ≤6 year IC job search.
_EXCLUDE_RE = re.compile(
    r"\b(lead|manager|management|director|vp|vice[\s-]*president|"
    r"head\s+of|chief|principal|staff|president|partner|"
    r"cto|ceo|coo|cfo)\b",
    re.I,
)

# Additional phrases (per canonical role) that are equivalent to a TARGET_ROLES
# entry but wouldn't be caught by simple substring matching.  E.g. Amazon uses
# "Software Development Engineer" / "SDE" rather than "Software Engineer".
_ROLE_ALIASES: dict[str, list[str]] = {
    "Software Engineer": ["Software Development Engineer", " SDE "],
}

# Seniority label parsed from title for display in the report.
_LEVEL_PATTERNS = [
    ("junior", re.compile(r"\b(junior|jr\.?|entry.?level|associate)\b", re.I)),
    ("senior", re.compile(r"\b(senior|sr\.?)\b",                        re.I)),
]

# Founding engineer regex — matches any "founding ... engineer" or
# "engineer ... founding" variant regardless of word order.
_FOUNDING_RE = re.compile(
    r"\bfounding\b.*\bengineer\b|\bengineer\b.*\bfounding\b", re.I
)


def parse_level(title: str) -> str:
    """Return 'junior', 'senior', or 'mid' (default for unlabeled IC roles)."""
    for label, pattern in _LEVEL_PATTERNS:
        if pattern.search(title):
            return label
    return "mid"


def matches_target_role(title: str) -> str | None:
    """
    Return the matched TARGET_ROLES entry for `title`, or None.

    Returns None for any management, lead, or over-senior-IC title.

    Matching order:
      1. Find the first target role (or alias) whose phrase appears in the
         title via case-insensitive substring search.
      2. Strip that matched phrase from the title, then apply _EXCLUDE_RE
         to the *remainder* — this prevents words that are legitimately part
         of a target role (e.g. "manager" in "Technical Product Manager")
         from triggering the exclusion, while still blocking modifiers like
         "Lead", "Director of", etc. that wrap an otherwise valid role.
    """
    title_lower = title.lower()

    # Step 1: find the first matching role (canonical name or alias).
    matched_role: str | None = None
    matched_phrase: str | None = None
    for role in TARGET_ROLES:
        phrases = [role] + _ROLE_ALIASES.get(role, [])
        for phrase in phrases:
            if phrase.lower() in title_lower:
                matched_role = role
                matched_phrase = phrase.lower()
                break
        if matched_role:
            break

    if matched_role is None:
        return None

    # Step 2: check exclusions on the part of the title outside the role phrase.
    remainder = title_lower.replace(matched_phrase, "")  # type: ignore[arg-type]
    if _EXCLUDE_RE.search(remainder):
        return None

    return matched_role


def matches_founding_role(title: str) -> bool:
    """
    True if the title describes a Founding Engineer role that is NOT already
    captured by matches_target_role() — e.g. standalone 'Founding Engineer'.

    'Founding Full Stack Engineer' → already matched by matches_target_role()
    so this returns False.  'Founding Engineer' → not matched by any target
    role, so this returns True.
    """
    return bool(_FOUNDING_RE.search(title)) and matches_target_role(title) is None


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
