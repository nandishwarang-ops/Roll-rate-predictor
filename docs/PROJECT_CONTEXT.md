# PS-03 Roll-Rate Forecaster: project context and change log

Written 2026-11-20 after section 27 of 31. Purpose: keep the full context of what was built, why, what the numbers are, and what is still open, so the work can be resumed in a new session without the chat history.

Repo: github.com/nandishwarang-ops/Roll-rate-predictor (public). Local folder: `/Users/nandishwaran/Documents/Roll_rate_hackthon`.

---

## 1. The problem and the design in one page

**Problem (PS-03).** Each month CN presents lenders with bucket-flow (roll-rate) forecasts and an explanation of what moved. Analysts do this by hand, forecasts extrapolate last month, and festival months, policy changes or a lender's own process change catch them out. Goal: reliable roll-rate forecasts by bucket, product and region with a defensible, evidence-cited explanation of drivers, ready for the lender review pack, in under 30 minutes. Acceptance bar (from the brief): MAPE at least 30% lower than seasonal-naive on the hidden period and the seeded driver correctly named. Guardrails: every driver claim cites the query and number behind it; every forecast carries a range.

**Design decisions made with the user (v4 of the FSD):**
- Forecasting is plain deterministic statistics. An AI agent loop runs only when something looks wrong.
- The LLM never invents numbers. Numbers come from tools; the LLM chooses hypotheses and shapes.
- Rolling 1-month forecast plus a 3-month outlook (a 3-month NPA outlook is a real need because a loan takes 3-4 missed payments to reach 90+).
- Any fresh change gets two forecasts, one assuming a blip and one assuming a lasting shift, with weights. The next month's actuals decide (driver registry re-checks).
- Investigate hierarchically (lender, product, region, segment) so one lender-wide cause is investigated once.
- Forecast the full transition matrix (every bucket-to-bucket move), not three summaries.
- Attribution percentages come from a deterministic calculator (control-adjusted contribution, mix vs rate, ranges, unexplained remainder).
- Unexplained movements become questions to lender operations, non-blocking.

**Three agents:** Agent 1 Root-Cause Detective, Agent 2 Regime Classifier, Agent 3 Review Pack Author (plus a numeric auditor). Everything else is code.

**Monthly pipeline per lender (LangGraph, 11 steps):** checks, prepare, detect, investigate (parallel workers), registry and classify, escalate, forecast, ranges, roll-up, charts, pack.

---

## 2. Status of the 31 build sections

| # | Section | Status |
|---|---|---|
| 1 | Dataset creation | done (generated in the Cowork project, files copied here) |
| 2 | Load into DuckDB | done |
| 3 | Schema discovery and profiling | done |
| 4 | Sanity checks and data-quality report | done |
| 5 | Lender lock and time-cutoff controls | done (was skipped at first; see section 6 of this file) |
| 6 | Full transition matrix builder | done |
| 7 | Seasonal-naive benchmark | done |
| 8 | Baseline forecasting models | done |
| 9 | Model bake-off and selection | done, **below the 30% bar** (25.8%) |
| 10 | Hierarchical change detection | done, thresholds untuned |
| 11 | Leading-indicator and forward-calendar scan | done |
| 12 | Drift profiler | done |
| 13 | Read-only SQL tool | done |
| 14 | Attribution engine | done |
| 15 | Agent 1: Root-Cause Detective | built, offline-tested, **never run against real Claude** |
| 16 | Escalation questions and non-blocking notification | done (default channel is a local outbox) |
| 17 | Driver registry | done |
| 18 | Agent 2: Regime Classifier | built; deterministic prior tested; **LLM path never run live** |
| 19 | Forecasting tool with interventions | done, small noise-limited gain |
| 20 | Multi-month chaining | done |
| 21 | Range calibration and simulation ranges | done, coverage 78-89% vs 80% target |
| 22 | Portfolio roll-up | done |
| 23 | Chart generation | done (validator not run) |
| 24 | Agent 3: Pack Author and numeric auditor | done; template author fully tested; **LLM author never run live** |
| 25 | Document generator (PDF + Markdown) | done |
| 26 | Orchestrator | done; runs offline with a rule-based investigator |
| 27 | Audit trace and logging | done (committed locally; see section 9) |
| 28 | Backtest harness with planted shifts | done; **results are weak** (see section 4b) |
| 29 | Threshold tuning and accuracy evaluation | **not started** |
| 30 | Review portal (run, review, approve, deliver) | **not started** |
| 31 | End-to-end run, timing check, demo prep | **not started** |

`docs/BUILD_PROGRESS.md` has the same table with file names (it was updated through section 26).

---

## 3. Data

Three synthetic lenders: Lender A = Sahyadri Finserv (diversified NBFC, about 100k loans), Lender B = Kaveri Auto and Personal Finance (two-wheeler heavy), Lender C = Nimbus Digital Lending (personal-loan heavy). Real cities and pin codes, EMI due days, NACH bounce reasons, agencies with agent IDs, calls, SMS, WhatsApp, field visits, promises to pay and payments.

- Public period: Oct 2023 to Sep 2025 (24 months). Hidden period: Oct to Dec 2025 (3 months, with seeded shifts).
- Loaded tables (main schema): `d1_account_monthly` 6,039,086 rows, `d3_collection_events` 10,293,016, `bucket_flow_history` 16,050, `event_calendar` 32, plus `dim_agency`, `dim_bucket`, `dim_geography`, `dim_lender`, `dim_product`.
- Hidden tables are in a separate `hidden` schema in `rollrate.duckdb` and are **not reachable** by the agent sandbox.
- The answer key `answer_key/seeded_events_answer_key.csv` (13 seeded events SE01-SE13) is **never loaded** into the system. I used it only to eyeball whether detectors fired, never as an input.
- Seeded events in the public period: Diwali (transient), regional festivals, fiscal year-end, recovery-agent conduct norms (small step, Apr 2024), Lender A payment-link outage (Jun 2024, silent), coastal flooding (Jul 2024), Surat cash crunch (Aug-Nov 2024, silent, fading), Lender C personal-loan approval loosening (lagged cohort effect, Nov 2024 onward), Lender B UPI Autopay launch (Jan 2025, improvement), West tele agency AG_W_TELE_02 attrition (Mar 2025, silent, step), plus decoy events with no effect. Hidden: Lender B field visits stopped for EMIs under 10k (Nov 2025, step), Lender C bank auto-debit failure (Dec 2025, blip).
- Data-quality report: 16 PASS, 2 WARN, 0 FAIL. Warnings: 16 of 180 segment-buckets have months below 30 opening accounts (mostly 61-90 and 31-60 for Lender B/C business loans and Lender C two-wheelers in the East), and 127 payments marked SUCCESS have amount 0.

Not in git (too large, regenerable, or sensitive): `data/`, `rollrate.duckdb` (about 700 MB), `answer_key/`, `files/`, `files.zip`, `outputs/`, `.venv/`. `src/generate_dataset.py` regenerates the data. Keep `files.zip` somewhere safe (Drive).

---

## 4. Key results and honest caveats

**Forecast accuracy (section 9, rolling origin, 9 origins x 3 horizons, public data).**

| Model | Cell MAPE | vs seasonal-naive | Roll-forward MAPE |
|---|---|---|---|
| Seasonal-naive | 29.5% | baseline | 14.5% |
| Naive (last month) | 27.6% | 6% better | 13.3% |
| ETS | 23.2% | 21% better | 12.3% |
| SARIMAX (calendar inputs) | 23.7% | 20% better | 12.8% |
| Pooled gradient boosting | 22.2% | 25% better | 13.3% |
| **Ensemble (selected)** | **21.9%** | **25.8% better** | **12.1%** |

The brief asks for 30%. The ensemble is about 4 points short. Part of the gap is seeded shifts that no statistical model can predict (the agent loop is meant to close that on the hidden period). Ideas not yet tried: tune ETS/GBM, weight the ensemble by recent accuracy, drop noisy small cells from scoring, add lag-12 features. A single-origin check had shown about 31%, which was a lucky draw. The public-data baseline numbers will look easier than the hidden period.

**Change detection (section 10).** Compares actual roll-forward and cure rates with the one-step ensemble forecast at four levels. z-score (binomial noise plus estimated model error), Benjamini-Hochberg q=0.05, materiality (1.0 pp segment, 0.5 pp parents, 20 accounts, 60 opening accounts), CUSUM for slow drift, then grouping into investigations; top 8 per month with at least 25 excess accounts are "priority". It fired on Diwali (Nov 2024), the Lender B Autopay launch (Jan 2025) and the Lender C personal-loan cohort (Mar 2025), and was quiet in Sep 2025. Thresholds are untuned.

**Leading indicators (section 11).** 14 D1/D3 indicators vs their own trailing 6 months at four levels. Caught the Jun 2024 gateway timeouts (Lender A), the Apr 2024 off-hours calls going to zero, and the Lender C bureau/new-to-credit shift about a month before roll rates moved. Most indicators move in the same month as roll rates, not before; only cohort-quality ones lead (2-4 month lag). Forward-calendar scan shows prior-occurrence lift (Diwali about +1.3 to +1.4 pp CURRENT to 1-30).

**Drift profiler (section 12).** Found the Surat cash crunch (+3.2 pp vs control) and the AG_W_TELE_02 attrition (+10.8 pp, with a 3-month window and an older baseline); quiet on a control pool; **missed** the Lender B Autopay effect (too diffuse).

**Attribution (section 14).** Control-adjusted contribution plus exact mix/rate split plus unexplained remainder, with 80% ranges. When the rest of the pool moves the opposite way, shares can exceed 100% or be negative; the engine and the pack report this as an offset instead of forcing a percentage. When the pool-level change is within sampling noise it withholds the share (Surat at pool level).

**Interventions (section 19).** Counterfactual history with the measured effect removed, then scenario profiles added back (STEP, DOT, TRANSIENT, lagged). On the real West-agency case across 9 points the adjusted forecast had mean error 2.24 pp vs 2.45 pp unadjusted and bias -0.7 pp vs -1.9 pp; removing the driver made it clearly worse (3.74). The accuracy gain is small and inside sampling noise (each pool-month has about 600 accounts, about 2 pp of noise). Do not claim a clear win from this case.

**Chaining (section 20).** Chaining actual rates reproduces actual 90+ and CURRENT stock exactly. With forecast matrices, NPA stock error is 1.6% / 3.0% / 4.7% at months 1/2/3 vs 3.6% / 6.9% / 10.2% for holding the stock flat; NPA additions bias +1.5%.

**Ranges (section 21).** Lognormal error per (bucket, move class, horizon) from backtest residuals, lender-wide shared error (kappa), persistence phi, multinomial sampling, scenario mixtures. Leave-one-origin-out coverage of the 80% range: NPA stock 78/78/89%, NPA additions 89/89/81% at months 1/2/3. Calibration choices (phi=0.9, lambda 1.7/2.2/2.5) were tuned on the same backtest points, so this is a good-faith check, not fully independent. 27 points per horizon.

**Pack (sections 22-25).** One reconciled roll-up table (20 nodes x 15 metrics, mean/P10/P50/P90 from the same draws; additive metrics reconcile exactly; quantiles are not additive). Four charts. The pack text is written with fact tokens; an auditor rejects typed numbers, unknown tokens, direction words that contradict a fact's sign, missing or fabricated citations, a forecast section without its model run id, and any rendered number not matching a fact. The Lender A June 2025 pack is 4 pages.

**Orchestrator (section 26).** One lender-month in about 34 s; three lenders in parallel in about 126 s (vs about 374-430 s sequential). 30-minute target met by a wide margin.

### 4b. Planted-shift backtest (section 28), the first honest measurement

Harness: `src/planted.py` (plant a shift in a scratch copy of one lender's D1/D3, rebuild bucket flows and matrices), `src/planted_backtest.py` (runner), `src/planted_report.py`, report in `docs/planted_backtest.md`. 5 shift types x 2 sizes plus lifecycle runs, July 2025, one seed, rule-based investigator.

- Detected: 3 of 5 at full size, 2 of 5 at half size (missed: weak cohort 0.7 pp pool effect, city shock 1.0 pp, half-size policy step). Lender-wide shifts as small as 0.6 pp are detected (big pool).
- Naming the planted slice: **0 of 3** where a slice exists. On a single month of about 600 accounts the profiler flags nothing for the agency and policy shifts (a 10-point effect is about 2.3 sigma; the false-discovery correction across about 100 slices removes it). With the true pool the cohort and city slices reach the top 3 but not top 1.
- Size accuracy: off by 13-14 points where the wrong slice was quantified.
- Shape classification: 3 of 3 correct on a high-power pool; wrong on the noisy pool (persistent step closed as a blip).
- Unmodified Jun-Sep 2025: about 1.8 flagged and 0.3 priority investigations per lender-month (upper bound).
- Implication: the system detects large shifts and reports them honestly, but cannot yet name mid-sized causes from one month of data. Section 29 should extend the profiler to multi-month windows, investigate at the true parent pool, rethink slice screening, and tune detection thresholds. Do not claim cause-naming accuracy in a demo until this is improved.

---

## 5. Architecture and file map

```
src/
  generate_dataset.py   rebuild the synthetic data
  load_duckdb.py        S2   load parquet into DuckDB (public -> main, hidden -> hidden)
  profile_schema.py     S3   column catalogue (docs/column_catalogue.*)
  dq_checks.py          S4   18 sanity checks -> docs/data_quality_report.*
  guarded_sql.py        S5   lender+time locked in-memory sandbox, SELECT only, fork() for parallel workers
  transition_matrix.py  S6   mart.transition_cells, transitions_*, moves_* at 4 levels
  benchmark.py          S7   seasonal-naive and naive scores
  forecast_models.py    S8   ets, sarimax (calendar exog), pooled gbm (sklearn HistGradientBoosting), snaive, naive
  bakeoff.py            S9   rolling-origin bake-off -> docs/model_bakeoff.md, src/selected_model.json
  detection.py          S10  mart.detections, mart.investigations
  leading_scan.py       S11  mart.leading_indicators, mart.forward_scan
  drift_profiler.py     S12  feature drift and slice outcome shifts
  sql_tool.py           S13  run_sql tool: evidence ids Q###, budget, timeout, audit
  attribution.py        S14  attribute_change tool: ids A###
  detective.py          S15  Agent 1 tool-use loop, validation, pluggable client
  escalations.py        S16  question checks, outbox notifier, follow-ups
  driver_registry.py    S17  lifecycle: open, persistent, fading, closed_transient, closed_reverted
  classifier.py         S18  Agent 2: DOT/TRANSIENT/STEP prior + validated LLM path
  intervention_forecast.py  S19
  chaining.py           S20
  ranges.py, ranges_backtest.py, range_calibration.json   S21
  rollup.py             S22
  charts.py             S23
  pack_author.py        S24  Facts, template author, LLM author, auditor
  doc_generator.py      S25  pack.pdf, pack.md, charts, evidence.json, manifest.json
  orchestrator.py       S26  LangGraph pipeline, rule-based investigator fallback
  audit_trace.py        S27  hash-chained trace
  planted.py, planted_backtest.py, planted_report.py   S28  planted-shift harness
tests/   one test file per section (test_*.py) plus fixtures.py
docs/    DATA_DICTIONARY.md, schema.png, BUILD_PROGRESS.md, backtest and calibration reports, this file
```

Mutable state (not in git): `outputs/state.duckdb` holds escalations, drivers, driver_obs, driver_events. `outputs/` also holds charts, forecasts, packs, runs, trace, audit, outbox.

Derived tables live in the `mart` schema of `rollrate.duckdb`: `transition_cells`, `transitions_{segment,lender_product,lender_region,lender}`, `moves_*`, `bakeoff_forecasts`, `detect_forecasts`, `detections`, `investigations`, `leading_indicators`, `forward_scan`, `benchmark_scores`.

---

## 6. Process notes and deviations to remember

1. **Section numbering slip.** I skipped section 5 (lender lock and time cutoff) and numbered everything after it one too low for a while. Found and fixed when the user asked. Commit messages for the transition matrix and benchmark say "Section 5/6" but are really 6/7; docs and docstrings are corrected.
2. **LightGBM replaced.** `libomp` is not installed (no Homebrew), so the pooled model uses scikit-learn `HistGradientBoostingRegressor`. Same idea; switch back if `libomp` is installed.
3. **Python 3.9.6 venv** (system Python). Pins: `reportlab==4.2.5` (newer needs 3.10+), `langgraph<0.3` (0.2.76 installed), `tabulate`, `matplotlib`, `pypdf`, `pypdfium2`, `anthropic`.
4. **No Node.** The dataviz skill's palette validator could not run. Charts use the documented, pre-validated slot 1 blue and slot 2 orange pair plus neutral gray.
5. **No ANTHROPIC_API_KEY.** The Detective, Classifier LLM path and LLM pack author are tested only with a scripted fake client. The orchestrator therefore uses a **rule-based investigator** that finds and quantifies where a movement is concentrated but cannot name the mechanism, so it always asks operations a question. Its output is crude (for example it flagged "new-to-credit flag = false" when the complementary group was the real mover, and can produce duplicate findings). A live Detective is the biggest unverified piece.
6. **Bugs found by tests/inspection and fixed:** SQL-guard table filter crashing on a new mart table; slice-effect smoothing; `forecast_models` hist override; additions aggregate indexing in the simulation (numpy advanced-indexing reorder); evidence-id collisions across parallel investigations (now offset per investigation: Q101.., Q201.., A101.., registry 900+, forecast 950+); secrets in event summaries not redacted (now redacted); chart rounding mismatch with the pack text; pack wording for negative contributions.
7. **Git and token handling.** Pushes use a fine-grained personal access token supplied in chat, injected inline for a single `git push` and never written to config. The token was pasted in chat, so **revoke it** at github.com/settings/personal-access-tokens and create a new one for future pushes (needs Contents: read and write; Metadata read is automatic). Commits are authored as `nandishwarang-ops` with a GitHub noreply email so the user's real email is not published. Commit trailer: `Co-Authored-By: Claude Sonnet 5.5`.
8. **Escalation notifications** default to a local outbox folder. Nothing is sent externally unless an email/webhook notifier is configured explicitly.

---

## 7. Section 27 (audit trace), as built

`src/audit_trace.py`: one append-only JSONL per run, `outputs/trace/<run_id>.jsonl`, each event hash-chained (`hash = sha256(prev + canonical event)`), thread-safe. Logged: run_start (git commit, uncommitted-src flag, library versions, data fingerprint of row counts and month ranges), every SQL query (allowed or rejected, with result hash), attribution calls, LLM calls (model, token counts, prompt hash, tools; never the prompt text), step start/end with timings, investigation outcomes, registry changes, classifier decisions, escalations, forecast and simulation runs (ids, seed, calibration), pack audit result, hashes of delivered files, run_end. Secrets are redacted in payloads and summaries. Tools: `verify_chain` (names the first bad event), `explain_fact` (from a pack number back to its source events), `report` (human-readable audit report), `export_bundle` (zip for an auditor). 22 tests pass (tamper detection of edits, deletions and reordering; thread safety; secret redaction; unique evidence ids; every id cited in the pack resolves to exactly one event; output hashes match delivered files).

Hooks were added to `SQLTool` and `AttributionTool` (optional `trace`, `id_offset`) and to every orchestrator step. After the change the orchestrator tests (15), SQL tool, attribution, Detective, pack author and document generator tests all still pass.

**Status:** sections 1-27 and this document are on GitHub (commit `a47dc13`). Section 28 is committed locally after that.

---

## 8. Open items and recommended next steps

1. **Add an API key and run the live Detective, Classifier and pack author.** Expect prompt tuning. `export ANTHROPIC_API_KEY=...` then `.venv/bin/python src/detective.py`, or pass `client=AnthropicClient()` to `RunConfig`. Do not paste keys into chat.
2. **Section 28: backtest harness with planted shifts.** Inject synthetic shifts into copies of the data (agency contact collapse, policy step, cohort mix change, moved festival) and measure detection rate, false-flag rate, named-driver correctness and dollar-style accuracy. This is the only way to measure the acceptance criteria honestly.
3. **Section 29: tune thresholds** (detection z, CUSUM, materiality, priority cutoff, classifier prior weights, calibration) using section 28. Revisit the 25.8% vs 30% gap (ideas in section 4).
4. **Hidden-period run.** Never done. Needs a rolling or three-month evaluation protocol decided with the organisers. Questions to confirm with them: scoring mode (rolling one-step vs a 3-month forecast from month 24), scored cells (full matrix vs summaries; rates vs counts), whether D1/D3 for hidden months may be read for leading indicators, and the exact format used to name the seeded driver.
5. **Section 30 review portal** and **section 31 end-to-end timing and demo.** Add the data-quality PASS/WARN and calibration coverage to the demo narrative; be upfront about the three untested LLM paths and the unmet 30% bar.
6. **Known limits to disclose:** new loans are assumed at the recent 3-month average; principal per account is held at the origin level; ranges are tuned on 9 origins; the recovery check uses EMI due-day groups as a rough proxy for timing inside the month; leading-scan and forward-calendar tables are rebuilt for the run's cut-off date by `orchestrator.prepare`, which overwrites the earlier global versions.
7. **Housekeeping:** `files/` and `files.zip` duplicate `data/` (about 600 MB) and can be deleted after backing up `files.zip`; the `outputs/` folder is large and disposable.

---

## 9. How to run

```bash
cd /Users/nandishwaran/Documents/Roll_rate_hackthon
.venv/bin/python src/load_duckdb.py                 # S2: build rollrate.duckdb from data/ (needs the parquet files)
.venv/bin/python src/transition_matrix.py           # S6: mart tables
.venv/bin/python src/bakeoff.py                     # S9: model bake-off (about 3 minutes)
.venv/bin/python src/ranges_backtest.py             # S21: calibration
.venv/bin/python src/orchestrator.py 2025-06-01     # S26: one monthly run for all three lenders (packs in outputs/packs/)
.venv/bin/python -W ignore tests/test_audit_trace.py   # any test file; orchestrator tests take about 6 minutes
```

Outputs per run: `outputs/packs/<LENDER>_<YYYY-MM>/` (pack.pdf, pack.md, charts/, evidence.json, manifest.json), `outputs/runs/<run_id>.json`, `outputs/trace/<run_id>.jsonl` and `.report.md`.

To recreate the environment: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.
