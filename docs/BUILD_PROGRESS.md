# Build progress (31 sections, official numbering)

| # | Section | Status | Code |
|---|---|---|---|
| 1 | Dataset creation | done | src/generate_dataset.py |
| 2 | Load into DuckDB | done | src/load_duckdb.py |
| 3 | Schema discovery and profiling | done | src/profile_schema.py |
| 4 | Sanity checks and data-quality report | done | src/dq_checks.py |
| 5 | Lender lock and time-cutoff controls | done | src/guarded_sql.py, tests/test_guards.py |
| 6 | Full transition matrix builder | done | src/transition_matrix.py |
| 7 | Seasonal-naive benchmark | done | src/benchmark.py |
| 8 | Baseline forecasting models | done | src/forecast_models.py |
| 9 | Model bake-off and selection | done (ensemble, 25.8% better than snaive; below 30% bar) | src/bakeoff.py |
| 10 | Hierarchical change detection | done (thresholds to be tuned in 29) | src/detection.py |
| 11 | Leading-indicator and forward-calendar scan | done | src/leading_scan.py |
| 12 | Drift profiler | done | src/drift_profiler.py |
| 13 | Read-only SQL tool | done | src/sql_tool.py, tests/test_sql_tool.py |
| 14 | Attribution engine | done | src/attribution.py, tests/test_attribution.py |
| 15 | Agent 1: Root-Cause Detective | built, offline-tested; live LLM run pending ANTHROPIC_API_KEY | src/detective.py, tests/test_detective.py |
| 16 | Escalation questions and non-blocking notification | done (default channel = local outbox) | src/escalations.py, tests/test_escalations.py |
| 17 | Driver registry (memory across months) | done | src/driver_registry.py, tests/test_driver_registry.py |
| 18 | Agent 2: Regime Classifier and scenario builder | built; deterministic prior tested; live LLM path pending ANTHROPIC_API_KEY | src/classifier.py, tests/test_classifier.py |
| 19 | Forecasting tool with interventions | done (small, noise-limited gain on the real agency case; see docs/intervention_backtest.md) | src/intervention_forecast.py, src/intervention_backtest.py |
| 20 | Multi-month chaining (3-month outlook) | done | src/chaining.py, tests/test_chaining.py, docs/chaining_backtest.md |
| 21 | Range calibration and simulation-based aggregate ranges | done (coverage 78-89% vs 80% target; leave-one-origin-out) | src/ranges.py, src/ranges_backtest.py, tests/test_ranges.py, docs/range_calibration.md |
| 22 | Portfolio roll-up (product, region, lender) | done | src/rollup.py, tests/test_rollup.py |
| 23 | Chart generation | done (4 charts + table view + alt text; palette validator not run: node missing) | src/charts.py, tests/test_charts.py |
| 24 | Agent 3: Review Pack Author and numeric auditor | done; template author + auditor fully tested, live LLM author pending ANTHROPIC_API_KEY | src/pack_author.py, tests/test_pack_author.py |
| 25 | Document generator (PDF + Markdown pack) | done | src/doc_generator.py, tests/test_doc_generator.py, tests/fixtures.py |
| 26 | Orchestrator (LangGraph, parallel workers, failure handling) | done; runs offline with a rule-based investigator, LLM Detective used when a key is set | src/orchestrator.py, tests/test_orchestrator.py |
| 27 | Audit trace and logging | done | src/audit_trace.py, tests/test_audit_trace.py |
| 28-31 | remaining | not started (see docs/PROJECT_CONTEXT.md) | |

Note: sections 6 and 7 were first committed under the labels "5" and "6" (numbering slip; section 5 was skipped and has now been built).
