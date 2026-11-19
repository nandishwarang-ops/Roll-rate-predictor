"""Section 19: forecasting tool with interventions (blip / fading / lasting).
Turns the classifier's SHAPES (section 18) into numbers. The SIZE of each driver's effect is measured from data (attribution engine, section 14), never by an LLM.
  1. measure the driver's effect on its pool for every month since it started (control-adjusted contribution, baseline placed before the start);
  2. build a COUNTERFACTUAL history with that effect removed and forecast it with the ensemble (so the baseline does not already carry half the shift - no double counting);
  3. add each scenario's effect profile back:  STEP  = level shift (ramping in over `lag_months`),  DOT = gone after the origin,
     TRANSIENT = decays with a half-life or stops at a known end month;  scenarios are blended by weight;
  4. apply the effect to the transition matrix by rescaling the affected cells, so every row still sums to 1.
Outputs per run: unadjusted baseline, counterfactual, 'lasting case', 'blip case', and the weighted forecast - all tagged with a run id for citation."""
import hashlib, json, pathlib, sys, datetime
import numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import driver_registry as R, classifier as C
from forecast_models import forecast, history, KEYS
root = pathlib.Path(__file__).resolve().parent.parent
SEV = {"CURRENT": 0, "1-30": 1, "31-60": 2, "61-90": 3, "90+": 4}
MODELS = ("ets", "sarimax", "gbm")
# ------------------------------------------------------------------ matrix surgery (rows keep summing to 1)
def _group_cols(df, mcol): return ["lender_id", "product_type", "region", "bucket_from"] + [c for c in ("month_date", "h") if c in df.columns]
def shift_rows(df, rate_col, pool, metric, delta):
    """shift the pool's `metric` rate by `delta` (fraction, e.g. 0.03 = +3pp); other cells are rescaled so rows still sum to 1. `delta` may be a dict month->delta."""
    df = df.copy(); sf = df.bucket_from.map(SEV); st = df.bucket_to.map(SEV)
    cell = (st > sf) if metric == "roll_forward" else (st < sf); cell &= st.notna()
    sel = (df.lender_id == pool["lender"]) & (df.bucket_from == pool["bucket_from"])
    if pool.get("product_type"): sel &= df.product_type == pool["product_type"]
    if pool.get("region"): sel &= df.region == pool["region"]
    if not sel.any(): return df
    key = ["lender_id", "product_type", "region", "bucket_from"] + [c for c in ("month_date", "h") if c in df.columns]
    dkey = "month_date" if "month_date" in df.columns else "h"
    for k, idx in df[sel].groupby(key).groups.items():
        d = delta.get(pd.Timestamp(k[key.index("month_date")]) if "month_date" in key else k[key.index("h")], 0.0) if isinstance(delta, dict) else delta
        if not d: continue
        g = df.loc[idx]; c = cell.loc[idx]; cur = g.loc[c, rate_col].sum(); new = float(min(1.0, max(0.0, cur + d)))
        if cur > 0: df.loc[idx[c.values], rate_col] = g.loc[c, rate_col] * new / cur
        elif new > 0:                                    # nothing to scale: put the mass on the adjacent worse/better bucket
            tgt = g[c].assign(sv=st.loc[g[c].index]); tgt = tgt.sort_values("sv", ascending=(metric == "roll_forward")); df.loc[tgt.index[0], rate_col] = new
        rest = (~c).values
        if (1 - cur) > 1e-12: df.loc[idx[rest], rate_col] = g.loc[~c, rate_col] * (1 - new) / (1 - cur)
    return df
# ------------------------------------------------------------------ effect measurement + profiles
def effect_series(g, driver, origin, attr):
    """control-adjusted contribution to the POOL metric (fraction) for each month from the driver's start to the origin."""
    spec = json.loads(driver["slice_spec"]); p = spec["pool"]; start = R.M(driver["start_month"]); T = R.M(origin); out = {}
    for k in range(0, R.months_between(start, T) + 1):
        m = start.replace(year=start.year + (start.month - 1 + k) // 12, month=(start.month - 1 + k) % 12 + 1)
        res = attr(month=str(m), bucket_from=p["bucket_from"], metric=p["metric"], product_type=p["product_type"], region=p["region"], recent_months=1, baseline_lag=k, causes={"driver": spec["cause"]}, control=spec["control"])
        c = res["causes"]["driver"] if res.get("ok") else None
        out[pd.Timestamp(m)] = (c["contribution_pp"] / 100 if c and c.get("status") == "ok" else 0.0)
    return out
def profile(scn, E_T, origin, horizon=3):
    """fraction-of-pool-rate effect for forecast months origin+1..origin+horizon."""
    T = R.M(origin); out = []
    for h in range(1, horizon + 1):
        m = C.months_after(T, h); sh = scn["shape"]
        if scn.get("active") is False or sh == "DOT": e = 0.0
        elif sh == "STEP":
            lag = scn.get("lag_months") or 0; start = R.M(scn["start_month"]); c0 = min(1.0, (R.months_between(start, T) + 1) / (lag + 1)); ch = min(1.0, (R.months_between(start, m) + 1) / (lag + 1))
            e = (E_T / c0) * ch if c0 > 0 else E_T
        else:    # TRANSIENT
            if scn.get("end_month"): e = E_T if R.M(m) <= R.M(scn["end_month"]) else 0.0
            else: e = E_T * 0.5 ** (h / scn["half_life_months"])
        out.append((pd.Timestamp(m), e))
    return out
def _hash(x): return hashlib.sha1(json.dumps(x, sort_keys=True, default=str).encode()).hexdigest()[:8]
def ensemble(con, origin, hist, horizon=3):
    fs = [forecast(m, con, origin, horizon, hist=hist) for m in MODELS]
    return pd.concat(fs).groupby(KEYS + ["month_date", "h"], as_index=False).fc_rate.mean()
# ------------------------------------------------------------------ the tool
def forecast_with_interventions(lender, origin, driver_ids, con, g, attr, classifications=None, state=None, horizon=3, out_dir=root / "outputs/forecasts"):
    origin = str(R.M(origin)); hist = history(con, origin); hist = hist[hist.lender_id == lender].copy(); hist["month_date"] = pd.to_datetime(hist.month_date)
    drivers = []
    for did in driver_ids:
        d, obs = C.get_driver(did, state); cls = (classifications or {}).get(did) or C.classify_driver(did, g, origin, state=state)
        series = effect_series(g, d, origin, attr); drivers.append(dict(d=d, cls=cls, series=series, pool={**json.loads(d["slice_spec"])["pool"], "lender": lender}))
    run_id = f"fc_{lender}_{origin[:7]}_{_hash([ (x['d']['driver_id'], x['cls']['scenarios']) for x in drivers])}"
    raw = ensemble(con, origin, hist, horizon)                          # 1. unadjusted
    cf_hist = hist.copy()
    for x in drivers:                                                   # 2. remove measured effect from history
        cf_hist = shift_rows(cf_hist, "rate_count", x["pool"], x["pool"]["metric"], {m: -e for m, e in x["series"].items()})
    cf = ensemble(con, origin, cf_hist, horizon)
    def build(select):                                                  # 3. add scenario profiles back
        out = cf.copy()
        for x in drivers:
            E_T = x["series"].get(pd.Timestamp(origin), 0.0); scn_list = x["cls"]["scenarios"]; pool = x["pool"]; m = pool["metric"]
            last = [v for k, v in sorted(x["series"].items())][-3:]; E_lvl = float(np.mean(last)) if last else 0.0      # single-month estimates are noisy: STEP uses the mean of the last 3 months
            if select == "weighted": prof = {}; [prof.__setitem__(t, prof.get(t, 0) + s["weight"] * e) for s in scn_list for t, e in profile(s, E_lvl if s["shape"] == "STEP" else E_T, origin, horizon)]
            else:
                pick = max((s for s in scn_list if (s["shape"] == "STEP") == (select == "lasting")), key=lambda s: s["weight"], default=max(scn_list, key=lambda s: s["weight"]))
                prof = dict(profile(pick, E_lvl if pick["shape"] == "STEP" else E_T, origin, horizon))
            out = shift_rows(out, "fc_rate", pool, m, prof)
        return out
    res = {"run_id": run_id, "lender": lender, "origin": origin, "unadjusted": raw, "counterfactual": cf, "lasting": build("lasting"), "blip": build("blip"), "adjusted": build("weighted"),
           "drivers": [{"driver_id": x["d"]["driver_id"], "what": x["d"]["what"], "status": x["d"]["status"], "scenarios": x["cls"]["scenarios"], "pool": x["pool"], "measured_effect_pp": {str(k)[:7]: round(100 * v, 2) for k, v in x["series"].items()}} for x in drivers]}
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.concat([res[k].assign(variant=k, run_id=run_id) for k in ("unadjusted", "counterfactual", "lasting", "blip", "adjusted")]).to_parquet(out_dir / f"{run_id}.parquet")
    (out_dir / f"{run_id}.json").write_text(json.dumps({k: res[k] for k in ("run_id", "lender", "origin", "drivers")}, indent=1, default=str)); return res
def pool_metric(fc, con, pool, metric, origin):
    """opening-weighted pool metric per forecast month (weights = opening accounts in the origin month)."""
    mv = con.sql(f"select lender_id, product_type, region, bucket_from, opening_accounts w from mart.moves_segment where month_date=date '{origin}'").df()
    f = fc.copy(); f["sf"] = f.bucket_from.map(SEV); f["st"] = f.bucket_to.map(SEV); c = (f.st > f.sf) if metric == "roll_forward" else (f.st < f.sf)
    f = f[c & f.st.notna() & (f.bucket_from == pool["bucket_from"]) & (f.lender_id == pool["lender"])]
    if pool.get("product_type"): f = f[f.product_type == pool["product_type"]]
    if pool.get("region"): f = f[f.region == pool["region"]]
    f = f.groupby(["lender_id", "product_type", "region", "bucket_from", "month_date"], as_index=False).fc_rate.sum().merge(mv, on=["lender_id", "product_type", "region", "bucket_from"])
    return f.groupby("month_date").apply(lambda d: float((d.fc_rate * d.w).sum() / d.w.sum()))
def pool_actual(con, pool, metric):
    q = f"select month_date, sum({metric}*opening_accounts)/sum(opening_accounts) v from mart.moves_segment where lender_id='{pool['lender']}' and bucket_from='{pool['bucket_from']}'"
    if pool.get("product_type"): q += f" and product_type='{pool['product_type']}'"
    if pool.get("region"): q += f" and region='{pool['region']}'"
    d = con.sql(q + " group by 1 order by 1").df(); d["month_date"] = pd.to_datetime(d.month_date); return d.set_index("month_date").v
