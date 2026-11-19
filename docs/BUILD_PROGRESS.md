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
| 18-31 | remaining | not started | |

Note: sections 6 and 7 were first committed under the labels "5" and "6" (numbering slip; section 5 was skipped and has now been built).
