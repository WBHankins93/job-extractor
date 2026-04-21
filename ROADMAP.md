# Job Extractor Roadmap

This roadmap captures the next iterations for hardening the current pipeline before a larger scraping + UI phase.

## Phase 0 — Stability and quality gates (now)

1. **Add regression tests for matching heuristics**
   - Create focused tests for:
     - `matches_target_role(...)`
     - `within_experience_cap(...)`
   - Include positive/negative examples for:
     - Software / Full Stack / Solutions / Forward Deployed
     - Seniority exclusions
     - Years-of-experience parsing from title/JD

2. **Fix stale embedding sanity-check references**
   - Update the `pipeline/embed.py` module self-test to remove old TPM-only examples and use currently mapped resumes.

3. **Improve fetch error observability**
   - Keep resilient behavior, but log structured fetch failures (ATS, URL, status/exception) for post-run debugging.

## Phase 1 — Explainability and output trust

4. **Persist exclusion reasons**
   - Add reason fields in outputs (e.g., `excluded_reason`):
     - unknown ATS
     - no jobs
     - non-remote
     - role mismatch
     - experience cap exceeded

5. **Smarter deduplication**
   - Extend dedupe beyond `Company + URL` using canonicalized URL/slug strategy to reduce duplicate listings across sources.

6. **Centralized pipeline config**
   - Move tuning knobs to a single config file:
     - target roles + aliases
     - experience cap
     - freshness window
     - location policy

## Phase 2 — Scraping tool + UI foundation

7. **Homepage → careers URL discovery**
   - For companies without direct ATS links, add a lightweight discovery stage:
     - known careers path probes (`/careers`, `/jobs`, etc.)
     - homepage link extraction + scoring

8. **Source health dashboard**
   - Extend reporting to include:
     - source-level success/failure counts
     - ATS detection coverage
     - exclusion reason summary

9. **Prepare API contract for future UI**
   - Define a stable JSON schema for:
     - matched jobs
     - score metadata
     - exclusion reasons
     - source diagnostics

---

## Success criteria

- Reproducible filtering behavior across runs
- Clear diagnostics for “why no match”
- Lower duplicate rate in merged output
- Ready-to-serve data model for a future frontend
