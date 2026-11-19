# Column catalogue (public schema, generated 2026-11-20)

## bucket_flow_history — 16,050 rows, 24 months (2023-10 → 2025-09)

| column | type | null% | distinct | min | max | values |
|---|---|---|---|---|---|---|
| lender_id | VARCHAR | 0.0 | 3 | LENDER_A | LENDER_C | LENDER_A, LENDER_B, LENDER_C |
| month_date | DATE | 0.0 | 25 | 2023-10-01 | 2025-09-01 | 2025-06-01, 2025-03-01, 2025-05-01, 2024-04-01, 2024-12-01, 2025-07-01, 2023-12-01, 2025-09-01, 2024-03-01, 2025-01-01, 2024-05-01, 2025-04-01 |
| product_type | VARCHAR | 0.0 | 3 | BUSINESS_LOAN | TWO_WHEELER | PERSONAL_LOAN, TWO_WHEELER, BUSINESS_LOAN |
| region | VARCHAR | 0.0 | 4 | EAST | WEST | NORTH, SOUTH, WEST, EAST |
| bucket_from | VARCHAR | 0.0 | 5 | 1-30 | CURRENT | 90+, 31-60, 61-90, CURRENT, 1-30 |
| bucket_to | VARCHAR | 0.0 | 7 | 1-30 | WRITTEN_OFF | CURRENT, 1-30, 31-60, 61-90, 90+, CLOSED, WRITTEN_OFF |
| account_count | INTEGER | 0.0 | 1,623 | 1 | 14350 |  |
| pos_opening_amount | BIGINT | 0.0 | 21,281 | 0 | 3121793786 |  |

## d1_account_monthly — 6,039,086 rows, 24 months (2023-10 → 2025-09)

| column | type | null% | distinct | min | max | values |
|---|---|---|---|---|---|---|
| month_date | DATE | 0.0 | 25 | 2023-10-01 | 2025-09-01 | 2025-09-01, 2025-08-01, 2025-07-01, 2025-06-01, 2025-05-01, 2025-04-01, 2025-03-01, 2025-02-01, 2025-01-01, 2024-12-01, 2024-11-01, 2024-10-01 |
| account_id | VARCHAR | 0.0 | 569,202 | KAFBL1912060456 | SFSTW2509257250 |  |
| lender_id | VARCHAR | 0.0 | 3 | LENDER_A | LENDER_C | LENDER_A, LENDER_B, LENDER_C |
| product_type | VARCHAR | 0.0 | 3 | BUSINESS_LOAN | TWO_WHEELER | PERSONAL_LOAN, TWO_WHEELER, BUSINESS_LOAN |
| region | VARCHAR | 0.0 | 4 | EAST | WEST | SOUTH, WEST, NORTH, EAST |
| state | VARCHAR | 0.0 | 17 | Andhra Pradesh | West Bengal | Maharashtra, Gujarat, Tamil Nadu, Karnataka, Delhi, Uttar Pradesh, West Bengal, Rajasthan, Telangana, Kerala, Haryana, Punjab |
| city | VARCHAR | 0.0 | 31 | Ahmedabad | Vijayawada |  |
| pin_code | VARCHAR | 0.0 | 558 | 110009 | 834091 |  |
| disbursement_date | DATE | 0.0 | 2,051 | 2018-11-04 | 2025-09-28 |  |
| loan_amount | INTEGER | 0.0 | 2,726 | 30000 | 3000000 |  |
| tenure_months | SMALLINT | 0.0 | 6 | 12 | 48 | 36, 24, 12, 48, 30, 18 |
| interest_rate | DECIMAL(5,2) | 0.0 | 1,718 | 10.00 | 26.00 |  |
| emi_amount | INTEGER | 0.0 | 52,927 | 813 | 286576 |  |
| emi_due_day | TINYINT | 0.0 | 6 | 2 | 15 | 5, 7, 2, 10, 15, 3 |
| mob | SMALLINT | 0.0 | 71 | 0 | 74 |  |
| employment_type | VARCHAR | 0.0 | 3 | GIG_WORKER | SELF_EMPLOYED | SALARIED, SELF_EMPLOYED, GIG_WORKER |
| bureau_score | SMALLINT | 12.5 | 296 | 600 | 890 |  |
| ntc_flag | BOOLEAN | 0.0 | 2 | false | true | False, True |
| pos_opening | BIGINT | 4.64 | 802,529 | 0 | 3000000 |  |
| pos_closing | BIGINT | 0.0 | 802,529 | 0 | 3000000 |  |
| overdue_amount | INTEGER | 0.0 | 109,060 | 0 | 4498714 |  |
| dpd_prev | SMALLINT | 4.64 | 484 | 0 | 1016 |  |
| dpd_curr | SMALLINT | 0.0 | 502 | 0 | 1016 |  |
| bucket_prev | VARCHAR | 0.0 | 6 | 1-30 | NEW | CURRENT, NEW, 90+, 1-30, 31-60, 61-90 |
| bucket_curr | VARCHAR | 0.0 | 7 | 1-30 | WRITTEN_OFF | CURRENT, 90+, 1-30, CLOSED, 31-60, 61-90, WRITTEN_OFF |
| nach_status | VARCHAR | 0.0 | 3 | BOUNCED | SUCCESS | SUCCESS, BOUNCED, NOT_DUE |
| bounce_reason | VARCHAR | 82.95 | 6 | ACCOUNT_CLOSED | TECH_ERROR_BANK_NPCI | None, INSUFFICIENT_FUNDS, MANDATE_CANCELLED_BY_CUSTOMER, AMOUNT_EXCEEDS_MANDATE_LIMIT, TECH_ERROR_BANK_NPCI, PAYMENT_STOPPED_BY_DRAWER, ACCOUNT_FROZEN_BLOCKED, ACCOUNT_CLOSED |
| agency_id | VARCHAR | 81.72 | 21 | AG_E_FLD_01 | CN_W_DIGI | None, CN_S_DIGI, CN_W_DIGI, CN_N_DIGI, CN_E_DIGI, AG_W_FLD_01, AG_W_FLD_02, AG_S_FLD_02, AG_N_FLD_02, AG_N_FLD_01, AG_S_FLD_01, AG_E_FLD_01 |
| allocation_channel | VARCHAR | 0.0 | 5 | DIGITAL_TELE | TELE | NONE, DIGITAL_TELE, FIELD_LEGAL, TELE, FIELD |
| account_status | VARCHAR | 0.0 | 3 | ACTIVE | WRITTEN_OFF | ACTIVE, CLOSED, WRITTEN_OFF |
| closure_reason | VARCHAR | 96.07 | 4 | FORECLOSED | WRITTEN_OFF | None, MATURED, FORECLOSED, WRITTEN_OFF, SETTLED |

## d3_collection_events — 10,293,016 rows, 24 months (2023-10 → 2025-09)

| column | type | null% | distinct | min | max | values |
|---|---|---|---|---|---|---|
| event_id | VARCHAR | 0.0 | 8,629,983 | EV23100000000 | EV25090454068 |  |
| account_id | VARCHAR | 0.0 | 274,806 | KAFBL1912060456 | SFSTW2508252932 |  |
| lender_id | VARCHAR | 0.0 | 3 | LENDER_A | LENDER_C | LENDER_A, LENDER_B, LENDER_C |
| month_date | DATE | 0.0 | 25 | 2023-10-01 | 2025-09-01 | 2024-12-01, 2025-08-01, 2025-03-01, 2025-09-01, 2025-01-01, 2025-02-01, 2025-07-01, 2025-06-01, 2023-12-01, 2025-05-01, 2025-04-01, 2024-11-01 |
| event_timestamp | TIMESTAMP | 0.0 | 8,469,991 | 2023-10-01 07:00:03 | 2025-09-30 19:59:58 |  |
| channel | VARCHAR | 0.0 | 7 | FIELD_COLLECTION | WHATSAPP | VOICE_CALL, SMS, WHATSAPP, PAYMENT, FIELD_VISIT, LEGAL_NOTICE, FIELD_COLLECTION |
| agency_id | VARCHAR | 5.11 | 26 | AG_E_FLD_01 | LGL_W_01 | CN_S_DIGI, CN_W_DIGI, CN_N_DIGI, CN_E_DIGI, None, AG_W_FLD_02, AG_W_FLD_01, AG_S_FLD_02, AG_N_FLD_02, AG_N_FLD_01, AG_S_FLD_01, AG_E_FLD_01 |
| agent_id | VARCHAR | 46.83 | 1,202 | AG_E_FLD_01-A001 | CN_W_DIGI-A060 |  |
| attempt_status | VARCHAR | 0.0 | 16 | ATTEMPTED | VISITED_MET | DELIVERED, NO_ANSWER, READ, CONNECTED, SWITCHED_OFF, COMPLETED, INVALID_NUMBER, NOT_REACHABLE, BUSY, FAILED_DELIVERY, VISITED_MET, DOOR_LOCKED |
| disposition_code | VARCHAR | 0.0 | 29 | ALREADY_PAID_CLAIM | WRONG_NUMBER | REMINDER_SENT, PAYMENT_LINK_SENT, RNR, SW_OFF, PAYMENT_RECEIVED, WRONG_NUMBER, NOT_REACHABLE, BUSY, PTP, REVISIT_PLANNED, CALLBACK_REQUESTED, THIRD_PARTY_CONTACT |
| call_duration_sec | SMALLINT | 51.69 | 1,323 | 0 | 1462 |  |
| ptp_amount | INTEGER | 97.66 | 53,520 | 825 | 3430392 |  |
| ptp_date | DATE | 97.66 | 685 | 2023-10-02 | 2025-10-08 |  |
| payment_mode | VARCHAR | 94.75 | 6 | BRANCH_DEPOSIT | UPI_PAYMENT_LINK | None, UPI_PAYMENT_LINK, NEFT_IMPS, BRANCH_DEPOSIT, NACH_REPRESENTATION, UPI_AUTOPAY, CASH_FIELD |
| payment_status | VARCHAR | 94.75 | 2 | FAILED | SUCCESS | None, SUCCESS, FAILED |
| payment_amount | INTEGER | 94.75 | 50,796 | 0 | 1555918 |  |
| failure_reason | VARCHAR | 99.6 | 3 | BANK_DECLINE | INSUFFICIENT_BALANCE | None, GATEWAY_TIMEOUT, BANK_DECLINE, INSUFFICIENT_BALANCE |

## dim_agency — 24 rows

| column | type | null% | distinct | min | max | values |
|---|---|---|---|---|---|---|
| agency_id | VARCHAR | 0.0 | 26 | AG_E_FLD_01 | LGL_W_01 | CN_S_DIGI, AG_S_FLD_02, AG_E_FLD_02, AG_W_TELE_01, LGL_W_01, AG_N_FLD_01, AG_W_FLD_02, CN_W_DIGI, AG_W_TELE_02, AG_N_TELE_01, AG_S_TELE_02, CN_N_DIGI |
| agency_name | VARCHAR | 0.0 | 21 | Anugraha Collections | Vishwas Field Collections | Marathwada Field Services, Purbasha Credit Management, Ekta Field Associates, Uttam Recovery Associates, Satyam & Co Advocates, Mitra Legal Chambers, CN Digital Collections Desk - North, Sri Lakshmi Credit Services, Ganga Recovery Services, Nyaya Legal Associates, Sankalp Credit Solutions, CN Digital Collections Desk - South |
| agency_type | VARCHAR | 0.0 | 4 | FIELD_AGENCY | TELE_AGENCY | TELE_AGENCY, FIELD_AGENCY, LEGAL_PARTNER, IN_HOUSE_DIGITAL_TELE |
| region | VARCHAR | 0.0 | 4 | EAST | WEST | SOUTH, EAST, WEST, NORTH |
| empanelled_since | VARCHAR | 0.0 | 4 | 2019-04-01 | 2022-04-01 | 2019-04-01, 2021-10-01, 2022-04-01, 2020-07-01, 2021-01-01 |
| contract_status | VARCHAR | 0.0 | 1 | ACTIVE | ACTIVE | ACTIVE |

## dim_bucket — 8 rows

| column | type | null% | distinct | min | max | values |
|---|---|---|---|---|---|---|
| bucket_code | VARCHAR | 0.0 | 7 | 1-30 | WRITTEN_OFF | CURRENT, 61-90, NEW, 90+, CLOSED, 31-60, WRITTEN_OFF, 1-30 |
| dpd_min | DOUBLE | 37.5 | 5 | 0.0 | 91.0 | None, 0.0, 91.0, 31.0, 61.0, 1.0 |
| dpd_max | DOUBLE | 37.5 | 5 | 0.0 | 9999.0 | None, 0.0, 30.0, 60.0, 90.0, 9999.0 |
| severity_order | DOUBLE | 12.5 | 7 | -1.0 | 5.0 | -1.0, 2.0, 3.0, 0.0, 5.0, 1.0, 4.0, None |
| ind_as_stage | VARCHAR | 25.0 | 3 | Stage 1 | Stage 3 | Stage 1, None, Stage 2, Stage 3 |
| is_terminal | BOOLEAN | 0.0 | 2 | false | true | False, True |
| description | VARCHAR | 0.0 | 7 | Disbursed this month (bucket_prev only) | Written off (typically 180+ DPD) | One EMI overdue (SMA-0), Disbursed this month (bucket_prev only), No overdue EMI, Three EMIs overdue (SMA-2), NPA, Matured, foreclosed or settled, Written off (typically 180+ DPD), Two EMIs overdue (SMA-1) |

## dim_geography — 594 rows

| column | type | null% | distinct | min | max | values |
|---|---|---|---|---|---|---|
| pin_code | VARCHAR | 0.0 | 558 | 110009 | 834091 |  |
| city | VARCHAR | 0.0 | 31 | Ahmedabad | Vijayawada |  |
| state | VARCHAR | 0.0 | 17 | Andhra Pradesh | West Bengal | Maharashtra, Tamil Nadu, Gujarat, Kerala, Uttar Pradesh, Karnataka, Delhi, Punjab, Bihar, Jharkhand, West Bengal, Assam |
| region | VARCHAR | 0.0 | 4 | EAST | WEST | SOUTH, WEST, NORTH, EAST |
| coastal_flood_zone | BOOLEAN | 0.0 | 2 | false | true | False, True |

## dim_lender — 3 rows

| column | type | null% | distinct | min | max | values |
|---|---|---|---|---|---|---|
| lender_id | VARCHAR | 0.0 | 3 | LENDER_A | LENDER_C | LENDER_B, LENDER_C, LENDER_A |
| lender_name | VARCHAR | 0.0 | 3 | Kaveri Auto & Personal Finance Ltd | Sahyadri Finserv Ltd | Sahyadri Finserv Ltd, Kaveri Auto & Personal Finance Ltd, Nimbus Digital Lending Pvt Ltd |
| lender_type | VARCHAR | 0.0 | 3 | Digital NBFC (Fintech) | Vehicle & Consumer NBFC | Vehicle & Consumer NBFC, Digital NBFC (Fintech), Diversified NBFC |
| hq_city | VARCHAR | 0.0 | 3 | Bengaluru | Pune | Chennai, Pune, Bengaluru |
| account_prefix | VARCHAR | 0.0 | 3 | KAF | SFS | SFS, KAF, NDL |
| cn_client_since | VARCHAR | 0.0 | 3 | 2021-06-01 | 2022-08-01 | 2021-06-01, 2022-08-01, 2022-01-01 |
| products_offered | VARCHAR | 0.0 | 3 | PERSONAL_LOAN|BUSINESS_LOAN|TWO_WHEELER | TWO_WHEELER|PERSONAL_LOAN|BUSINESS_LOAN | TWO_WHEELER|PERSONAL_LOAN|BUSINESS_LOAN, PERSONAL_LOAN|BUSINESS_LOAN|TWO_WHEELER, PERSONAL_LOAN|TWO_WHEELER|BUSINESS_LOAN |

## dim_product — 3 rows

| column | type | null% | distinct | min | max | values |
|---|---|---|---|---|---|---|
| product_type | VARCHAR | 0.0 | 3 | BUSINESS_LOAN | TWO_WHEELER | BUSINESS_LOAN, PERSONAL_LOAN, TWO_WHEELER |
| product_code | VARCHAR | 0.0 | 3 | BL | TW | TW, BL, PL |
| product_name | VARCHAR | 0.0 | 3 | Personal Loan | Unsecured Business Loan (MSME) | Personal Loan, Unsecured Business Loan (MSME), Two-Wheeler Loan |
| secured_flag | BOOLEAN | 0.0 | 2 | false | true | False, True |
| collateral | VARCHAR | 0.0 | 2 | Hypothecated vehicle | None | None, Hypothecated vehicle |
| typical_ticket_inr | VARCHAR | 0.0 | 3 | 1,50,000 - 30,00,000 | 55,000 - 2,50,000 | 55,000 - 2,50,000, 30,000 - 10,00,000, 1,50,000 - 30,00,000 |
| typical_tenure_months | VARCHAR | 0.0 | 2 | 12-36 | 12-48 | 12-36, 12-48 |
| interest_rate_range_pct | VARCHAR | 0.0 | 3 | 10-19 | 16-26 | 16-26, 10-19, 13-24 |

## event_calendar — 32 rows

| column | type | null% | distinct | min | max | values |
|---|---|---|---|---|---|---|
| event_id | VARCHAR | 0.0 | 36 | EVT001 | EVT033 |  |
| event_name | VARCHAR | 0.0 | 17 | Christmas & New Year | UPI Autopay & WhatsApp payment links launched | Christmas & New Year, Diwali, Durga Puja, RBI repo rate cut, Pongal / Sankranti, Holi, Eid-ul-Fitr, Onam, Ganesh Chaturthi, Fiscal year-end collections drive, Penal charges framework, Monsoon flooding - coastal Karnataka & Kerala |
| event_category | VARCHAR | 0.0 | 5 | FESTIVAL | REGULATORY_POLICY | FESTIVAL, MACRO_SHOCK, LENDER_PROCESS, FISCAL_PERIOD, REGULATORY_POLICY |
| event_start_date | DATE | 0.0 | 28 | 2023-10-20 | 2025-12-24 | 2024-04-01, 2025-03-01, 2023-10-20, 2025-06-06, 2024-01-14, 2024-03-01, 2024-03-16, 2024-03-25, 2024-04-11, 2023-12-24, 2024-08-05, 2024-09-07 |
| event_end_date | DATE | 15.62 | 21 | 2023-10-24 | 2026-01-01 | None, 2025-03-31, 2024-11-03, 2025-06-06, 2024-01-17, 2024-03-25, 2024-03-31, 2024-04-11, 2024-06-04, 2024-01-01, 2024-09-15, 2024-09-17 |
| lender_id | VARCHAR | 87.5 | 3 | LENDER_A | LENDER_C | None, LENDER_C, LENDER_A, LENDER_B |
| region | VARCHAR | 62.5 | 4 | EAST | WEST | None, SOUTH, EAST, WEST, NORTH |
| state | VARCHAR | 93.75 | 1 | Kerala | Kerala | None, Kerala |
| product_type | VARCHAR | 93.75 | 1 | PERSONAL_LOAN | PERSONAL_LOAN | None, PERSONAL_LOAN |
| description | VARCHAR | 0.0 | 18 | Diwali festival week - pan-India; elevated household spending, branch & agency holidays | Year-end holiday period | Diwali festival week - pan-India; elevated household spending, branch & agency holidays, Year-end holiday period, Durga Puja - major festival in East India; field operations slow, Holi - North India, Financial year closing - lenders run intensive collection & settlement drives, Ganeshotsav - Maharashtra & Gujarat, Harvest festival - Tamil Nadu, Andhra Pradesh, Telangana, Karnataka, Onam - Kerala, Eid-ul-Fitr - national holiday, Monetary policy: repo rate reduced by 25 bps, Penal interest replaced by flat penal charges on new and renewed loans, Revised fair-practices code: borrower calls only 08:00-19:00, call-frequency caps, mandatory call recording for agencies |
| announced_date | DATE | 0.0 | 13 | 2023-01-01 | 2025-06-06 | 2024-01-01, 2025-01-01, 2023-01-01, 2023-08-18, 2024-01-15, 2024-02-15, 2024-03-16, 2024-07-10, 2024-07-15, 2024-10-20, 2024-12-10, 2025-01-15 |
| known_in_advance | BOOLEAN | 0.0 | 2 | false | true | True, False |
