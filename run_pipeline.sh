#!/usr/bin/env bash
# run_pipeline.sh — run the full job extractor pipeline end-to-end
#
# Usage:
#   ./run_pipeline.sh           # full run (all stages)
#   ./run_pipeline.sh --boards  # board sources only (faster, skips ATS scan)
#
# Stages:
#   1. main.py                      — ATS detection + job fetch + role match
#   2. export_remote_roles.py       — filter to remote-matched companies
#   3. fetch_jds_and_rescore.py     — fetch full JDs + rescore
#   4. fetch_board_jobs.py          — Levels, YC, Getro, HN, hiring.cafe
#   5. merge_results.py             — unified all-jobs.csv
#
# Output: output/all-jobs.csv (open in Excel / Numbers / Google Sheets)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate venv
if [[ -f ".venv/bin/activate" ]]; then
    source .venv/bin/activate
else
    echo "ERROR: .venv not found. Run: python3 -m venv .venv && pip install -r requirements.txt"
    exit 1
fi

BOARDS_ONLY=false
for arg in "$@"; do
    [[ "$arg" == "--boards" ]] && BOARDS_ONLY=true
done

START=$(date +%s)
echo "=== Job Extractor Pipeline — $(date '+%Y-%m-%d %H:%M') ==="
echo

if [[ "$BOARDS_ONLY" == "false" ]]; then
    echo "── Stage 1/4: ATS scan + role match ──────────────────────"
    python3 main.py

    echo
    echo "── Stage 2/4: Export remote-matched companies ─────────────"
    python3 scripts/export_remote_roles.py

    echo
    echo "── Stage 3/4: Fetch full JDs + rescore ───────────────────"
    python3 scripts/fetch_jds_and_rescore.py
else
    echo "(--boards flag: skipping ATS stages 1-3)"
    echo
fi

echo
echo "── Stage 4/4: Board sources ───────────────────────────────"
python3 scripts/fetch_board_jobs.py

echo
echo "── Merge: unified all-jobs.csv ────────────────────────────"
python3 scripts/merge_results.py

END=$(date +%s)
ELAPSED=$(( END - START ))
MINS=$(( ELAPSED / 60 ))
SECS=$(( ELAPSED % 60 ))

echo
echo "=== Done in ${MINS}m ${SECS}s ==="
echo "    output/all-jobs.csv — open this for clickable links"
echo
