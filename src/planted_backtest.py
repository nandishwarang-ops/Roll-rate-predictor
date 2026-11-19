"""Section 28 runner: plant shifts of several types and sizes, run detection + the rule-based investigator + the driver registry, and score:
detection (any / priority / at which level), naming (does a top-3 slice match the planted slice), size accuracy (engine excess vs planted), shape classification (STEP / DOT / TRANSIENT
-> registry status), and the false-flag rate on unmodified data. Writes docs/planted_backtest.md and src/planted_backtest.json."""
import sys, pathlib, json, time, tempfile, duckdb, numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import planted as P, driver_registry as R, drift_profiler as DP
from guarded_sql import GuardedSQL
from sql_tool import SQLTool
from attribution import AttributionTool
import orchestrator as ORC
root = pathlib.Path(__file__).resolve().parent.parent; orig = duckdb.connect(str(root / "rollrate.duckdb"), read_only=True); T = "2025-07-01"; T1, T2 = "2025-08-01", "2025-09-01"
S = lambda name, lender, kind, bucket, pool, slice_sql, delta, truth, d3=None, months=None, size="base", metric="roll_forward": dict(name=name, lender=lender, kind=kind, bucket=bucket, pool=pool, slice_sql=slice_sql, delta=delta, d3=d3, truth=truth, months=months or {T: 1.0}, size=size, metric=metric)
BASE = [S("agency", "LENDER_A", "agency contact collapse", "31-60", {"region": "WEST"}, "agency_id='AG_W_TELE_01'", 0.10, [("agency_id", "AG_W_TELE_01")], d3=dict(kind="calls", frac=0.6)),
        S("policy", "LENDER_B", "field-visit policy on small EMIs", "31-60", {}, "emi_amount<10000", 0.08, [("emi_band", "emi_<5k"), ("emi_band", "emi_5-10k"), ("had_field_visit", "no_visit")], d3=dict(kind="field", frac=1.0)),
        S("cohort", "LENDER_C", "weak new-to-credit cohort", "CURRENT", {"product_type": "PERSONAL_LOAN"}, "ntc_flag and mob<=6", 0.15, [("ntc_flag", "True"), ("mob_band", "mob_0-3"), ("mob_band", "mob_4-6"), ("bureau_band", "bureau_<650")]),
        S("festival", "LENDER_A", "moved festival (lender-wide)", "CURRENT", {}, "1=1", 0.012, []),
        S("city", "LENDER_A", "city cash-crunch", "CURRENT", {"product_type": "BUSINESS_LOAN", "region": "WEST"}, "city='Surat'", 0.06, [("city", "Surat")])]
SCEN = BASE + [dict(s, name=s["name"] + "_half", delta=s["delta"] / 2, size="half") for s in BASE]
BIG = S("bigpool", "LENDER_C", "personal-loan roll-forward step (high-power pool)", "CURRENT", {}, "product_type='PERSONAL_LOAN'", 0.02, [("product_type", "PERSONAL_LOAN")])
LIFE = {"step_bigpool": dict(BIG, name="life_step_big", months={T: 1.0, T1: 1.0, T2: 1.0}, expect={"persistent"}), "transient_bigpool": dict(BIG, name="life_transient_big", months={T: 1.0, T1: 0.5, T2: 0.25}, expect={"fading", "closed_transient"}), "dot_bigpool": dict(BIG, name="life_dot_big", months={T: 1.0}, expect={"closed_transient"}),
        "step": dict(BASE[0], name="life_step", months={T: 1.0, T1: 1.0, T2: 1.0}, expect={"persistent"}), "transient": dict(BASE[0], name="life_transient", months={T: 1.0, T1: 0.5, T2: 0.25}, expect={"fading", "closed_transient"}),
        "dot": dict(BASE[0], name="life_dot", months={T: 1.0}, expect={"closed_transient"})}
def investigate(path, spec, month, inv_row):
    g = GuardedSQL(spec["lender"], month, run_id="planted", db=path); sql = SQLTool(spec["lender"], month, run_id="pl", g=g.fork()); attr = AttributionTool(spec["lender"], month, run_id="pl", g=g.fork())
    inv = dict(inv_row, month=month, level=inv_row["level"], node=inv_row["node"]); res = ORC.rule_detective(inv, sql, attr, g.fork(), "pl"); return res, g, attr
def run_scenario(spec, orig_con=orig):
    t0 = time.time(); path, truth = P.scenario_db(spec); inv = P.detect(path, spec, orig_con); m = P.match(inv, spec, T); out = dict(name=spec["name"], kind=spec["kind"], size=spec["size"], planted_slice_pp=truth[0]["slice_effect_pp"], planted_pool_pp=truth[0]["pool_effect_pp"], n_slice=truth[0]["n_slice"], n_pool=truth[0]["n_pool"])
    out["detected_any"] = bool(len(m)); out["detected_priority"] = bool(len(m) and m.priority.any())
    if len(m):
        best = m.reindex(m.abs_excess.sort_values(ascending=False).index).iloc[0]; out.update(level=best["level"], node=best["node"], z=float(best["z"]), diff_pp=float(best["diff_pp"]))
        try:
            res, g, attr = investigate(path, spec, T, best.to_dict())
            if res["status"] == "complete":
                f = res["findings"]; d = f["drivers"]; slices = [(x["where"].get("sub_slice", "")) for x in d]; out["named_slices"] = slices; out["unexplained"] = bool(f.get("unexplained_note"))
                prof = DP.profile(spec["lender"], T, spec["bucket"], spec.get("metric", "roll_forward"), spec["pool"].get("product_type"), spec["pool"].get("region"), g=g.fork(), recent=1); sl = prof["slices"]
                top3 = [(r_.dimension, str(r_.slice)) for r_ in sl.head(3).itertuples()]; out["top3_slices"] = top3; truth_set = set(spec["truth"])
                out["named_correct_top1"] = bool(top3 and top3[0] in truth_set) if truth_set else None; out["named_correct_top3"] = bool(any(x in truth_set for x in top3)) if truth_set else None
                if d:
                    ev = res["evidence"][d[0]["attribution_id"]]; ex = R.excess_from_cause(ev)
                    if ex: out["engine_excess_pp"] = float(ex["excess_pp"]); out["excess_err_pp"] = float(ex["excess_pp"] - truth[0]["slice_effect_pp"])
        except Exception as e: out["investigate_error"] = f"{type(e).__name__}: {e}"
    out["secs"] = round(time.time() - t0, 1); return out, path
def lifecycle(key, spec):
    """shape classification scored on its own: the driver is registered with the TRUE slice (naming is scored separately), then re-checked in the next two months."""
    path, truth = P.scenario_db(spec); st = pathlib.Path(tempfile.mkdtemp()) / "state.duckdb"; dim, val = spec["truth"][0]; p = spec["pool"]
    g1 = GuardedSQL(spec["lender"], T2, run_id="planted_life", db=path); at = AttributionTool(spec["lender"], T2, run_id="life", g=g1.fork())
    a = at(T, spec["bucket"], spec.get("metric", "roll_forward"), {"driver": {"dimension": dim, "values": [val]}}, product_type=p.get("product_type"), region=p.get("region"), recent_months=1, baseline_lag=3)
    res = dict(investigation=dict(month=T, node=f"{spec['lender']}|" + "|".join(x for x in [p.get("product_type"), p.get("region")] if x), metric=spec.get("metric", "roll_forward"), bucket_from=spec["bucket"]),
               findings=dict(drivers=[dict(what="planted", where=dict(lender=spec["lender"], sub_slice=f"{dim} {val}", **({"region": p["region"]} if p.get("region") else {})), when=dict(start_month=T[:7]), category="operational", evidence_ids=[a["attribution_id"]], attribution_id=a["attribution_id"], confidence="high", control_group_note="rest of pool")]))
    ids = R.register_from_result(res, at.evidence, st, "life")
    if not ids: return dict(name=key, expected=sorted(spec["expect"]), status="driver not registered"), None
    hist = []
    for m_ in (T1, T2):
        out = R.recheck_all(spec["lender"], m_, at, st, "life"); hist.append([(o.get("status"), o.get("reason", "")[:70]) for o in out])
    c = R._con(st); s_ = c.sql("select status from drivers").fetchone()[0]; c.close(); return dict(name=key, expected=sorted(spec["expect"]), status=s_, ok=s_ in spec["expect"], history=hist), None
def naming_at_true_pool(spec):
    """diagnostic: can the profiler name the planted slice when it looks at the TRUE affected pool (rather than the sub-pool the detector flagged)?"""
    path, truth = P.scenario_db(spec); g = GuardedSQL(spec["lender"], T, run_id="planted_diag", db=path); p = spec["pool"]
    sl = DP.profile(spec["lender"], T, spec["bucket"], spec.get("metric", "roll_forward"), p.get("product_type"), p.get("region"), g=g.fork(), recent=1)["slices"]
    top3 = [(r_.dimension, str(r_.slice), round(float(r_.did_pp), 1), round(float(r_.z), 1)) for r_ in sl.head(3).itertuples()]; ts = set(spec["truth"])
    return dict(name=spec["name"], top3=top3, top1_correct=bool(top3 and top3[0][:2] in ts), top3_correct=any(x[:2] in ts for x in top3), n_flagged=int(len(sl)))
if __name__ == "__main__":
    t0 = time.time(); rows = []
    for spec in SCEN:
        r_, _ = run_scenario(spec); rows.append(r_); print(f"[{time.time()-t0:5.0f}s] {spec['name']:14} detected={r_['detected_any']} priority={r_['detected_priority']} level={r_.get('level')} named1={r_.get('named_correct_top1')} named3={r_.get('named_correct_top3')} excess_err={r_.get('excess_err_pp')}", flush=True)
    life = []
    for k, spec in LIFE.items():
        r_, _ = lifecycle(k, spec); life.append(r_); print(f"[{time.time()-t0:5.0f}s] lifecycle {k}: expected {r_['expected']} got {r_['status']}", flush=True)
    diag = []
    for spec in [x for x in SCEN if x["truth"]]:
        d_ = naming_at_true_pool(spec); diag.append(d_); print(f"[{time.time()-t0:5.0f}s] diag {d_['name']:14} top1={d_['top1_correct']} top3={d_['top3_correct']} flagged={d_['n_flagged']} {d_['top3']}", flush=True)
    # false flags on unmodified data (months with no NEW seeded event in the public answer key are Jun-Sep 2025)
    ff = orig.sql("select substr(node,1,8) lender, month, count(*) all_flags, count(*) filter (where priority) priority_flags from mart.investigations where month between date '2025-06-01' and date '2025-09-01' group by 1,2 order by 1,2").df()
    res = dict(scenarios=rows, lifecycle=life, diagnostics=diag, false_flags=ff.to_dict("records"), secs=round(time.time() - t0)); (root / "src/planted_backtest.json").write_text(json.dumps(res, indent=1, default=str)); print(json.dumps({"secs": res["secs"]}))
