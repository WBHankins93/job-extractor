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

The pipeline runs in two stages. Each one gets you closer to the signal and further from the noise.

```
📋 Forbes CSV (500 companies)
        │
        ▼  python main.py
┌───────────────────────────────────┐
│  1. 🔍 ATS Detect                 │  3-pass: URL → HTML → slug probe
│  2. 📥 Job Fetch                  │  Greenhouse · Lever · Ashby · SmartRecruiters · Workable
│  3. 🎯 Role Match                 │  Remote only · 5 target roles
│  4. 🤖 Resume Score               │  Cosine similarity (BAAI/bge-small-en-v1.5)
└────────┬──────────────────────────┘
         │
         ▼
  📄 output/results.csv  (500 rows, all companies)
         │
         ▼  python scripts/export_remote_roles.py
  📄 output/remote-roles.csv  (remote=True companies only)
         │
         ▼  python scripts/fetch_jds_and_rescore.py
┌───────────────────────────────────┐
│  5. 🔄 Re-detect ATS              │  Recover api_url for remote companies
│  6. 📖 Fetch Full JD              │  Per-job API calls where needed
│  7. ⚡ Rescore                    │  Full JD text vs resume (not just title)
└────────┬──────────────────────────┘
         │
         ▼
  🏆 output/rescored-jobs.csv  (one row per job, sorted by fit_score_jd)
```

> **Last run:** 495/500 companies detected · 155 remote · 182 role-matched jobs · top score: **0.885**

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

### `python main.py` — Run the full pipeline

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

### `python scripts/export_remote_roles.py` — Filter remote companies

Reads `output/results.csv` and saves every company with remote positions to a clean, focused file.

```
Saved 155 remote companies → output/remote-roles.csv
  67 with role match (✓), 88 without
```

---

### `python scripts/fetch_jds_and_rescore.py` — Deep rescore with full JDs

The real magic. Fetches the complete job description for every remote listing and re-scores fit using the full JD text — not just the title. Surfaces hidden matches that keyword filtering misses.

- **Greenhouse / Lever** — JD content is free in the batch API response (zero extra calls)
- **Ashby / SmartRecruiters / Workable** — one targeted API call per job
- Scores **all** remote companies, including those without an exact title match

```
Total remote jobs: 1566
  737/1566 had full JD fetched
  182/1566 matched a target role keyword

Top 5 by fit_score_jd:
  Solo.io       Senior Customer Success Engineer   0.885 ✨
  Solo.io       Open Source Evangelist             0.884
  Drata         Senior Solutions Engineer          0.882
  Solo.io       RevOps Engineer                    0.882
  Mighty Networks  Sr. Software Engineer, DevOps   0.872
```

---

### `python scripts/report_found_unfound.py` — Print summary stats

Quick snapshot of the last run — no network calls, instant output.

```
=== Found vs Unfound (from output/results.csv) ===
Total companies: 500
Found (role match): 67
Unfound: 433
  unknown ATS: 5 · known ATS no jobs: 366 · no remote: 36 · remote but no role: 26
```

---

## 📁 Output Files

| File | Rows | What's inside |
|------|------|----------------|
| `output/results.csv` | 500 | Every company — ATS, remote flag, role match, fit score |
| `output/remote-roles.csv` | ~155 | Remote-only filtered view |
| `output/rescored-jobs.csv` | ~1,500+ | One row per job, sorted by `fit_score_jd` |

> ⚠️ Output files are **gitignored** — they're generated data, not source code. Run the pipeline locally to populate them.

**Key columns:**

| Column | Description |
|--------|-------------|
| `match` | `✓` if the company has a remote opening matching a target role |
| `fit_score` | Cosine similarity (0–1) between job title and your resume |
| `fit_score_jd` | Cosine similarity using the **full job description** text |
| `jd_found` | Whether a full JD was successfully fetched |
| `resume_used` | Which of your PDFs scored highest for that role |

---

## 🎯 Target Roles

The pipeline matches jobs against these title substrings (case-insensitive):

| Role | Resume Used |
|------|-------------|
| 🖥️ Software Engineer | `Full_Stack.pdf` |
| 🔧 Full Stack Engineer | `Full_Stack.pdf` |
| 🤝 Solutions Engineer | `Solutions_feb26.pdf` |
| 🚀 Forward Deployed Engineer | `Solutions_feb26.pdf` |
| 📋 Technical Product Manager | `TPM.pdf` |

> Edit `TARGET_ROLES` in `pipeline/ingest.py` and `ROLE_TO_RESUME` in `pipeline/embed.py` to customize for your background.

---

## 🏗️ Project Structure

```
job-extractor/
├── 🎬 main.py                        # Pipeline orchestrator
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
│   └── report_found_unfound.py       # Summary stats from last run
│
├── data/
│   ├── Forbes_Best_Startup_Employers_2026_FINAL.csv
│   └── chroma/                       # Vector store (auto-created, gitignored)
│
├── resume/                           # 🔒 Drop your PDFs here (gitignored)
└── output/                           # 📊 Generated on each run (gitignored)
    ├── results.csv
    ├── remote-roles.csv
    └── rescored-jobs.csv
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
- **Score interpretation:** `0.85+` = strong match · `0.80–0.85` = worth a look · `< 0.75` = likely off-target

---

<div align="center">

Built to stop the job search grind. 🤙

</div>
