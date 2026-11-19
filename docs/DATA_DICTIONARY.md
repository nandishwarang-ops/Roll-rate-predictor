# PS-03 Roll-Rate Forecaster — Dataset & Data Dictionary

Synthetic but realistic Indian retail/MSME collections data for three lenders, October 2023 – December 2025.
Loans are simulated one by one, month by month. Whether a loan gets worse or better depends on the borrower's risk,
the season, and what collections actually did (calls connected, promises to pay, field visits that met the customer),
so every real-world event leaves a trail the agent can investigate.

## 1. Folders

| Folder | Months | Use |
|---|---|---|
| `reference/` | — | Lookup tables (lenders, products, buckets, geography, agencies) |
| `public/` | 2023-10 → 2025-09 (24 months) | Everything the system may use for training and investigation |
| `hidden/` | 2025-10 → 2025-12 (3 months) | Evaluation period. Contains seeded shifts. Load separately; never visible to the agent before the forecast date |
| `answer_key/` | — | Ground truth of seeded events. **For backtesting only — never load into the agent's database** |
| `schema.png` | — | Table diagram and joins |
| `generate_dataset.py` | — | Seeded generator (reproducible) |

Calendar entries are split by `announced_date`: entries announced on or before 2025-09-30 are in `public/` (this includes Diwali 2025, which is known in advance). The Lender B field-policy announcement (15 Oct 2025) is in `hidden/`.

## 2. Volumes

| Table | Public rows | Hidden rows |
|---|---:|---:|
| d1_account_monthly | 6,039,086 | 830,709 |
| d3_collection_events | 10,293,016 | 1,452,320 |
| bucket_flow_history | 16,050 | ~2,000 |
| event_calendar | 32 | 1 |

About 262,000 active loans at the latest month (≈501,000 distinct loans over the period).

| Lender | Profile | Active loans | Product mix | Region mix (N/S/E/W) |
|---|---|---:|---|---|
| LENDER_A Sahyadri Finserv Ltd | Diversified NBFC | ~120k | PL 40 / TW 30 / BL 30 | 20 / 30 / 15 / 35 |
| LENDER_B Kaveri Auto & Personal Finance Ltd | Vehicle & consumer NBFC | ~80k | TW 58 / PL 27 / BL 15 | 25 / 35 / 20 / 20 |
| LENDER_C Nimbus Digital Lending Pvt Ltd | Digital NBFC | ~62k | PL 60 / BL 22 / TW 18 | 35 / 30 / 10 / 25 |

Typical monthly rates: on-time → 1–30 ≈ 3.5%; 1–30 worsen ≈ 34%; 31–60 worsen ≈ 54%; 61–90 worsen ≈ 66%; NPA stock ≈ 5–6% of book.

## 3. Joins

- `d3.account_id + d3.month_date` → `d1.account_id + d1.month_date`
- `d1.lender_id` → `dim_lender`; `d1.product_type` → `dim_product`; `d1.pin_code` → `dim_geography`; `d1.agency_id`, `d3.agency_id` → `dim_agency`
- `d1.bucket_prev`, `d1.bucket_curr`, `bucket_flow_history.bucket_from/to` → `dim_bucket.bucket_code`
- `bucket_flow_history` = `d1` grouped by lender, month, product, region, bucket_prev → bucket_curr (rows with `bucket_prev = 'NEW'` excluded). They reconcile exactly.
- `event_calendar.lender_id / region / product_type`: NULL means "applies to all".

## 4. d1_account_monthly — one row per loan per month

| Column | Type | Meaning / values |
|---|---|---|
| month_date | DATE | Month (first day). Snapshot is as at month-end |
| account_id | VARCHAR | Loan number: lender prefix + product code + disbursal YYMM + serial (e.g. `KAFTW2409012345`) |
| lender_id | VARCHAR | LENDER_A / LENDER_B / LENDER_C |
| product_type | VARCHAR | PERSONAL_LOAN, TWO_WHEELER, BUSINESS_LOAN |
| region, state, city, pin_code | VARCHAR | Borrower location (27 cities, 594 pin codes) |
| disbursement_date | DATE | Loan start date |
| loan_amount | INT | Sanctioned amount (₹) |
| tenure_months | SMALLINT | 12–48 |
| interest_rate | DECIMAL | Annual reducing rate % |
| emi_amount | INT | Monthly instalment (₹) |
| emi_due_day | TINYINT | NACH presentation day: 2, 3, 5, 7, 10 or 15 |
| mob | SMALLINT | Months on book (0 in the disbursal month) |
| employment_type | VARCHAR | SALARIED, SELF_EMPLOYED, GIG_WORKER |
| bureau_score | SMALLINT | Credit score at origination (NULL for new-to-credit) |
| ntc_flag | BOOL | New-to-credit borrower |
| pos_opening / pos_closing | BIGINT | Principal outstanding at start / end of month |
| overdue_amount | INT | Unpaid EMIs + penal charges at month-end |
| dpd_prev / dpd_curr | SMALLINT | Days past due at previous / this month-end |
| bucket_prev / bucket_curr | VARCHAR | CURRENT, 1-30, 31-60, 61-90, 90+, CLOSED, WRITTEN_OFF (bucket_prev = NEW for fresh disbursals) |
| nach_status | VARCHAR | SUCCESS, BOUNCED, NOT_DUE |
| bounce_reason | VARCHAR | INSUFFICIENT_FUNDS, AMOUNT_EXCEEDS_MANDATE_LIMIT, MANDATE_CANCELLED_BY_CUSTOMER, PAYMENT_STOPPED_BY_DRAWER, ACCOUNT_FROZEN_BLOCKED, ACCOUNT_CLOSED, TECH_ERROR_BANK_NPCI |
| agency_id | VARCHAR | Desk/agency allocated this month (NULL if not in collections) |
| allocation_channel | VARCHAR | NONE, DIGITAL_TELE (bounced & 1–30), TELE (31–60), FIELD (61–90), FIELD_LEGAL (90+) |
| account_status | VARCHAR | ACTIVE, CLOSED, WRITTEN_OFF |
| closure_reason | VARCHAR | MATURED, FORECLOSED, SETTLED, WRITTEN_OFF |

Note: an on-time loan whose EMI bounces is worked within the same month; if it pays it stays CURRENT (with `nach_status = BOUNCED`), otherwise it ends the month in 1–30.

## 5. d3_collection_events — one row per collection action or payment

| Column | Type | Meaning / values |
|---|---|---|
| event_id | VARCHAR | Unique id |
| account_id, lender_id, month_date | | Keys to D1 |
| event_timestamp | TIMESTAMP | Date and time of the action |
| channel | VARCHAR | VOICE_CALL, SMS, WHATSAPP, FIELD_VISIT, LEGAL_NOTICE, PAYMENT, FIELD_COLLECTION |
| agency_id, agent_id | VARCHAR | Who acted (agent ids like `AG_W_TELE_02-A007`) |
| attempt_status | VARCHAR | Calls: CONNECTED, NO_ANSWER, SWITCHED_OFF, BUSY, NOT_REACHABLE, INVALID_NUMBER · Messages: DELIVERED, READ, FAILED_DELIVERY · Visits: VISITED_MET, DOOR_LOCKED, CUSTOMER_NOT_AVAILABLE, CUSTOMER_SHIFTED · Legal: NOTICE_DISPATCHED · Payments: COMPLETED, ATTEMPTED |
| disposition_code | VARCHAR | PTP, CALLBACK_REQUESTED, FOLLOW_UP_REMINDER, REFUSED_TO_PAY, THIRD_PARTY_CONTACT, FINANCIAL_DIFFICULTY, BUSINESS_LOSS, DISPUTE_RAISED, ALREADY_PAID_CLAIM, RNR, SW_OFF, BUSY, NOT_REACHABLE, WRONG_NUMBER, PARTIAL_COMMITMENT, VEHICLE_INSPECTED, SKIP_TRACE_REQUIRED, REVISIT_PLANNED, REMINDER_SENT, PAYMENT_LINK_SENT, SEC_138_NOTICE, ARBITRATION_NOTICE, PRE_LITIGATION_NOTICE, PAYMENT_RECEIVED, SETTLEMENT_PAYMENT, PAYMENT_FAILED |
| call_duration_sec | SMALLINT | Talk time |
| ptp_amount, ptp_date | INT, DATE | Promise to pay (only on PTP) |
| payment_mode | VARCHAR | UPI_PAYMENT_LINK, UPI_AUTOPAY, NACH_REPRESENTATION, NEFT_IMPS, BRANCH_DEPOSIT, CASH_FIELD |
| payment_status | VARCHAR | SUCCESS, FAILED |
| payment_amount | INT | ₹ |
| failure_reason | VARCHAR | GATEWAY_TIMEOUT, BANK_DECLINE, INSUFFICIENT_BALANCE |

Useful derived metrics: calls per account, connect rate, right-party-contact rate, PTP rate, PTP kept (PTP followed by a payment), field "met" rate, payment failure rate, share of calls outside 08:00–19:00.

## 6. bucket_flow_history

`lender_id, month_date, product_type, region, bucket_from, bucket_to, account_count, pos_opening_amount` — how many loans (and how much principal) moved from each bucket to each destination in the month. This is the input for the roll-rate matrix.

## 7. event_calendar

`event_id, event_name, event_category (FESTIVAL, FISCAL_PERIOD, REGULATORY_POLICY, LENDER_PROCESS, MACRO_SHOCK), event_start_date, event_end_date (NULL = permanent), lender_id, region, state, product_type (NULL = all), description, announced_date, known_in_advance`.

Includes real drivers, festivals on their actual dates (Diwali moves between October and November), and decoys with no effect (elections, repo-rate cuts, a CRM go-live, the penal-charges rule) so the agent must prove causes rather than assume them. Several real drivers are deliberately **not** in the calendar.

## 8. Reference tables

- **dim_lender** — id, name, type, HQ, account prefix, CN client since
- **dim_product** — product code/name, secured flag, collateral, typical ticket/tenure/rate
- **dim_bucket** — DPD range, severity order, Ind-AS stage, terminal flag
- **dim_geography** — pin code, city, state, region, coastal flood zone
- **dim_agency** — 24 desks/agencies: CN digital desks, two tele agencies and two field agencies per region, one legal partner per region

## 9. What the data is designed to test (summary — details in `answer_key/`)

Blips (gateway outage, flooding, bank auto-debit failure), fading shocks (Diwali, a local cash crunch in Surat), lasting shifts (conduct norms, a bad lending cohort with a time lag, agency staff loss, a field-visit policy change), an improvement (UPI Autopay), shifts visible only below segment level (one agency, one city), cross-lender shifts (one agency serving two lenders), and decoy calendar events.

## 10. Quick load into DuckDB

```python
import duckdb
con = duckdb.connect("rollrate.duckdb")
for t in ["d1_account_monthly", "d3_collection_events", "bucket_flow_history", "event_calendar"]:
    con.sql(f"CREATE OR REPLACE TABLE {t} AS SELECT * FROM 'public/{t}.parquet'")
for t in ["dim_lender", "dim_product", "dim_bucket", "dim_geography", "dim_agency"]:
    con.sql(f"CREATE OR REPLACE TABLE {t} AS SELECT * FROM 'reference/{t}.parquet'")
```
Hidden-period tables go into a separate schema (e.g. `hidden.*`) that the agent's SQL tool cannot read.
