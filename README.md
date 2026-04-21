<div align="center">

# 🎯 Job Extractor

### Stop scrolling job boards. Let the pipeline find you.

**An automated, AI-powered job-matching engine** that scans 500 Forbes Best Startup Employers,
fingerprints their hiring stack, pulls live listings, and ranks every role against your resume —
using semantic embeddings, not keyword luck.

![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white)
![httpx](https://img.shields.io/badge/httpx-async-009688?style=flat-square)
![ChromaDB](https://img.shields.io/badge/ChromaDB-vector_store-FF6B35?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-22c55e?style=flat-square)

</div>

---

## 🧠 How It Works

Two source tracks run in parallel and merge into one ranked output.

```
📋 Forbes CSV (500 companies)                  🌐 Job Boards
        │                                      (Levels.fyi · YC · Getro · HN · hiring.cafe)
        ▼  main.py                                      │
┌───────────────────────────────────┐                   ▼  fetch_board_jobs.py
│  1. 🔍 ATS Detect                 │         ┌─────────────────────────┐
│  2. 📥 Job Fetch                  │         │  Fetch remote listings  │
│  3. 🎯 Role Match + Score         │         │  Role match + score     │
└────────┬──────────────────────────┘         └──────────┬──────────────┘
         │                                               │
         ▼  export_remote_roles.py                       │
  remote-roles.csv                                       │
         │                                               │
         ▼  fetch_jds_and_rescore.py                     │
  rescored-jobs.csv  ←──────────────────────────────────┘
  (full JD scoring)           board-jobs.csv · founding-jobs.csv
         │                               │
         └───────────┬───────────────────┘
                     ▼  merge_results.py
             🏆 output/all-jobs.csv
             (unified · deduped · sorted by score)
```

> **Last run:** 495/500 companies detected · 273 role-matched jobs · top score: **88.2**

---

## ⚡ Quickstart

**Requirements:** Python 3.12+

```bash
# 1. Clone and set up your environment
git clone https://github.com/WBHankins93/job-extractor.git
cd job-extractor
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# → Add your HF_TOKEN (free at huggingface.co/settings/tokens)

# 3. Drop your resumes into resume/
#    Then update ROLE_TO_RESUME in pipeline/embed.py to point to your files
```

---

## 🚀 Commands

### One-command pipeline (recommended)

```bash
./run_pipeline.sh           # Full run: ATS scan + boards + merge (~15 min)
./run_pipeline.sh --boards  # Boards only: skip ATS stages (~2 min)
```

`run_pipeline.sh` runs all stages in order and ends with a merged `output/all-jobs.csv`.

---

### Manual stage-by-stage

```bash
python main.py                              # ATS detect + fetch + role match + score
python scripts/export_remote_roles.py       # Filter remote=True → remote-roles.csv
python scripts/fetch_jds_and_rescore.py     # Fetch full JDs + rescore → rescored-jobs.csv
python scripts/fetch_board_jobs.py          # Levels, YC, Getro, HN, hiring.cafe → board-jobs.csv
python scripts/merge_results.py             # Merge all outputs → all-jobs.csv
```

---

### `python main.py` — ATS scan

Detects ATS, fetches live jobs, matches roles, scores against your resume. Downloads the embedding model on first run (~33MB, cached after). Takes 3–5 minutes for 500 companies.

```
=== Job Extractor Pipeline ===

Loaded 500 companies from data/Forbes_Best_Startup_Employers_2026_FINAL.csv
Detecting ATS platforms...
  {'smartrecruiters': 210, 'greenhouse': 161, 'ashby': 70, 'lever': 46, 'workable': 8, 'unknown': 5}
Fetching jobs for 495 companies with known ATS...
Matching roles and scoring resume fit...
  67 companies matched (remote + target role)

Saved → output/results.csv
```

---

### `python scripts/fetch_jds_and_rescore.py` — Deep rescore with full JDs

Fetches the complete job description for every remote listing and re-scores fit using the full JD text — not just the title. Surfaces hidden matches that keyword filtering misses.

- **Greenhouse / Lever** — JD content is free in the batch API response (zero extra calls)
- **Ashby / SmartRecruiters / Workable** — one targeted API call per job

---

### `python scripts/fetch_board_jobs.py` — Board sources

Pulls jobs from external boards and scores them with the same embedding pipeline.

| Source | What it covers |
|--------|---------------|
| Levels.fyi | Comp-transparent roles at known tech companies |
| YC Work at a Startup | YC-backed companies actively hiring |
| Getro | VC portfolio job networks |
| HN Who's Hiring | Monthly Hacker News hiring thread |
| hiring.cafe | Curated remote-friendly listings |

---

### `python scripts/merge_results.py` — Unified output

Merges all three source CSVs, deduplicates by company + URL, sorts by score, and writes `output/all-jobs.csv` — the only file you need to open.

```
  rescored-jobs:   273 rows
  board-jobs:      142 rows

  415 total → 12 duplicates removed → 403 unique jobs

Top 10 by score:
        Company                                 Title                      Role  Score
        ClickUp  Senior Solutions Engineer, Enterprise      Solutions Engineer   88.2
          Drata  Senior Solutions Engineer, Enterprise      Solutions Engineer   88.2
```

---

## 📁 Output Files

| File | What's inside |
|------|----------------|
| `output/all-jobs.csv` | **Primary output** — unified, deduped, sorted by score |
| `output/rescored-jobs.csv` | ATS-sourced jobs scored against full JD text |
| `output/board-jobs.csv` | Board-sourced jobs (Levels, YC, Getro, HN, hiring.cafe) |
| `output/founding-jobs.csv` | Founding engineer roles from board sources |
| `output/results.csv` | All 500 companies — ATS detection, remote flag, role match |
| `output/remote-roles.csv` | Remote-only filtered view (input to rescore stage) |

> ⚠️ Output files are **gitignored** — run the pipeline locally to populate them.

**Columns in `all-jobs.csv`:**

| Column | Description |
|--------|-------------|
| `Company` | Employer name |
| `Title` | Job title |
| `URL` | Direct link to the job posting |
| `Role` | Role bucket (Software Engineer, Solutions Engineer, etc.) |
| `Level` | senior · staff · mid · junior |
| `Score` | Fit score as a percentage (`88.2` = strong match) |
| `Source` | ATS name or board (ashby · greenhouse · levels · yc…) |
| `Location` | Location string — populated from board sources |
| `Posted` | Post date — populated from board sources |
| `Salary Min/Max` | Salary range — populated from board sources |

---

## ⏰ Automation

Install cron jobs to run the pipeline automatically — no manual triggering needed.

```bash
./setup_cron.sh
```

**Schedule installed:**

| Days | Time | What runs |
|------|------|-----------|
| Tue + Fri | 11am | Full pipeline — ATS scan + boards (~15 min) |
| Mon + Wed + Thu | 11am | Boards only — fast refresh (~2 min) |

Log tails to `~/job-extractor-cron.log`. Live watch: `tail -f ~/job-extractor-cron.log`

> **macOS note:** cron needs Full Disk Access to read your home directory.
> System Settings → Privacy & Security → Full Disk Access → add `/usr/sbin/cron`

---

## 🎯 Target Roles

The pipeline matches jobs against these title substrings (case-insensitive):

| Role | Resume Used |
|------|-------------|
| 🖥️ Software Engineer | `Ben_Hankins_Full_Stack.pdf` |
| 🔧 Full Stack Engineer | `Ben_Hankins_Full_Stack.pdf` |
| 🤝 Solutions Engineer | `Ben_Hankins_Solutions_feb26.pdf` |
| 🚀 Forward Deployed Engineer | `Ben_Hankins_Solutions_feb26.pdf` |

> Edit `TARGET_ROLES` in `pipeline/ingest.py` and `ROLE_TO_RESUME` in `pipeline/embed.py` to customize for your background.

---

## 🏗️ Project Structure

```
job-extractor/
├── 🎬 main.py                        # Pipeline orchestrator
├── 🚀 run_pipeline.sh                # One-command runner (all stages)
├── ⏰ setup_cron.sh                  # Install automated cron schedule
├── 📦 requirements.txt
│
├── pipeline/
│   ├── ingest.py                     # Load & validate the Forbes CSV
│   ├── ats.py                        # ATS detection + job fetching (5 platforms)
│   └── embed.py                      # Resume embeddings + fit scoring (ChromaDB)
│
├── scripts/
│   ├── export_remote_roles.py        # Filter remote companies → CSV
│   ├── fetch_jds_and_rescore.py      # Full JD fetch + deep rescore
│   ├── fetch_board_jobs.py           # Levels · YC · Getro · HN · hiring.cafe
│   ├── merge_results.py              # Unify all outputs → all-jobs.csv
│   └── report_found_unfound.py       # Summary stats from last run
│
├── data/
│   ├── Forbes_Best_Startup_Employers_2026_FINAL.csv
│   └── chroma/                       # Vector store (auto-created, gitignored)
│
├── resume/                           # 🔒 Drop your PDFs here (gitignored)
└── output/                           # 📊 Generated on each run (gitignored)
    ├── all-jobs.csv                  # ← Open this one
    ├── rescored-jobs.csv
    ├── board-jobs.csv
    ├── founding-jobs.csv
    ├── results.csv
    └── remote-roles.csv
```

---

## 🔬 How ATS Detection Works

Most companies hide their job listings behind React/SPA frontends — the actual data lives in an ATS API. Detection runs in **three passes** per company:

| Pass | Method | What it does |
|------|--------|--------------|
| 1️⃣ | **URL fast-path** | Career URL directly points to a known ATS domain (e.g. `greenhouse.io`) |
| 2️⃣ | **HTML fingerprinting** | Fetch the career page, scan for ATS signatures in the markup |
| 3️⃣ | **Slug guessing** | Derive company slug from domain (`anthropic.com → anthropic`), probe each ATS API directly — cuts through JavaScript-rendered pages |

**Supported platforms:** Greenhouse · Lever · Ashby · SmartRecruiters · Workable

> The 3-pass approach knocked unknown ATS detections from **349 → 5** across 500 companies.

---

## 🤖 How Fit Scoring Works

The fit score is **cosine similarity** (0–1) between your resume and a job posting, computed locally — no API calls, no data leaving your machine.

```
Your Resume PDF  →  text  →  384-dim vector  ┐
                                              ├─ cosine similarity → fit_score
Job Description  →  text  →  384-dim vector  ┘
```

- **Model:** [`BAAI/bge-small-en-v1.5`](https://huggingface.co/BAAI/bge-small-en-v1.5) — 33MB, runs on CPU
- **Stage 1 scoring** (`main.py`): uses job title + location
- **Stage 2 scoring** (`fetch_jds_and_rescore.py`): uses full job description text
- **Score in `all-jobs.csv`:** displayed as a percentage (`88.2` = 0.882 cosine similarity)
- **Interpretation:** `85+` = strong match · `75–85` = worth a look · `< 75` = likely off-target

---

<div align="center">

Built to stop the job search grind. 🤙

</div>
