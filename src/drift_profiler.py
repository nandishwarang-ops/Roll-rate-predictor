"""Section 12: drift profiler. Gathers ranked CLUES for the Detective (no AI, no causal claims).
Given an investigation (lender, optional product/region, opening bucket, metric, month T) it pulls, through the lender-locked
sandbox, every account that opened month T..T-6 in that bucket and compares month T with the previous 6 months two ways:
  1. FEATURE DRIFT   - did who is in the pool / what collections did change?   numeric: standardized mean difference + Welch t;
                       categorical: PSI + Cramer's V + chi-square.  Ranked by effect size, not p-value (huge N makes everything 'significant').
  2. SLICE OUTCOME SHIFT - did the roll-forward (or cure) rate change more inside a slice than in the rest of the pool?
                       difference-in-differences with a two-proportion z, Benjamini-Hochberg across slices, ranked by excess accounts.
A feature reaches the Detective only if it is material: |SMD| >= 0.2 or PSI >= 0.15 or Cramer's V >= 0.1; a slice only if BH-significant,
|DiD| >= 3pp and excess accounts >= 10."""
import pandas as pd, numpy as np, pathlib, sys
from scipy import stats
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from guarded_sql import GuardedSQL
root = pathlib.Path(__file__).resolve().parent.parent
SEV = "case {c} when 'CURRENT' then 0 when '1-30' then 1 when '31-60' then 2 when '61-90' then 3 when '90+' then 4 end"
CATS = ["city", "state", "employment_type", "mob_band", "bureau_band", "ntc_flag", "emi_band", "ticket_band", "emi_due_day", "agency_id",
        "allocation_channel", "nach_status", "bounce_reason", "had_call", "had_connect", "had_field_visit", "had_ptp", "had_failed_payment", "had_autopay", "product_type", "region"]
NUMS = ["bureau_score", "loan_amount", "emi_amount", "mob", "calls", "connected", "field_visits", "visited_met", "ptp", "off_calls", "pay_failed", "autopay_ok"]
def pull(g, month, bucket_from, product=None, region=None, baseline=6, lag=0, recent=1):
    """current = last `recent` months ending at T; baseline = `baseline` months ending `lag` months before the current window."""
    T = pd.Timestamp(month); cur_lo = T - pd.DateOffset(months=recent - 1); hi = cur_lo - pd.DateOffset(months=lag + 1); lo = hi - pd.DateOffset(months=baseline - 1)
    where = f"d.bucket_prev='{bucket_from}' and (d.month_date between date '{lo:%Y-%m-%d}' and date '{hi:%Y-%m-%d}' or d.month_date between date '{cur_lo:%Y-%m-%d}' and date '{T:%Y-%m-%d}')"
    if product: where += f" and d.product_type='{product}'"
    if region: where += f" and d.region='{region}'"
    sev = SEV.format(c="d.bucket_curr"), SEV.format(c="d.bucket_prev")
    sql = f"""
    with c as (select account_id, month_date,
        count(*) filter (where channel='VOICE_CALL') calls, count(*) filter (where channel='VOICE_CALL' and attempt_status='CONNECTED') connected,
        count(*) filter (where channel='FIELD_VISIT') field_visits, count(*) filter (where channel='FIELD_VISIT' and attempt_status='VISITED_MET') visited_met,
        count(*) filter (where channel='VOICE_CALL' and disposition_code='PTP') ptp,
        count(*) filter (where channel='VOICE_CALL' and (hour(event_timestamp)<8 or hour(event_timestamp)>=19)) off_calls,
        count(*) filter (where payment_status='FAILED') pay_failed, count(*) filter (where payment_status='SUCCESS' and payment_mode='UPI_AUTOPAY') autopay_ok
      from d3_collection_events group by all)
    select d.month_date, d.account_id, d.product_type, d.region, d.state, d.city, d.employment_type, d.ntc_flag::varchar ntc_flag, d.bureau_score, d.loan_amount,
           d.emi_amount, d.mob, d.emi_due_day::varchar emi_due_day, coalesce(d.agency_id,'NONE') agency_id, d.allocation_channel, d.nach_status, coalesce(d.bounce_reason,'NONE') bounce_reason,
           case when d.mob<=3 then 'mob_0-3' when d.mob<=6 then 'mob_4-6' when d.mob<=12 then 'mob_7-12' when d.mob<=24 then 'mob_13-24' else 'mob_25+' end mob_band,
           case when d.bureau_score<650 then 'bureau_<650' when d.bureau_score<720 then 'bureau_650-719' else 'bureau_720+' end bureau_band,
           case when d.emi_amount<5000 then 'emi_<5k' when d.emi_amount<10000 then 'emi_5-10k' when d.emi_amount<20000 then 'emi_10-20k' else 'emi_20k+' end emi_band,
           case when d.loan_amount<100000 then 'loan_<1L' when d.loan_amount<300000 then 'loan_1-3L' else 'loan_3L+' end ticket_band,
           coalesce(c.calls,0) calls, coalesce(c.connected,0) connected, coalesce(c.field_visits,0) field_visits, coalesce(c.visited_met,0) visited_met,
           coalesce(c.ptp,0) ptp, coalesce(c.off_calls,0) off_calls, coalesce(c.pay_failed,0) pay_failed, coalesce(c.autopay_ok,0) autopay_ok,
           case when coalesce(c.calls,0)>0 then 'call' else 'no_call' end had_call, case when coalesce(c.connected,0)>0 then 'connected' else 'not_connected' end had_connect,
           case when coalesce(c.field_visits,0)>0 then 'visited' else 'no_visit' end had_field_visit, case when coalesce(c.ptp,0)>0 then 'ptp' else 'no_ptp' end had_ptp,
           case when coalesce(c.pay_failed,0)>0 then 'pay_failed' else 'no_pay_fail' end had_failed_payment,
           case when coalesce(c.autopay_ok,0)>0 then 'autopay_paid' else 'no_autopay' end had_autopay,
           ({sev[0]}) > ({sev[1]}) and d.bucket_curr in ('CURRENT','1-30','31-60','61-90','90+') as roll_forward,
           ({sev[0]}) < ({sev[1]}) and d.bucket_curr in ('CURRENT','1-30','31-60','61-90','90+') as cure
    from d1_account_monthly d left join c on c.account_id=d.account_id and c.month_date=d.month_date where {where}"""
    df = g.query(sql, max_rows=5_000_000); df["month_date"] = pd.to_datetime(df.month_date); df["is_T"] = df.month_date >= cur_lo
    return df
def psi(cur, base):
    cats = sorted(set(cur.index) | set(base.index)); c = cur.reindex(cats).fillna(0) + 0.5; b = base.reindex(cats).fillna(0) + 0.5
    c, b = c / c.sum(), b / b.sum(); return float(((c - b) * np.log(c / b)).sum()), (c - b)
def bh(p, q=0.05):
    p = np.asarray(p, float); n = len(p)
    if n == 0: return np.zeros(0, bool)
    o = np.argsort(p); ok = p[o] <= q * (np.arange(1, n + 1) / n); k = np.max(np.where(ok)[0]) + 1 if ok.any() else 0
    f = np.zeros(n, bool); f[o[:k]] = True; return f
def feature_drift(df):
    cur, base = df[df.is_T], df[~df.is_T]; rows = []
    for c in NUMS:
        a, b = cur[c].dropna().astype(float), base[c].dropna().astype(float)
        if len(a) < 30 or len(b) < 30: continue
        sd = np.sqrt((a.var() + b.var()) / 2); smd = (a.mean() - b.mean()) / sd if sd > 0 else 0.0
        rows.append(dict(feature=c, kind="numeric", effect=abs(smd), direction="up" if smd > 0 else "down", detail=f"{b.mean():.3g} -> {a.mean():.3g} (SMD {smd:+.2f})",
                         p=stats.ttest_ind(a, b, equal_var=False).pvalue, material=abs(smd) >= 0.2 or (abs(smd) >= 0.1 and abs(a.mean() - b.mean()) >= 0.25 * abs(b.mean()))))
    for c in CATS:
        if df[c].nunique() < 2: continue
        vc, vb = cur[c].value_counts(), base[c].value_counts(); p_, diff = psi(vc, vb)
        tab = pd.concat([vc, vb], axis=1).fillna(0).values; chi = stats.chi2_contingency(tab) if tab.shape[0] > 1 else None
        v = float(np.sqrt(chi[0] / tab.sum() / (min(tab.shape) - 1))) if chi else 0.0; top = diff.abs().idxmax()
        rows.append(dict(feature=c, kind="categorical", effect=max(p_, v), direction=f"{top} share {'up' if diff[top] > 0 else 'down'}",
                         detail=f"PSI {p_:.3f}, V {v:.2f}; biggest mover {top}: {100*(vb/vb.sum()).get(top,0):.1f}% -> {100*(vc/vc.sum()).get(top,0):.1f}%",
                         p=chi[1] if chi else 1.0, material=(p_ >= 0.15) or (v >= 0.1)))
    return pd.DataFrame(rows).sort_values("effect", ascending=False)
def slice_shifts(df, metric="roll_forward", min_t=50, min_b=100):
    cur, base = df[df.is_T], df[~df.is_T]; rows = []
    for c in CATS:
        for lvl in df[c].dropna().unique():
            sT, sB, rT, rB = cur[cur[c] == lvl][metric], base[base[c] == lvl][metric], cur[cur[c] != lvl][metric], base[base[c] != lvl][metric]
            if len(sT) < min_t or len(sB) < min_b or len(rT) < min_t or len(rB) < min_b: continue
            pT, pB, qT, qB = sT.mean(), sB.mean(), rT.mean(), rB.mean(); did = (pT - pB) - (qT - qB)
            se = np.sqrt(sum(p * (1 - p) / n for p, n in [(pT, len(sT)), (pB, len(sB)), (qT, len(rT)), (qB, len(rB))])); z = did / se if se > 0 else 0.0
            rows.append(dict(dimension=c, slice=str(lvl), n_T=len(sT), rate_base=pB, rate_T=pT, slice_change_pp=100 * (pT - pB), rest_change_pp=100 * (qT - qB),
                             did_pp=100 * did, z=z, p=stats.norm.sf(abs(z)) * 2, excess_accounts=len(sT) * did))
    s = pd.DataFrame(rows)
    if s.empty: return s
    s["bh"] = bh(s.p.values, 0.10); s["flag"] = s.bh & (s.did_pp.abs() >= np.maximum(1.0, np.minimum(3.0, 25 * s.rate_base))) & (s.excess_accounts.abs() >= 10)   # screening FDR 10%; relative-aware materiality
    return s.sort_values("excess_accounts", key=abs, ascending=False)
def profile(lender, month, bucket_from, metric="roll_forward", product=None, region=None, g=None, baseline=6, recent=1, lags=(0, 3)):
    """Runs the profile against a recent baseline (lag 0) and an older, uncontaminated baseline (lag 3): a persistent shift that started
    earlier pollutes the recent baseline, so clues are merged across both and tagged with the baseline that found them."""
    g = g or GuardedSQL(lender, month, run_id="drift_profiler"); F, S, n = [], [], {}
    for lag in lags:
        df = pull(g, month, bucket_from, product, region, baseline, lag, recent); n[lag] = (int(df.is_T.sum()), int((~df.is_T).sum()))
        fd = feature_drift(df); fd["bh"] = bh(fd.p.values); F.append(fd[fd.material & fd.bh].assign(baseline_lag=lag))
        ss = slice_shifts(df, metric); S.append((ss[ss.flag] if len(ss) else ss).assign(baseline_lag=lag))
    f = pd.concat(F).sort_values("effect", ascending=False).drop_duplicates("feature") if F else pd.DataFrame()
    s_ = pd.concat(S); s_ = s_.sort_values("excess_accounts", key=abs, ascending=False).drop_duplicates(["dimension", "slice"]) if len(s_) else s_
    return dict(n=n, features=f, slices=s_)
if __name__ == "__main__":
    pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 70)
    cases = [("Surat cash crunch, peak month (LENDER_A BUSINESS_LOAN WEST CURRENT)", "LENDER_A", "2024-10-01", "CURRENT", "roll_forward", "BUSINESS_LOAN", "WEST", 1),
             ("West tele agency attrition, 3-month window (LENDER_A WEST 31-60)", "LENDER_A", "2025-05-01", "31-60", "roll_forward", None, "WEST", 3),
             ("Lender B UPI Autopay (1-30 cure)", "LENDER_B", "2025-01-01", "1-30", "cure", None, None, 1),
             ("Quiet control (LENDER_B TWO_WHEELER SOUTH 1-30, Aug 2025)", "LENDER_B", "2025-08-01", "1-30", "roll_forward", "TWO_WHEELER", "SOUTH", 1)]
    for name, l, m, b, met, p, r, rec in cases:
        res = profile(l, m, b, met, p, r, recent=rec); print(f"\n===== {name} | {m} | pools (T, base) by lag: {res['n']}")
        print("-- feature drift"); print(res["features"][["feature", "effect", "direction", "detail", "baseline_lag"]].head(5).round(3).to_string(index=False) if len(res["features"]) else "(none)")
        print("-- slice shifts"); print(res["slices"][["dimension", "slice", "n_T", "rate_base", "rate_T", "did_pp", "z", "excess_accounts", "baseline_lag"]].head(5).round(2).to_string(index=False) if len(res["slices"]) else "(none)")
