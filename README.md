# Job Extractor

Automated job-matching pipeline that scans 500 Forbes Best Startup Employers, detects their ATS platform, fetches live job listings, and ranks them by resume fit using semantic embeddings.

---

## How It Works

```
Forbes CSV (500 companies)
        │
        ▼  python main.py
┌───────────────────┐
│  1. ATS Detect    │  3-pass: URL → HTML → slug probe
│  2. Job Fetch     │  Greenhouse · Lever · Ashby · SmartRecruiters · Workable
│  3. Role Match    │  Remote only · 5 target roles
│  4. Resume Score  │  Cosine similarity (BAAI/bge-small-en-v1.5)
└────────┬──────────┘
         │
         ▼
  output/results.csv (500 rows, all companies)
         │
         ▼  python scripts/export_remote_roles.py
  output/remote-roles.csv (93 companies, remote=True)
         │
         ▼  python scripts/fetch_jds_and_rescore.py
┌───────────────────┐
│  5. Re-detect ATS │  Recover api_url for all 93
│  6. Fetch Full JD │  Per-job API calls where needed
│  7. Rescore       │  Full JD text vs resume (fallback: title+location)
└────────┬──────────┘
         │
         ▼
  output/rescored-jobs.csv (one row per job, sorted by fit_score_jd)
```

**Last run:** 495/500 companies detected · 93 remote · 67 role matches

---

## Setup

**Requirements:** Python 3.12+

```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate       # Mac/Linux
.venv\Scripts\activate          # Windows

# Install dependencies
pip install -r requirements.txt
```

**Resumes** — drop your PDFs into `resume/`:
```
resume/
├── Ben_Hankins_Full_Stack.pdf
├── Ben_Hankins_Solutions_feb26.pdf
└── Ben_Hankins_TPM.pdf
```

The resume-to-role mapping lives in `pipeline/embed.py` under `ROLE_TO_RESUME`.

**Environment** (optional):
```bash
cp .env.example .env
# Add HF_TOKEN if model downloads fail
```

---

## Commands

### Run the full pipeline
```bash
python main.py
```

Downloads the embedding model on first run (~33MB, cached after). Takes 3–5 minutes for 500 companies.

**Output:**
```
=== Job Extractor Pipeline ===

Loaded 500 companies from data/Forbes_Best_Startup_Employers_2026_FINAL.csv
Detecting ATS platforms...
  {'greenhouse': 161, 'smartrecruiters': 210, 'ashby': 70, 'lever': 46, 'workable': 8, 'unknown': 5}
Fetching jobs for 495 companies with known ATS...
Matching roles and scoring resume fit...
  67 companies matched (remote + target role)

Saved → output/results.csv

Top matches by fit score:
   name        role_type                  resume_used  fit_score
   Drata       Solutions Engineer         Ben_Hankins_Solutions_feb26.pdf  0.882
   ClickUp     Solutions Engineer         ...
   ...
```

---

### Export remote-only companies
```bash
python scripts/export_remote_roles.py
```

Reads `output/results.csv` and saves all companies with remote positions to a focused file.

**Output:** `output/remote-roles.csv` (93 companies on last run)

---

### Fetch full JDs and rescore
```bash
python scripts/fetch_jds_and_rescore.py
```

Fetches the full job description for every remote position across all 93 remote companies and re-scores fit using the complete JD text. Run after `export_remote_roles.py`.

- **Greenhouse / Lever**: JD content comes free from the batch API call (no extra requests)
- **Ashby / SmartRecruiters / Workable**: makes one additional API call per job
- All 93 companies are scored — including the 26 that had no target-role title match

**Output:** `output/rescored-jobs.csv` — one row per remote job, sorted by `fit_score_jd`

---

### Print summary stats
```bash
python scripts/report_found_unfound.py
```

Re-prints the found/unfound breakdown from the last pipeline run without re-fetching anything.

**Output:**
```
=== Found vs Unfound (from output/results.csv) ===
Total companies: 500
Found (role match): 67
Unfound: 433
  unknown ATS: 5, known ATS no jobs: 366, no remote: 36, remote but no role: 26
```

---

## Output Files

| File | Description |
|------|-------------|
| `output/results.csv` | All 500 companies enriched with ATS, remote status, role match, fit score. Sorted by fit score. |
| `output/rescored-jobs.csv` | One row per remote job, rescored using full JD text. Sorted by `fit_score_jd`. |
| `output/remote-roles.csv` | Filtered view — only companies offering remote positions. |

**Columns:** `rank, name, industry, location, career_url, ats, remote, role_type, resume_used, fit_score, match`

- `match` — `✓` if the company has a remote opening matching a target role
- `fit_score` — cosine similarity (0–1) between the job title and your resume
- `resume_used` — which of your PDFs scored highest for that role

---

## Target Roles

The pipeline matches jobs against these title substrings (case-insensitive):

- Software Engineer
- Full Stack Engineer
- Solutions Engineer
- Forward Deployed Engineer
- Technical Product Manager

Edit `TARGET_ROLES` in `main.py` to change what gets matched.

---

## Project Structure

```
job-extractor/
├── main.py                   # Pipeline orchestrator
├── requirements.txt
│
├── pipeline/
│   ├── ingest.py             # Load & validate the Forbes CSV
│   ├── ats.py                # ATS detection + job fetching (5 platforms)
│   └── embed.py              # Resume embeddings + fit scoring (ChromaDB)
│
├── scripts/
│   ├── export_remote_roles.py    # Save remote-only companies to CSV
│   └── report_found_unfound.py   # Print summary stats
│
├── data/
│   ├── Forbes_Best_Startup_Employers_2026_FINAL.csv
│   └── chroma/               # Vector store (auto-created)
│
├── resume/                   # Drop your PDF resumes here
└── output/                   # Generated on each run
    ├── results.csv
    └── remote-roles.csv
```

---

## ATS Detection

Detection runs in three passes per company:

1. **URL fast-path** — career URL itself points to a known ATS domain (e.g. `greenhouse.io`)
2. **HTML fingerprinting** — fetch the career page and scan for ATS signatures in the HTML
3. **Slug guessing** — derive a company slug from the domain (e.g. `anthropic.com → anthropic`) and probe each ATS's public API directly — bypasses React/SPA pages that load jobs via JavaScript

**Supported platforms:** Greenhouse · Lever · Ashby · SmartRecruiters · Workable

---

## Fit Score

The fit score is **cosine similarity** (0–1) between:
- The job title (e.g. `"Solutions Engineer Remote"`)
- Your resume text

Computed locally using [`BAAI/bge-small-en-v1.5`](https://huggingface.co/BAAI/bge-small-en-v1.5) (384-dim vectors, no GPU needed). Higher score = stronger semantic alignment between the role and your background. Scores above ~0.85 are strong matches.
