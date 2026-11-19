# Planted-shift backtest (section 28)

Shifts planted in a scratch copy of one lender's data; ground truth never shown to the system. Detection uses the original one-step forecasts.

## Scenarios

| name          | kind                             | size   |   planted_slice_pp |   planted_pool_pp |   n_slice |   n_pool | detected_any   | detected_priority   | level          |      z |   named_correct_top1 |   named_correct_top3 |   engine_excess_pp |   excess_err_pp |
|:--------------|:---------------------------------|:-------|-------------------:|------------------:|----------:|---------:|:---------------|:--------------------|:---------------|-------:|---------------------:|---------------------:|-------------------:|----------------:|
| agency        | agency contact collapse          | base   |              10.03 |              5.48 |       339 |      620 | True           | True                | segment        |   4.22 |                    0 |                    0 |              23.35 |           13.32 |
| policy        | field-visit policy on small EMIs | base   |               8    |              6.49 |       812 |     1002 | True           | True                | lender         |   2.62 |                    0 |                    0 |             nan    |          nan    |
| cohort        | weak new-to-credit cohort        | base   |              14.98 |              0.72 |      1889 |    39514 | False          | False               | nan            | nan    |                  nan |                  nan |             nan    |          nan    |
| festival      | moved festival (lender-wide)     | base   |               1.2  |              1.2  |     88001 |    88001 | True           | True                | lender         |   4.75 |                      |                      |             nan    |          nan    |
| city          | city cash-crunch                 | base   |               5.99 |              0.98 |      1487 |     9123 | False          | False               | nan            | nan    |                  nan |                  nan |             nan    |          nan    |
| agency_half   | agency contact collapse          | half   |               5.01 |              2.74 |       339 |      620 | True           | True                | segment        |   3.65 |                    0 |                    0 |              19.43 |           14.42 |
| policy_half   | field-visit policy on small EMIs | half   |               3.94 |              3.19 |       812 |     1002 | False          | False               | nan            | nan    |                  nan |                  nan |             nan    |          nan    |
| cohort_half   | weak new-to-credit cohort        | half   |               7.52 |              0.36 |      1889 |    39514 | False          | False               | nan            | nan    |                  nan |                  nan |             nan    |          nan    |
| festival_half | moved festival (lender-wide)     | half   |               0.6  |              0.6  |     88001 |    88001 | True           | True                | lender_product |   2.81 |                      |                      |             nan    |          nan    |
| city_half     | city cash-crunch                 | half   |               3.03 |              0.49 |      1487 |     9123 | False          | False               | nan            | nan    |                  nan |                  nan |             nan    |          nan    |

## Summary

| | base size | half size |
|---|---|---|
| detected at all | 3/5 | 2/5 |
| detected as a priority investigation | 3/5 | 2/5 |
| planted slice named (top 1) where a slice exists | 0/2 | 0/1 |
| planted slice in the top 3 | 0/2 | 0/1 |

Size accuracy: engine excess minus planted effect, mean absolute error 13.9 pp over 2 scenarios (median 13.9).

## Shape classification (driver registry lifecycle)

| shape planted | expected status | status after 2 re-checks | correct |
|---|---|---|---|
| step_bigpool | persistent | persistent | True |
| transient_bigpool | closed_transient, fading | closed_transient | True |
| dot_bigpool | closed_transient | closed_transient | True |
| step | persistent | closed_transient | False |
| transient | closed_transient, fading | closed_transient | True |
| dot | closed_transient | closed_transient | True |

## Diagnostic: naming when the profiler looks at the TRUE affected pool

| scenario | planted slice named top 1 | in top 3 | slices flagged | top 3 (dimension, slice, did_pp, z) |
|---|---|---|---|---|
| agency | False | False | 0 | [] |
| policy | False | False | 0 | [] |
| cohort | False | True | 8 | [['ntc_flag', 'false', -4.5, -8.7], ['mob_band', 'mob_4-6', 8.7, 18.5], ['bureau_band', 'bureau_720+', 1.1, 3.7]] |
| city | False | True | 6 | [['state', 'Gujarat', 3.1, 6.4], ['state', 'Maharashtra', -2.1, -4.7], ['city', 'Surat', 5.8, 7.3]] |
| agency_half | False | False | 0 | [] |
| policy_half | False | False | 0 | [] |
| cohort_half | False | True | 4 | [['ntc_flag', 'false', -1.7, -3.6], ['mob_band', 'mob_4-6', 6.8, 15.5], ['mob_band', 'mob_0-3', -5.4, -15.2]] |
| city_half | False | True | 5 | [['state', 'Gujarat', 1.9, 4.1], ['state', 'Maharashtra', -1.1, -2.7], ['city', 'Surat', 2.8, 4.2]] |

## False flags on unmodified data (Jun-Sep 2025, no new seeded events)

| lender   | month               |   all_flags |   priority_flags |
|:---------|:--------------------|------------:|-----------------:|
| LENDER_A | 2025-07-01 00:00:00 |           1 |                0 |
| LENDER_B | 2025-06-01 00:00:00 |           1 |                1 |
| LENDER_B | 2025-07-01 00:00:00 |           1 |                0 |
| LENDER_B | 2025-08-01 00:00:00 |           3 |                0 |
| LENDER_B | 2025-09-01 00:00:00 |           1 |                0 |
| LENDER_C | 2025-06-01 00:00:00 |           4 |                1 |
| LENDER_C | 2025-07-01 00:00:00 |           1 |                1 |
| LENDER_C | 2025-08-01 00:00:00 |           1 |                0 |
| LENDER_C | 2025-09-01 00:00:00 |           3 |                0 |

Mean flagged investigations per lender-month: 1.78; priority: 0.33.

## Reading the results

- **Detection is power-limited, not broken.** Shifts with a pool-level effect of about 2.7 points or more (agency collapse, policy step at full size) and lender-wide shifts as small as 0.6 points (large pool, so little noise) were detected. Pool-level effects of 0.5-1.0 points on a small slice (weak cohort 0.7, city shock 1.0) were missed. The leading-indicator scan (section 11), which might catch the cohort and city cases, is not part of this harness.
- **Naming fails on a single month of a small pool.** For the agency and policy shifts the profiler flags no slice at all, even when pointed at the true pool: a 10-point effect on about 340 accounts is only about 2.3 sigma, and the false-discovery correction across about 100 candidate slices removes it. The cohort and city cases do put the planted slice in the top 3 when the true pool is searched, but not at top 1 (the complementary slice or the parent state ranks first).
- **The detected sub-pool is often not the true pool,** so the investigator searches the wrong population (agency case: it looked at one product segment of the West pool). Searching at the true pool helps for cohort and city, not for agency and policy.
- **Size accuracy** is poor where naming failed (the engine quantified a wrong slice: about 13-14 points off).
- **Shape classification is sound when the signal is strong** (3 of 3 on a high-power pool) and wrong on the noisy pool (a persistent step was closed as a blip because one month of about 600 accounts is too noisy to confirm persistence).
- **False flags:** the unmodified Jun-Sep 2025 months show about 1.8 flagged and 0.3 priority investigations per lender-month. Some are real (the ongoing West agency attrition and Lender B Autopay shifts are in these months), so this is an upper bound.

## Limits of this harness

One planted month (July 2025), one lender and one seed per shift type, five shift types, two sizes. The investigator is the rule-based one (the LLM Detective has not run). Detection uses forecasts made before the planted month. Results are indicative, not statistics.

## What section 29 should do with this

1. Let the profiler use a multi-month window (and the registry's persistence) once a shift is first flagged, since a single month cannot name a mid-sized slice.
2. Investigate at the true pool: when several sub-pools of one parent flag together, profile the parent.
3. Revisit the slice screening (q = 0.10 across about 100 hypotheses) and consider a two-stage search (dimension first, then value).
4. Re-tune detection thresholds with this harness extended to more seeds, months and lenders, and add the leading-indicator path to the detection score.
5. Make the rule-based investigator say plainly when it has no power to name a slice (it currently names whatever is largest).