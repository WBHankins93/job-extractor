#!/usr/bin/env bash
# setup_cron.sh — install automated cron jobs for the job extractor pipeline
#
# Run once: ./setup_cron.sh
# Safe to re-run — won't add duplicate entries.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$HOME/job-extractor-cron.log"

# ── What is cron? ─────────────────────────────────────────────────────────────
#
#  Cron is a macOS/Linux daemon that runs commands on a schedule.
#  Your personal schedule lives in a "crontab" (cron table).
#
#  Each line follows this format:
#
#    MIN  HOUR  DOM  MON  DOW   COMMAND
#     0    11    *    *   2,5   cd /path && ./script.sh >> ~/log 2>&1
#
#  Field meanings:
#    MIN  — minute (0–59)
#    HOUR — hour in 24h (0–23)
#    DOM  — day of month (1–31),  * = every day
#    MON  — month (1–12),         * = every month
#    DOW  — day of week:  0=Sun 1=Mon 2=Tue 3=Wed 4=Thu 5=Fri 6=Sat
#
#  Common commands:
#    crontab -l   → list your current jobs
#    crontab -e   → open in editor (vi/nano) to edit manually
#    crontab -r   → REMOVE ALL jobs — careful!
#
#  The >> ~/log 2>&1 redirects both stdout and stderr to a log file
#  (appending, not overwriting). Without this, cron output goes nowhere.
#
# ──────────────────────────────────────────────────────────────────────────────

echo "=== Job Extractor — Cron Setup ==="
echo

# ── Define the entries ────────────────────────────────────────────────────────

ENTRY_FULL="# Job Extractor — full pipeline (ATS + boards): Tue & Fri 11am
0 11 * * 2,5 cd ${SCRIPT_DIR} && ./run_pipeline.sh >> ${LOG} 2>&1"

ENTRY_BOARDS="# Job Extractor — boards only (Levels, YC, HN etc.): Mon, Wed, Thu 11am
0 11 * * 1,3,4 cd ${SCRIPT_DIR} && ./run_pipeline.sh --boards >> ${LOG} 2>&1"

ENTRIES="${ENTRY_FULL}

${ENTRY_BOARDS}"

# ── Show what will be installed ───────────────────────────────────────────────

echo "The following cron jobs will be installed:"
echo
echo "┌─────────────────────────────────────────────────────────────────────"
while IFS= read -r line; do
    echo "│ $line"
done <<< "$ENTRIES"
echo "└─────────────────────────────────────────────────────────────────────"
echo
echo "Schedule:"
echo "  Tue + Fri    11:00am → full pipeline  (ATS scan + boards, ~15 min)"
echo "  Mon/Wed/Thu  11:00am → boards only    (Levels, YC, HN etc., ~2 min)"
echo
echo "Log: $LOG"
echo "  Live tail: tail -f $LOG"
echo

# ── Check for existing entries ────────────────────────────────────────────────

EXISTING=$(crontab -l 2>/dev/null | grep "job-extractor" || true)
if [[ -n "$EXISTING" ]]; then
    echo "⚠️  Existing job-extractor entries found — replacing them:"
    echo "$EXISTING"
    echo
fi

# ── Install ───────────────────────────────────────────────────────────────────
#
#  Pull current crontab (ignore error if empty), strip any job-extractor lines,
#  append the new entries, pipe result back into crontab.
#  This preserves any other cron jobs you have.
#
CURRENT=$(crontab -l 2>/dev/null || true)
FILTERED=$(printf '%s\n' "$CURRENT" | grep -v "job-extractor" | grep -v "^$" || true)

printf '%s\n\n%s\n' "$FILTERED" "$ENTRIES" | crontab -

echo "✓ Installed. Verifying..."
echo

# ── Verify ────────────────────────────────────────────────────────────────────

echo "Your crontab now contains:"
echo
crontab -l
echo

# ── macOS note ────────────────────────────────────────────────────────────────

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "macOS note: cron needs Full Disk Access to read your home directory."
echo "If jobs run silently with no output in the log:"
echo "  System Settings → Privacy & Security → Full Disk Access → add /usr/sbin/cron"
echo
echo "cron only fires if the machine is awake at 11am. If the lid is closed"
echo "at that time, the job is skipped — not deferred."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo
echo "To manually test in the same bare environment cron uses (boards-only, fast):"
echo "  env -i HOME=\$HOME PATH=/usr/bin:/bin /bin/bash -c \\"
echo "    \"cd ${SCRIPT_DIR} && ./run_pipeline.sh --boards >> ${LOG} 2>&1\""
echo
echo "Done."
