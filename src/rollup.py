"""Section 22: portfolio roll-up (segment -> product / region -> lender) = the single, reconciled table the review pack reads.
For one lender and origin it builds, for every node (lender, 3 products, 4 regions, 12 segments) and every metric, the last ACTUAL value and the forecast
for months +1..+3 as mean / P10 / P50 / P90, all taken from the SAME simulation draws (section 21) - so every level reconciles draw by draw.
Rates are always recomputed from summed numerators and denominators, never averaged.  Quantiles are not additive (P50 of a sum is not the sum of P50s):
the 'mean' column is the additive one and is what reconciliation checks use.
Also: shift-share 'what moved' tables (which segments drove the change in a lender-level rate, split into mix vs rate effect)."""
import json, pathlib, sys
import numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import chaining as C, ranges as RG
root = pathlib.Path(__file__).resolve().parent.parent
SEGS = C.segments(); NB = ["CURRENT", "1-30", "31-60", "61-90", "90+"]
def nodes():
    out = [("lender", "ALL", np.ones(12, bool))]
    out += [("product", p, np.array([s[0] == p for s in SEGS])) for p in ["BUSINESS_LOAN", "PERSONAL_LOAN", "TWO_WHEELER"]]
    out += [("region", r, np.array([s[1] == r for s in SEGS])) for r in ["EAST", "NORTH", "SOUTH", "WEST"]]
    out += [("segment", f"{p}|{r}", np.array([s == (p, r) for s in SEGS])) for p, r in SEGS]; return out
def draws(sim, mask):
    """every metric as an array [N,H] for the segments in `mask` (rates from summed numerators / denominators)."""
    s, f, ap = sim["stock"], sim["flows"], sim["avg_pos"]; m = mask; out = dict(RG.aggregates(sim, m))
    for b in range(5):
        den = s[:, :-1, m, b].sum(-1)                                                       # opening accounts of each forecast month
        if b < 4: out[f"roll_forward_{NB[b]}"] = f[:, :, m, b, b + 1:5].sum(-1).sum(-1) / np.where(den > 0, den, np.nan)
        if b >= 1: out[f"cure_{NB[b]}"] = f[:, :, m, b, :b].sum(-1).sum(-1) / np.where(den > 0, den, np.nan)
    return out
def actuals(q, lender, origin):
    """last observed values at every node (origin month)."""
    st, ap = C.get_state(q, lender, origin)
    mv = q(f"select product_type, region, bucket_from, opening_accounts n, roll_forward rf, cure cu from mart.moves_segment where lender_id='{lender}' and month_date=date '{origin}'")
    adds = q(f"select product_type, region, sum(account_count) a from mart.transitions_segment where lender_id='{lender}' and month_date=date '{origin}' and bucket_to='90+' and bucket_from in ('CURRENT','1-30','31-60','61-90') group by all")
    idx = {s: i for i, s in enumerate(SEGS)}; N = np.zeros((12, 5)); RF = np.zeros((12, 5)); CU = np.zeros((12, 5)); A = np.zeros(12)
    for r in mv.itertuples(): i = idx[(r.product_type, r.region)]; b = NB.index(r.bucket_from); N[i, b], RF[i, b], CU[i, b] = r.n, r.rf, r.cu
    for r in adds.itertuples(): A[idx[(r.product_type, r.region)]] = r.a
    out = {}
    for kind, name, m in nodes():
        d = {"npa_accounts": st[m, 4].sum(), "npa_additions": A[m].sum(), "npa_principal": (st[m, 4] * ap[m, 4]).sum(), "stage3_principal": (st[m, 4] * ap[m, 4]).sum(),
             "stage2_principal": (st[m, 2:4] * ap[m, 2:4]).sum(), "live_accounts": st[m].sum()}; d["npa_ratio"] = d["npa_accounts"] / d["live_accounts"]
        for b in range(5):
            den = N[m, b].sum()
            if b < 4: d[f"roll_forward_{NB[b]}"] = (N[m, b] * RF[m, b]).sum() / den if den else np.nan
            if b >= 1: d[f"cure_{NB[b]}"] = (N[m, b] * CU[m, b]).sum() / den if den else np.nan
        out[(kind, name)] = d
    return out
def build_rollup(q, lender, origin, sim, q_lo=0.1, q_hi=0.9):
    act = actuals(q, lender, origin); rows = []
    for kind, name, m in nodes():
        for metric, a in draws(sim, m).items():
            for h in range(a.shape[1]):
                x = a[:, h]; rows.append(dict(lender_id=lender, origin=str(origin)[:7], level=kind, node=name, metric=metric, h=h + 1, actual_origin=act[(kind, name)].get(metric),
                                              mean=float(np.nanmean(x)), p10=float(np.nanquantile(x, q_lo)), p50=float(np.nanquantile(x, 0.5)), p90=float(np.nanquantile(x, q_hi))))
    return pd.DataFrame(rows)
# ------------------------------------------------------------------ reconciliation
ADDITIVE = ["npa_accounts", "npa_additions", "npa_principal", "stage2_principal", "stage3_principal", "live_accounts"]
def reconcile(df, tol=1e-6):
    """additive metrics: lender == sum(products) == sum(regions) == sum(segments) on the mean. -> DataFrame of checks."""
    out = []; d = df.set_index(["level", "node", "metric", "h"])["mean"]
    for metric in ADDITIVE:
        for h in sorted(df.h.unique()):
            L = d[("lender", "ALL", metric, h)]
            for lvl in ["product", "region", "segment"]:
                s = d.xs((lvl, metric, h), level=("level", "metric", "h")).sum(); out.append(dict(metric=metric, h=h, level=lvl, lender=L, children_sum=s, ok=abs(L - s) <= tol * max(1.0, abs(L))))
    return pd.DataFrame(out)
# ------------------------------------------------------------------ what moved: shift-share across segments
def shift_share(seg0, seg1):
    """seg0/seg1: DataFrames [segment, w, r] (w = opening accounts, r = rate) for two periods -> per-segment contribution to the change in the pooled rate (pp), mix + rate = total exactly."""
    a = seg0.set_index("segment"); b = seg1.set_index("segment").reindex(a.index); w0, w1 = a.w / a.w.sum(), b.w / b.w.sum(); R0 = (w0 * a.r).sum(); R1 = (w1 * b.r).sum()
    mix = (w1 - w0) * (a.r - R0); rate = w1 * (b.r - a.r)
    return pd.DataFrame({"mix_pp": 100 * mix, "rate_pp": 100 * rate, "total_pp": 100 * (mix + rate), "rate_prev": a.r, "rate_now": b.r, "w_prev": w0, "w_now": w1}).sort_values("total_pp", key=abs, ascending=False), 100 * (R1 - R0)
def what_moved(q, lender, month, bucket="31-60", metric="roll_forward"):
    """which segments moved the lender-level rate between month-1 and month."""
    prev = (pd.Timestamp(month) - pd.DateOffset(months=1)).strftime("%Y-%m-%d")
    f = lambda m: q(f"select product_type || '|' || region segment, opening_accounts w, {metric} r from mart.moves_segment where lender_id='{lender}' and month_date=date '{m}' and bucket_from='{bucket}'")
    return shift_share(f(prev), f(str(month)[:10]))
def save(df, lender, origin, out_dir=root / "outputs/rollup"):
    out_dir.mkdir(parents=True, exist_ok=True); p = out_dir / f"{lender}_{str(origin)[:7]}.parquet"; df.to_parquet(p); return p
