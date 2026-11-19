# Threshold tuning and accuracy evaluation (section 29)

Train = shifts planted in May and June 2025, test = July 2025 (never used to choose anything). Each shift persists for 3 months. Indicative, not statistical: 12 scenarios, one seed.

## 1. Forecast accuracy: can a better ensemble close the gap to 30%?

Leave-one-origin-out weight search over ETS / SARIMAX / GBM / naive: out-of-origin MAPE 21.7% vs equal-weight 21.8% vs seasonal-naive 29.5%, i.e. 26.4% vs 25.8% better than seasonal-naive.
Best in-sample weights {'ets': 0.2, 'sarimax': 0.2, 'gbm': 0.5, 'naive': 0.1}. The 0.6-point gain is within noise, so the equal-weight ensemble is kept. **The gap to the 30% bar is not a weighting problem.**

## 2. Naming the planted cause (top-1 / top-3 hit rates)

| variant | train top-1 | train top-3 | test top-1 | test top-3 |
|---|---|---|---|---|
| V0_current | 1/6 | 1/6 | 2/8 | 6/8 |
| V1_direction_z | 2/6 | 2/6 | 6/8 | 6/8 |
| V2_parent_pools | 3/6 | 3/6 | 5/8 | 6/8 |
| V2_at_T+2_1month | 1/6 | 3/6 | 2/8 | 2/8 |
| V3_3month_window_at_T+2 | 2/6 | 4/6 | 2/8 | 5/8 |

V0 current profiler at onset month | V1 + keep only slices moving WITH the alarm, rank by z | V2 + search the parent pools | V3 same at T+2 with a 3-month window (needs the shift to persist). Leads (unflagged, p<0.05) are listed separately below.

Weak leads (flagged top-3 plus unadjusted leads) hit rate with the 3-month window: 9/14; flagged only: 9/14.

Size accuracy when the planted slice was named top-1 (3-month window): mean absolute error 3.3 pp over 4 cases.

Per scenario:

| scenario | split | pool effect pp | V0 | V1 | V2 | V2@T+2 | V3@T+2 |
|---|---|---|---|---|---|---|---|
| agency_05_base | train | 5.79 | 0/0 | 0/0 | 1/1 | 0/1 | 0/1 |
| agency_06_base | train | 5.38 | 0/0 | 0/0 | 0/0 | 0/0 | 0/1 |
| agency_07_base | test | 5.48 | 1/1 | 1/1 | 0/1 | 0/0 | 0/1 |
| agency_07_half | test | 2.74 | 1/1 | 1/1 | 1/1 | 0/0 | 0/0 |
| policy_05_base | train | 6.56 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 |
| policy_06_base | train | 6.63 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 |
| policy_07_base | test | 6.49 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 |
| policy_07_half | test | 3.19 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 |
| cohort_06_base | train | 0.94 | 0/0 | 1/1 | 1/1 | 0/1 | 1/1 |
| cohort_07_base | test | 0.72 | 0/1 | 1/1 | 1/1 | 0/0 | 0/1 |
| cohort_07_half | test | 0.36 | 0/1 | 1/1 | 1/1 | 0/0 | 0/1 |
| city_06_base | train | 0.99 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| city_07_base | test | 0.98 | 0/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| city_07_half | test | 0.49 | 0/1 | 1/1 | 1/1 | 1/1 | 1/1 |

## 3. Detection thresholds

Detection of the planted shift at its onset month (any investigation covering the planted pool, right bucket and direction) and false flags on unmodified Jun-Sep 2025 (an upper bound: some of those months contain real seeded shifts).

| z | FDR q | segment materiality | min opening | train detected (priority) | test detected (priority) | flags per lender-month |
|---|---|---|---|---|---|---|
| 2.0 | 0.05 | 0.005 | 60 | 3/6 (3) | 2/8 (2) | 1.17 |
| 2.0 | 0.05 | 0.01 | 60 | 3/6 (3) | 2/8 (2) | 1.17 |
| 2.0 | 0.1 | 0.005 | 60 | 3/6 (3) | 2/8 (2) | 1.17 |
| 2.0 | 0.1 | 0.01 | 60 | 3/6 (3) | 2/8 (2) | 1.17 |
| 2.5 | 0.05 | 0.005 | 60 | 3/6 (3) | 2/8 (2) | 1.17 |
| 2.5 | 0.05 | 0.01 | 60 | 3/6 (3) | 2/8 (2) | 1.17 |
| 2.5 | 0.1 | 0.005 | 60 | 3/6 (3) | 2/8 (2) | 1.17 |
| 2.5 | 0.1 | 0.01 | 60 | 3/6 (3) | 2/8 (2) | 1.17 |
| 3.0 | 0.05 | 0.005 | 60 | 3/6 (3) | 2/8 (2) | 1.17 |
| 3.0 | 0.05 | 0.01 | 60 | 3/6 (3) | 2/8 (2) | 1.17 |
| 3.0 | 0.1 | 0.005 | 60 | 3/6 (3) | 2/8 (2) | 1.17 |
| 3.0 | 0.1 | 0.01 | 60 | 3/6 (3) | 2/8 (2) | 1.17 |
| 2.5 | 0.05 | 0.01 | 30 | 3/6 (3) | 2/8 (2) | 1.17 |

Chosen on TRAIN only (best priority detection with false flags no more than 25% above the current setting): z=2.0, q=0.05, segment materiality=0.005, min opening=60. Test: 2/8 priority-detected vs 2/8 with the current setting; flags per lender-month 1.17 vs 1.17.

## 4. Decisions

- **Adopted: direction filter + z ranking in the investigator (V1).** Top-1 naming 3/14 -> 8/14 over all 14 scenarios (train 1/6 -> 2/6, test 2/8 -> 6/8). The old ranking put the complement of the real slice first (a slice and its complement have equal and opposite effects).
- **Not adopted: parent-pool search (V2).** It ties V1 overall (8/14), is better on the train months and worse on the test month, and costs up to 4 profiles per investigation. It stays available (`find_slices`) but is not the default.
- **Not adopted: the 3-month window at T+2 (V3).** Top-1 4/14, worse than naming at the onset month. The intuition (more accounts, more power) did not hold in this harness; I did not find out why (candidate: baseline handling when the shift has already persisted for months). Left for later.
- **Not adopted: weak leads.** They added nothing over the flagged slices (9/14 either way).
- **Unchanged: detection thresholds.** All 13 settings gave identical detection and false-flag counts, so z threshold, FDR q, materiality and minimum opening are not the binding constraints. Detection is limited by how large the shift is relative to the forecast model's own error, so it will only improve with a better forecast or longer observation, not with a different threshold.
- **Unchanged: ensemble weights** (see section 1).

## 5. Where the system stands against the acceptance criteria (public data, indicative)

| Criterion | Result | Verdict |
|---|---|---|
| MAPE at least 30% below seasonal-naive | 25.8% (equal-weight ensemble, rolling backtest, public data) | **not met**; hidden period not tested |
| Detect a structural change | planted shifts detected at onset: 5/14; large or lender-wide shifts caught, shifts under about 1 point of pool effect and small pools missed | partial |
| Name the cause | planted slice named top-1: 8/14 (was 3/14); agency and policy shifts on small pools still not named; mechanism cannot be named without the LLM Detective | partial |
| Attribute with numbers | size error 3.3 pp when the slice is named top-1; offsets reported honestly | partial |
| Ranges | 80% ranges cover 78-89% out of origin | met (small sample) |
| Shape classification | 3 of 3 correct on a high-power pool, wrong on a noisy one | partial |
| Every claim cited, no invented numbers | enforced by the auditor (section 24) | met |
| Under 30 minutes | about 34 s per lender-month, 126 s for all three | met |
