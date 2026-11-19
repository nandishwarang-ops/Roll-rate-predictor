"""Section 10: hierarchical change detection (no AI, ~seconds).
Per month T, compare ACTUAL roll-forward / cure rates with the one-step-ahead forecast made at T-1 (ensemble from section 9),
for every segment and every parent level (lender, lender x product, lender x region).
  z      = (actual - expected) / sqrt(binomial_se^2 + tau^2)   tau = model error beyond sampling noise, robustly estimated
  flag   = [Benjamini-Hochberg significant at q=0.05 AND material]  OR  [CUSUM alarm AND half-material]
  material = |diff| >= 1.0pp (segment) / 0.5pp (parents) AND |diff| x opening >= 20 accounts
Grouping: a flagged parent whose flagged segments cover >= 50% of its opening accounts (or a parent flagged with no flagged
segments = diffuse shift) becomes ONE investigation at the highest such level; leftover flagged segments stand alone."""
import duckdb, pandas as pd, numpy as np, pathlib, sys
from math import erfc, sqrt
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from forecast_models import forecast, KEYS
root = pathlib.Path(__file__).resolve().parent.parent
SEV = {"CURRENT": 0, "1-30": 1, "31-60": 2, "61-90": 3, "90+": 4}
ORIGINS = pd.date_range("2024-10-01", "2025-08-01", freq="MS")
LEVELS = {"segment": ["lender_id", "product_type", "region"], "lender_product": ["lender_id", "product_type"],
          "lender_region": ["lender_id", "region"], "lender": ["lender_id"]}
Z_THR, Q, CUSUM_K, CUSUM_H, MIN_ACC, MIN_OPEN = 2.5, 0.05, 0.5, 4.0, 20, 60
TOP_N, MIN_EXCESS = 8, 25   # investigations passed to the Detective: top N by impact, each >= 25 excess accounts
MAT = {"segment": 0.01, "lender_product": 0.005, "lender_region": 0.005, "lender": 0.005}
def one_step_forecasts(con):
    """ensemble h=1 forecasts for every origin in ORIGINS (cached in mart.detect_forecasts)."""
    have = set()
    try: have = set(pd.to_datetime(con.sql("select distinct origin from mart.detect_forecasts").df().origin))
    except Exception: pass
    new = []
    for o in ORIGINS:
        if o in have: continue
        fs = [forecast(m, con, str(o.date()), horizon=1) for m in ["ets", "sarimax", "gbm"]]
        new.append(pd.concat(fs).groupby(KEYS + ["month_date"], as_index=False).fc_rate.mean().assign(origin=o))
    if new:
        df = pd.concat(new); con.register("df_new", df)
        if have: con.sql("insert into mart.detect_forecasts select * from df_new")
        else: con.sql("create or replace table mart.detect_forecasts as select * from df_new")
    return con.sql("select * from mart.detect_forecasts").df()
def metric_frame(con, fc):
    fc = fc.copy(); fc["month_date"] = pd.to_datetime(fc.month_date)
    fc["sf"] = fc.bucket_from.map(SEV); fc["st"] = fc.bucket_to.map(SEV)
    rows = []
    for metric, cond, buckets in [("roll_forward", fc.st > fc.sf, ["CURRENT", "1-30", "31-60", "61-90"]), ("cure", fc.st < fc.sf, ["1-30", "31-60", "61-90"])]:
        g = fc[cond & fc.bucket_from.isin(buckets)].groupby(["lender_id", "product_type", "region", "bucket_from", "month_date"], as_index=False).fc_rate.sum()
        rows.append(g.assign(metric=metric).rename(columns={"fc_rate": "exp"}))
    exp = pd.concat(rows)
    act = con.sql("select lender_id, product_type, region, bucket_from, month_date, opening_accounts as op, roll_forward, cure from mart.moves_segment").df()
    act["month_date"] = pd.to_datetime(act.month_date)
    act = act.melt(id_vars=["lender_id", "product_type", "region", "bucket_from", "month_date", "op"], value_vars=["roll_forward", "cure"], var_name="metric", value_name="act")
    return exp.merge(act, on=["lender_id", "product_type", "region", "bucket_from", "month_date", "metric"])
def level_frames(seg):
    out = {}
    for lvl, keys in LEVELS.items():
        g = seg.assign(e=seg.exp * seg.op, a=seg.act * seg.op).groupby(keys + ["bucket_from", "metric", "month_date"], as_index=False)[["e", "a", "op"]].sum()
        g["exp"], g["act"] = g.e / g.op, g.a / g.op
        g["level"] = lvl; g["node"] = g[keys].astype(str).agg("|".join, axis=1)
        out[lvl] = g.drop(columns=["e", "a"])
    return pd.concat(out.values(), ignore_index=True)
def bh(p, q):
    p = np.asarray(p); n = len(p); order = np.argsort(p); thr = q * (np.arange(1, n + 1) / n)
    ok = p[order] <= thr; k = np.max(np.where(ok)[0]) + 1 if ok.any() else 0
    flag = np.zeros(n, bool); flag[order[:k]] = True; return flag
def score(df):
    df = df[df.op >= 1].copy(); df["diff"] = df.act - df.exp
    p0 = df.exp.clip(0.005, 0.995); df["se"] = np.sqrt(p0 * (1 - p0) / df.op)
    df["tau"] = np.nan
    for (lvl, metric, b), idx in df.groupby(["level", "metric", "bucket_from"]).groups.items():
        sub = df.loc[idx]
        for m in sub.month_date.unique():            # leave-current-month-out robust tau
            rest = sub[sub.month_date != m]; r = rest["diff"]; mad = 1.4826 * np.median(np.abs(r - np.median(r)))
            tau2 = max(mad ** 2 - np.mean(rest.se ** 2), 1e-6)
            df.loc[sub.index[sub.month_date == m], "tau"] = np.sqrt(tau2)
    df["z"] = df["diff"] / np.sqrt(df.se ** 2 + df.tau ** 2)
    df["p"] = [erfc(abs(z) / sqrt(2)) for z in df.z]
    df["bh"] = False
    for _, idx in df.groupby(["level", "metric", "month_date"]).groups.items():
        df.loc[idx, "bh"] = bh(df.loc[idx, "p"].values, Q)
    df["material"] = (df["diff"].abs() >= df.level.map(MAT)) & (df["diff"].abs() * df.op >= MIN_ACC)
    df = df.sort_values("month_date"); sp, sn = {}, {}
    cp, cn = [], []
    for r in df.itertuples():
        k = (r.level, r.node, r.metric, r.bucket_from)
        sp[k] = max(0, sp.get(k, 0) + r.z - CUSUM_K); sn[k] = max(0, sn.get(k, 0) - r.z - CUSUM_K)
        cp.append(sp[k]); cn.append(sn[k])
    df["cusum_pos"], df["cusum_neg"] = cp, cn
    df["cusum_alarm"] = ((df.cusum_pos > CUSUM_H) | (df.cusum_neg > CUSUM_H)) & (df["diff"].abs() >= df.level.map(MAT) / 2) & (df["diff"].abs() * df.op >= MIN_ACC / 2) & (df.z.abs() >= 1.5)
    df["flag"] = ((df.bh & df.material & (df.z.abs() >= Z_THR)) | df.cusum_alarm) & (df.op >= MIN_OPEN)
    df["direction"] = np.where(df["diff"] > 0, "up", "down")
    return df
def group(df, month):
    """-> list of investigations for `month` (dicts)."""
    m = df[(df.month_date == month) & df.flag]
    seg_all = df[(df.month_date == month) & (df.level == "segment")]
    invs = []
    for (metric, b, d), g in m.groupby(["metric", "bucket_from", "direction"]):
        segs = g[g.level == "segment"].set_index("node"); covered = set()
        # candidate parents, highest level first
        for lvl in ["lender", "lender_product", "lender_region"]:
            for r in g[g.level == lvl].itertuples():
                keys = dict(zip(LEVELS[lvl], r.node.split("|")))
                sel = seg_all[(seg_all.metric == metric) & (seg_all.bucket_from == b)]
                for k, v in keys.items(): sel = sel[sel[k] == v]
                mem = set(sel.node) - covered; fl = [n for n in mem if n in segs.index]
                cov = sel[sel.node.isin(fl)].op.sum() / max(sel.op.sum(), 1)
                if mem and (cov >= 0.5 or not fl) and (len(fl) >= 2 or not fl):
                    invs.append(dict(month=month, level=lvl, node=r.node, metric=metric, bucket_from=b, direction=d, diff_pp=100 * r.diff,
                                     z=r.z, expected=r.exp, actual=r.act, opening=r.op, n_segments=len(mem), flagged_segments=len(fl),
                                     excess_accounts=r.diff * r.op, via="diffuse" if not fl else "shared"))
                    covered |= mem
        for n, r in segs.iterrows():
            if n not in covered:
                invs.append(dict(month=month, level="segment", node=n, metric=metric, bucket_from=b, direction=d, diff_pp=100 * r["diff"], z=r.z,
                                 expected=r.exp, actual=r.act, opening=r.op, n_segments=1, flagged_segments=1, excess_accounts=r["diff"] * r.op,
                                 via="cusum" if (r.cusum_alarm and not (r.bh and r.material)) else "z"))
    return pd.DataFrame(invs)
def run(con=None):
    con = con or duckdb.connect(str(root / "rollrate.duckdb"))
    fc = one_step_forecasts(con); df = score(level_frames(metric_frame(con, fc)))
    con.register("det", df); con.sql("create or replace table mart.detections as select * from det")
    invs = pd.concat([group(df, m) for m in sorted(df.month_date.unique())], ignore_index=True)
    invs["abs_excess"] = invs.excess_accounts.abs()
    invs["rank"] = invs.groupby("month").abs_excess.rank(ascending=False, method="first").astype(int)
    invs["priority"] = (invs["rank"] <= TOP_N) & (invs.abs_excess >= MIN_EXCESS)
    con.register("inv", invs); con.sql("create or replace table mart.investigations as select * from inv")
    return df, invs
if __name__ == "__main__":
    df, invs = run()
    seg = df[df.level == "segment"]
    print("segment-level series scored per month:", seg.groupby("month_date").size().iloc[0], "| flagged segment-metric-bucket cells per month:")
    print(seg.groupby("month_date").flag.sum().to_string())
    print("\ninvestigations per month (all / priority):"); print(invs.groupby("month").agg(all=("rank", "size"), priority=("priority", "sum")).to_string())
    pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 40)
    for mth in ["2024-11-01", "2024-12-01", "2025-01-01", "2025-03-01", "2025-09-01"]:
        print(f"\n== {mth}"); x = invs[(invs.month == mth) & invs.priority].sort_values("rank")
        print(x[["level", "node", "metric", "bucket_from", "direction", "diff_pp", "z", "n_segments", "via"]].head(8).round(2).to_string(index=False))
