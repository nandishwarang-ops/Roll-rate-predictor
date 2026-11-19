"""Section 11: leading-indicator scan + forward-calendar scan.
Runs through the lender-locked, time-locked GuardedSQL sandbox (section 5), one lender at a time.
(A) Leading indicators from D1/D3 that usually move BEFORE roll rates do: connect rate, calls and field visits per collectable
    account, PTP rate, payment-failure and gateway-timeout share, off-hours call share, UPI-Autopay share, bounce rate, tech-error
    bounce share, new-cohort share, NTC share and bureau score of new loans. Each is compared with its own trailing 6 months at
    four levels (segment, lender x product, lender x region, lender). Flag = |z| >= 3, |change| >= abs_min and denominator >= 100.
(B) Forward calendar: events known on the cutoff date that fall in the next 3 months (with the lift seen at their previous
    occurrence), plus recent lender-process/regulatory events still inside their 6-month lag window."""
import duckdb, pandas as pd, numpy as np, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from guarded_sql import GuardedSQL
root = pathlib.Path(__file__).resolve().parent.parent
LEVELS = {"segment": ["product_type", "region"], "lender_product": ["product_type"], "lender_region": ["region"], "lender": []}
# name: (numerator col, denominator col, abs_min change, hint when it moves)
IND = {
 "connect_rate": ("connected", "calls", 0.03, "lower contact -> roll-forward up in 1-30/31-60"),
 "calls_per_collectable": ("calls", "collectable", 0.15, "fewer calls per account -> roll-forward up"),
 "field_visits_per_collectable": ("field_visits", "collectable", 0.03, "fewer field visits -> 31-60/61-90 roll-forward up"),
 "field_met_rate": ("visited_met", "field_visits", 0.05, "fewer successful visits -> roll-forward up"),
 "ptp_rate": ("ptp", "connected", 0.03, "fewer promises-to-pay -> roll-forward up"),
 "pay_fail_rate": ("pay_failed", "payments", 0.02, "more failed payments -> CURRENT/1-30 roll-forward up"),
 "gateway_timeout_share": ("gateway_timeouts", "payments", 0.01, "payment-link outage -> CURRENT/1-30 roll-forward up (transient)"),
 "off_hours_call_share": ("off_calls", "calls", 0.02, "conduct / process change in calling hours"),
 "autopay_share": ("autopay_ok", "pay_ok", 0.02, "more autopay -> cures up, roll-forward down"),
 "bounce_rate": ("bounced", "nach_due", 0.01, "more NACH bounces -> CURRENT roll-forward up next month"),
 "tech_bounce_share": ("tech_bounced", "bounced", 0.05, "bank / NPCI technical failure -> transient CURRENT roll-forward spike"),
 "new_cohort_share": ("new_accts", "accounts", 0.02, "cohort mix change -> lagged roll-forward change in 2-4 months"),
 "ntc_share_new": ("ntc_new", "new_accts", 0.05, "weaker new-to-credit mix -> lagged early-MOB roll-forward up"),
 "bureau_new": ("bureau_sum_new", "new_accts", 8.0, "lower bureau score of new loans -> lagged roll-forward up"),
}
BASE_SQL = """
with d1 as (select month_date, account_id, product_type, region, mob, ntc_flag, bureau_score, nach_status, bounce_reason, bucket_curr from d1_account_monthly),
a as (select product_type, region, month_date,
        count(*) accounts,
        count(*) filter (where bucket_curr in ('1-30','31-60','61-90','90+') or nach_status='BOUNCED') collectable,
        count(*) filter (where nach_status in ('SUCCESS','BOUNCED')) nach_due,
        count(*) filter (where nach_status='BOUNCED') bounced,
        count(*) filter (where bounce_reason='TECH_ERROR_BANK_NPCI') tech_bounced,
        count(*) filter (where mob<=6) new_accts,
        count(*) filter (where mob<=6 and ntc_flag) ntc_new,
        coalesce(sum(bureau_score) filter (where mob<=6),0) bureau_sum_new
      from d1 group by all),
b as (select d1.product_type, d1.region, d3.month_date,
        count(*) filter (where channel='VOICE_CALL') calls,
        count(*) filter (where channel='VOICE_CALL' and attempt_status='CONNECTED') connected,
        count(*) filter (where channel='VOICE_CALL' and disposition_code='PTP') ptp,
        count(*) filter (where channel='VOICE_CALL' and (hour(event_timestamp)<8 or hour(event_timestamp)>=19)) off_calls,
        count(*) filter (where channel='FIELD_VISIT') field_visits,
        count(*) filter (where channel='FIELD_VISIT' and attempt_status='VISITED_MET') visited_met,
        count(*) filter (where payment_status is not null) payments,
        count(*) filter (where payment_status='FAILED') pay_failed,
        count(*) filter (where failure_reason='GATEWAY_TIMEOUT') gateway_timeouts,
        count(*) filter (where payment_status='SUCCESS') pay_ok,
        count(*) filter (where payment_status='SUCCESS' and payment_mode='UPI_AUTOPAY') autopay_ok
      from d3_collection_events d3 join d1 using (account_id, month_date) group by all)
select a.*, b.* exclude (product_type, region, month_date) from a left join b using (product_type, region, month_date)"""
COUNTS = sorted({c for n, d, *_ in IND.values() for c in (n, d)})
def indicators(g):
    base = g.query(BASE_SQL, max_rows=100000); base["month_date"] = pd.to_datetime(base.month_date); out = []
    for lvl, keys in LEVELS.items():
        agg = base.groupby(keys + ["month_date"], as_index=False)[COUNTS].sum() if keys else base.groupby("month_date", as_index=False)[COUNTS].sum()
        agg["node"] = agg[keys].astype(str).agg("|".join, axis=1) if keys else g.lender_id
        for name, (num, den, absmin, hint) in IND.items():
            x = agg[["node", "month_date", num, den]].rename(columns={num: "num", den: "den"}).copy()
            x["value"] = x.num / x.den.replace(0, np.nan); x["indicator"], x["level"], x["abs_min"], x["hint"] = name, lvl, absmin, hint
            out.append(x)
    df = pd.concat(out).dropna(subset=["value"]).sort_values("month_date")
    df["base_mean"] = df.groupby(["level", "node", "indicator"]).value.transform(lambda s: s.shift(1).rolling(6, min_periods=6).mean())
    df["base_std"] = df.groupby(["level", "node", "indicator"]).value.transform(lambda s: s.shift(1).rolling(6, min_periods=6).std())
    p = df.base_mean.clip(0.01, 0.99); se = np.sqrt(p * (1 - p) / df.den.clip(lower=1))
    sd = np.maximum(df.base_std, np.where(df.abs_min < 1, se, 0.0)); sd = np.maximum(sd, 1e-6)
    df["z"] = (df.value - df.base_mean) / sd; df["change"] = df.value - df.base_mean
    df["flag"] = (df.z.abs() >= 3) & (df.change.abs() >= df.abs_min) & (df.den >= 100)
    df["lender_id"] = g.lender_id
    return df
def forward_scan(g, horizon=3):
    A = pd.Timestamp(g.as_of); months = [A + pd.offsets.MonthBegin(i) for i in range(1, horizon + 1)]
    ev = g.query("select * from event_calendar", max_rows=1000)
    for c in ["event_start_date", "event_end_date", "announced_date"]: ev[c] = pd.to_datetime(ev[c])
    r = g.query("""select month_date, region, sum(account_count) filter (where bucket_from='CURRENT' and bucket_to='1-30') * 1.0 /
                          sum(account_count) filter (where bucket_from='CURRENT') rate
                   from bucket_flow_history group by all""", max_rows=100000); r["month_date"] = pd.to_datetime(r.month_date)
    def lift(row, m):
        s = r if pd.isna(row.region) else r[r.region == row.region]
        s = s.groupby("month_date").rate.mean(); cur = s.get(m); nb = [s.get(m + pd.offsets.MonthBegin(k)) for k in (-1, 1)]
        nb = [x for x in nb if x is not None and not np.isnan(x)]
        return None if cur is None or not nb else 100 * (cur - np.mean(nb))
    rows = []
    for e in ev.itertuples():
        end = e.event_end_date if pd.notna(e.event_end_date) else pd.Timestamp("2100-01-01")
        hit = [m for m in months if e.event_start_date <= m + pd.offsets.MonthEnd(0) and end >= m]
        if hit and e.known_in_advance and e.event_start_date > A - pd.offsets.MonthBegin(0):
            prev = ev[(ev.event_name == e.event_name) & (ev.event_end_date.fillna(ev.event_start_date) < A) & (ev.event_start_date < e.event_start_date)]
            lifts = []
            for p in prev.itertuples():          # effect can land in the event month or the one after (catch-up), keep the larger
                m0 = p.event_start_date.replace(day=1); c = [x for x in (lift(p, m0), lift(p, m0 + pd.offsets.MonthBegin(1))) if x is not None]
                if c: lifts.append(max(c, key=abs))
            rows.append(dict(kind="upcoming", event_id=e.event_id, event_name=e.event_name, category=e.event_category, start=e.event_start_date, end=e.event_end_date,
                             region=e.region, product_type=e.product_type, months_hit=",".join(m.strftime("%Y-%m") for m in hit), prior_occurrences=len(prev),
                             expected_current_to_1_30_lift_pp=round(float(np.mean(lifts)), 2) if lifts else None))
        elif e.event_category in ("LENDER_PROCESS", "REGULATORY_POLICY") and e.event_start_date <= A and (pd.isna(e.event_end_date) or e.event_end_date >= A - pd.DateOffset(months=6)):
            age = (A.year - e.event_start_date.year) * 12 + A.month - e.event_start_date.month
            rows.append(dict(kind="active_structural", event_id=e.event_id, event_name=e.event_name, category=e.event_category, start=e.event_start_date, end=e.event_end_date,
                             region=e.region, product_type=e.product_type, months_hit=f"{age} months since start", prior_occurrences=0, expected_current_to_1_30_lift_pp=None))
    fs = pd.DataFrame(rows); fs["lender_id"] = g.lender_id; fs["as_of"] = g.as_of
    return fs
def run(as_of="2025-09-01"):
    ind, fwd = [], []
    for lender in ["LENDER_A", "LENDER_B", "LENDER_C"]:
        g = GuardedSQL(lender, as_of, run_id="leading_scan"); ind.append(indicators(g)); fwd.append(forward_scan(g))
    ind, fwd = pd.concat(ind, ignore_index=True), pd.concat(fwd, ignore_index=True)
    con = duckdb.connect(str(root / "rollrate.duckdb"))
    con.register("ind", ind); con.sql("create or replace table mart.leading_indicators as select * from ind")
    con.register("fwd", fwd.astype({"start": "datetime64[ns]", "end": "datetime64[ns]"})); con.sql("create or replace table mart.forward_scan as select * from fwd")
    return ind, fwd
if __name__ == "__main__":
    ind, fwd = run()
    f = ind[ind.flag]; pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 45)
    print("flags by month (all levels):"); print(f.groupby(f.month_date.dt.strftime("%Y-%m")).size().to_string())
    for lvl in ["lender", "lender_product", "lender_region"]:
        x = f[(f.level == lvl)].copy(); x["m"] = x.month_date.dt.strftime("%Y-%m")
        print(f"\n-- {lvl} flags"); print(x.sort_values("z", key=abs, ascending=False)[["m", "node", "indicator", "value", "base_mean", "z"]].head(18).round(3).to_string(index=False))
    print("\n-- forward scan"); print(fwd[["lender_id", "kind", "event_name", "category", "region", "months_hit", "prior_occurrences", "expected_current_to_1_30_lift_pp"]].to_string(index=False))
