# Data-quality report — dq_20261120_003023_5aea66

Schema `main` · 2026-11-20T00:30:23 · PASS: 16 · WARN: 2 · FAIL: 0

| | check | result |
|---|---|---|
| ✅ | D1 one row per account per month | 0 duplicated (account, month) keys |
| ✅ | D3 event_id unique | 0 duplicate event_ids |
| ✅ | No nulls in key columns | all key columns complete |
| ✅ | d1_account_monthly: 24 months per lender | LENDER_A: 24 months 2023-10-01→2025-09-01; LENDER_B: 24 months 2023-10-01→2025-09-01; LENDER_C: 24 months 2023-10-01→2025-09-01 |
| ✅ | d3_collection_events: 24 months per lender | LENDER_A: 24 months 2023-10-01→2025-09-01; LENDER_B: 24 months 2023-10-01→2025-09-01; LENDER_C: 24 months 2023-10-01→2025-09-01 |
| ✅ | bucket_flow_history: 24 months per lender | LENDER_A: 24 months 2023-10-01→2025-09-01; LENDER_B: 24 months 2023-10-01→2025-09-01; LENDER_C: 24 months 2023-10-01→2025-09-01 |
| ✅ | bucket_flow_history reconciles with D1 (account counts) | 16,050 cells compared, 0 mismatches |
| ✅ | No forward bucket skips (e.g. CURRENT -> 31-60 in one month) | 0 accounts skipped a bucket |
| ✅ | No transitions out of terminal buckets | 0 rows |
| ✅ | dpd_curr agrees with bucket_curr | 0 inconsistent rows |
| ✅ | No negative or zero amounts in D1 | 0 rows |
| ✅ | Bureau score within 300-900 | 0 rows out of range |
| ✅ | D3 events link to a D1 account | 0 orphan events |
| ✅ | D3 event_timestamp falls in its month_date | 0 events |
| ⚠️ | Successful payments carry an amount | 127 events |
| ✅ | Event calendar: end date not before start | 0 events |
| ✅ | Event calendar: 'known in advance' events announced before start | 0 events |
| ⚠️ | Segment thickness (opening accounts >= 30/month) | 16 of 180 segment-buckets have months below 30 accounts; rates there are noisy |

### Segment thickness (opening accounts >= 30/month) (first 16)
| lender | product | region | bucket | months_thin | min_accounts |
|---|---|---|---|---|---|
| LENDER_C | TWO_WHEELER | EAST | 61-90 | 24 | 10 |
| LENDER_C | BUSINESS_LOAN | EAST | 61-90 | 24 | 10 |
| LENDER_B | BUSINESS_LOAN | WEST | 61-90 | 20 | 14 |
| LENDER_B | BUSINESS_LOAN | NORTH | 61-90 | 18 | 14 |
| LENDER_C | BUSINESS_LOAN | EAST | 31-60 | 16 | 15 |
| LENDER_B | BUSINESS_LOAN | EAST | 61-90 | 15 | 16 |
| LENDER_B | BUSINESS_LOAN | SOUTH | 61-90 | 10 | 17 |
| LENDER_C | TWO_WHEELER | EAST | 31-60 | 9 | 18 |
| LENDER_B | PERSONAL_LOAN | WEST | 61-90 | 9 | 24 |
| LENDER_C | BUSINESS_LOAN | SOUTH | 61-90 | 3 | 26 |
| LENDER_B | BUSINESS_LOAN | WEST | 31-60 | 3 | 24 |
| LENDER_C | TWO_WHEELER | WEST | 61-90 | 2 | 28 |
| LENDER_C | TWO_WHEELER | SOUTH | 61-90 | 2 | 25 |
| LENDER_B | BUSINESS_LOAN | EAST | 31-60 | 2 | 26 |
| LENDER_C | BUSINESS_LOAN | WEST | 61-90 | 1 | 28 |
| LENDER_B | PERSONAL_LOAN | EAST | 61-90 | 1 | 27 |