"""Section 29b/c: tune on a bank of planted scenarios with a TRAIN/TEST split by month (train: May, Jun 2025; test: Jul 2025). Shifts persist for 3 months (T..T+2).
(1) naming variants: V0 current profiler | V1 direction filter + z ranking | V2 V1 + search parent pools | V3 V2 with a 3-month window at T+2 (+ weak leads)
(2) detection grid over z threshold, FDR q and segment materiality, scored on planted detection (train/test) and on false flags in unmodified Jun-Sep 2025 months.
The planted DB of each scenario is deleted after use (3 GB)."""
import sys, pathlib, json, time, itertools, duckdb, numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import planted as P, detection, drift_profiler as DP, driver_registry as R
from planted_backtest import BASE, S
from guarded_sql import GuardedSQL
from attribution import AttributionTool
root = pathlib.Path(__file__).resolve().parent.parent; orig = duckdb.connect(str(root / "rollrate.duckdb"), read_only=True)
MON = lambda t, k: str((pd.Timestamp(t) + pd.DateOffset(months=k)).date())
DEFAULT = dict(Z=2.5, Q=0.05, MAT=0.01, MIN_OPEN=60)
GRID = [dict(Z=z, Q=q, MAT=m, MIN_OPEN=60) for z, q, m in itertools.product([2.0, 2.5, 3.0], [0.05, 0.10], [0.005, 0.01])] + [dict(Z=2.5, Q=0.05, MAT=0.01, MIN_OPEN=30)]
def setcfg(c):
    detection.Z_THR, detection.Q, detection.MIN_OPEN = c["Z"], c["Q"], c["MIN_OPEN"]; detection.MAT = {"segment": c["MAT"], "lender_product": c["MAT"] / 2, "lender_region": c["MAT"] / 2, "lender": c["MAT"] / 2}
FC = {L: orig.sql(f"select * from mart.detect_forecasts where lender_id='{L}'").df() for L in ["LENDER_A", "LENDER_B", "LENDER_C"]}
OTH = orig.sql("select * from mart.investigations").df(); OTH["month"] = pd.to_datetime(OTH.month)
def detect_cfg(seg, spec, T, cfg, top_n=8, min_excess=25):
    setcfg(cfg); df = detection.score(detection.level_frames(seg)); inv = detection.group(df, pd.Timestamp(T))
    if not len(inv): return inv
    inv = inv.copy(); inv["abs_excess"] = inv.excess_accounts.abs(); oth = OTH[(OTH.month == pd.Timestamp(T)) & (~OTH.node.str.startswith(spec["lender"]))]
    allr = pd.concat([inv.assign(_m=1), oth.assign(_m=0, abs_excess=oth.excess_accounts.abs())], ignore_index=True, sort=False); allr["rk"] = allr.abs_excess.rank(ascending=False, method="first"); mine = allr[allr._m == 1]
    inv["priority"] = ((mine.rk.values <= top_n) & (mine.abs_excess.values >= min_excess)); return inv
def best_match(inv, spec, T):
    m = P.match(inv.assign(month=pd.Timestamp(T)) if len(inv) else inv, spec, T)
    return m.reindex(m.abs_excess.sort_values(ascending=False).index).iloc[0] if len(m) else None
def naming(path, spec, T, best):
    """naming variants for one scenario. best = matched investigation row at the default config (or None -> use the true pool)."""
    g = GuardedSQL(spec["lender"], MON(T, 2), run_id="tune", db=path); b, met = spec["bucket"], spec.get("metric", "roll_forward"); truth = set(spec["truth"]); out = {}
    node = (best["level"], best["node"]) if best is not None else ("segment" if spec["pool"].get("product_type") and spec["pool"].get("region") else "lender_product" if spec["pool"].get("product_type") else "lender_region" if spec["pool"].get("region") else "lender", None)
    if best is None:
        lvl = node[0]; L = spec["lender"]; node = (lvl, "|".join([L] + [x for x in [spec["pool"].get("product_type"), spec["pool"].get("region")] if x]))
    lvl, nd = node; hit = lambda sl, k: bool(len(sl) and any((r.dimension, str(r.slice)) in truth for r in sl.head(k).itertuples()))
    def record(tag, r, month_note=""):
        sl, ld = r["slices"], r["leads"]; allc = pd.concat([sl, ld]) if len(ld) else sl
        out[tag] = dict(top1=hit(sl, 1), top3=hit(sl, 3), flagged=int(len(sl)), top1_or_leads3=hit(allc, 3) if len(allc) else False, pool=str(r.get("pool", "")), used_detected_node=best is not None)
    p0 = nd.split("|"); prod0, reg0 = (p0[1] if lvl in ("lender_product", "segment") else None), (p0[2] if lvl == "segment" else (p0[1] if lvl == "lender_region" else None))
    record("V0_current", DP.profile(spec["lender"], T, b, met, prod0, reg0, g=g.fork(), recent=1, direction=None, rank="excess"))
    record("V1_direction_z", DP.profile(spec["lender"], T, b, met, prod0, reg0, g=g.fork(), recent=1, direction="up", rank="z"))
    record("V2_parent_pools", DP.find_slices(g, spec["lender"], T, b, met, lvl, nd, direction="up", recent=1))
    r3 = DP.find_slices(g, spec["lender"], MON(T, 2), b, met, lvl, nd, direction="up", recent=3); record("V3_3month_window_at_T+2", r3)
    r2 = DP.find_slices(g, spec["lender"], MON(T, 2), b, met, lvl, nd, direction="up", recent=1); record("V2_at_T+2_1month", r2)
    # size accuracy when the planted slice is named top 1 with the 3-month window
    if out["V3_3month_window_at_T+2"]["top1"]:
        sl = r3["slices"].iloc[0]; prod, reg = r3["pool"]; at = AttributionTool(spec["lender"], MON(T, 2), run_id="tune", g=g.fork())
        a = at(MON(T, 2), b, met, {"driver": {"dimension": sl.dimension, "values": [sl.slice]}}, product_type=prod, region=reg, recent_months=3, baseline_lag=3); ex = R.excess_from_cause(a) if a.get("ok") else None
        if ex: out["size_err_pp"] = float(ex["excess_pp"]); out["size_err_pp"] = float(ex["excess_pp"] - 100 * spec["delta"] * 1.0)
    return out
def run():
    t0 = time.time(); rows = []; TEST = "2025-07-01"
    specs = []
    for base in BASE:
        if base["name"] == "festival": continue
        for T in (["2025-05-01", "2025-06-01", "2025-07-01"] if base["name"] in ("agency", "policy") else ["2025-06-01", "2025-07-01"]):
            for size, mult in ([("base", 1.0)] + ([("half", 0.5)] if T == TEST else [])):
                specs.append(dict(base, name=f"{base['name']}_{T[5:7]}_{size}", base_name=base["name"], T=T, size=size, split="test" if T == TEST else "train", delta=base["delta"] * mult, months={T: 1.0, MON(T, 1): 1.0, MON(T, 2): 1.0}))
    for sp in specs:
        path, truth = P.scenario_db(sp); pc = duckdb.connect(str(path), read_only=True); seg = DP_seg = __import__("detection").metric_frame(pc, FC[sp["lender"]]); pc.close(); T = sp["T"]
        det = {}
        for i, cfg in enumerate(GRID):
            inv = detect_cfg(seg, sp, T, cfg); bm = best_match(inv, sp, T) if len(inv) else None; det[i] = dict(any=bm is not None, priority=bool(bm is not None and bm["priority"]))
        setcfg(DEFAULT); inv0 = detect_cfg(seg, sp, T, DEFAULT); bm0 = best_match(inv0, sp, T) if len(inv0) else None
        nm = naming(path, sp, T, bm0); rows.append(dict(name=sp["name"], base=sp["base_name"], size=sp["size"], split=sp["split"], T=T, pool_pp=truth[0]["pool_effect_pp"], slice_pp=truth[0]["slice_effect_pp"], detection=det, naming=nm))
        try: pathlib.Path(path).unlink()
        except Exception: pass
        print(f"[{time.time()-t0:5.0f}s] {sp['name']:22} det_default={det[GRID.index(DEFAULT)]} naming top1/top3: " + " ".join(f"{k.split('_')[0]}={int(v['top1'])}/{int(v['top3'])}" for k, v in nm.items() if isinstance(v, dict)), flush=True)
    # false flags on unmodified months
    ff = []
    for i, cfg in enumerate(GRID):
        setcfg(cfg); n_all = n_pri = n = 0
        for L in FC:
            seg = detection.metric_frame(orig, FC[L]); df = detection.score(detection.level_frames(seg))
            for m in pd.date_range("2025-06-01", "2025-09-01", freq="MS"):
                inv = detection.group(df, m); n += 1; n_all += len(inv)
                if len(inv): n_pri += int(((inv.excess_accounts.abs() >= 25)).sum() and min(len(inv), 3) > 0 and (inv.excess_accounts.abs().rank(ascending=False) <= 8).sum() > 0 and (inv.excess_accounts.abs() >= 25).sum())
        ff.append(dict(cfg=i, flags_per_lender_month=n_all / n, priority_like_per_lender_month=n_pri / n))
    setcfg(DEFAULT); res = dict(grid=GRID, rows=rows, false_flags=ff, secs=round(time.time() - t0)); (root / "src/tuning_results.json").write_text(json.dumps(res, indent=1, default=str)); print(json.dumps({"secs": res["secs"]}))
if __name__ == "__main__": run()
