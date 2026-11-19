"""Section 26: the orchestrator - one monthly run per lender as a LangGraph pipeline, lenders in parallel, investigations in parallel.
  checks -> prepare -> detect -> investigate (parallel workers) -> registry+classify -> escalate -> forecast -> ranges -> rollup -> charts -> pack -> finalize
Failure policy (a failed step must never silently change a number):
  * data checks FAIL                 -> run is PAUSED, no pack, analyst alerted (run record says why)
  * one investigation raises / times out -> that movement is marked 'incomplete'; its segments keep the statistical baseline; the pack says so; the run goes on
  * classifier error                 -> deterministic prior;   intervention forecast error -> baseline forecast + warning
  * chart error                      -> pack without charts;   LLM author error -> template author (same audit)
  * notification error               -> recorded, never blocks
  * range simulation / roll-up / pack error -> run FAILED with the partial run record (no half-pack is published)
Without an API key the Detective is a deterministic RULE-BASED investigator (drift profiler + attribution engine): it finds WHERE a movement is concentrated and quantifies it,
but cannot name the mechanism, so it always asks operations a question. With a key, the LLM Detective (section 15) runs instead."""
import json, pathlib, sys, time, datetime, traceback, threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FTimeout
from dataclasses import dataclass, field
from typing import Any, TypedDict
import duckdb, numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import dq_checks, detection, leading_scan, drift_profiler as DP, driver_registry as R, classifier as CL, escalations as ES, intervention_forecast as IF
import ranges as RG, rollup as RU, charts as CH, pack_author as PA, doc_generator as DG, chaining as CHN
from guarded_sql import GuardedSQL
from sql_tool import SQLTool
from attribution import AttributionTool
from detective import run_detective, validate as det_validate, pool_from_node
from audit_trace import Trace, TracedClient, code_version, data_fingerprint, sha, report as trace_report
from langgraph.graph import StateGraph, END
root = pathlib.Path(__file__).resolve().parent.parent
DB = root / "rollrate.duckdb"
@dataclass
class RunConfig:
    lender: str; origin: str; client: Any = None; state_path: Any = None; out_root: Any = root / "outputs"; n_sims: int = 1500; max_investigations: int = 3
    investigation_timeout: float = 240.0; workers: int = 3; inject: dict = field(default_factory=dict); notifier: Any = None
class S(TypedDict, total=False):
    paused: bool; status: str; stage: str
def MS(x): x = pd.Timestamp(x); return x.strftime("%Y-%m-%d")
# ------------------------------------------------------------------ rule-based investigator (offline fallback for the LLM Detective)
DIM_CAT = {"agency_id": "operational", "allocation_channel": "operational", "had_call": "operational", "had_connect": "operational", "had_field_visit": "operational", "had_ptp": "operational", "had_failed_payment": "technical_failure",
           "had_autopay": "lender_process", "bounce_reason": "technical_failure", "nach_status": "technical_failure", "emi_due_day": "technical_failure", "city": "macro_shock", "state": "macro_shock", "mob_band": "cohort", "bureau_band": "cohort",
           "ntc_flag": "cohort", "employment_type": "cohort", "ticket_band": "cohort", "emi_band": "lender_process", "product_type": "operational", "region": "operational"}
DIM_LABEL = {"agency_id": "agency", "allocation_channel": "allocation channel", "had_call": "call activity", "had_connect": "contact status", "had_field_visit": "field-visit activity", "had_ptp": "promise-to-pay status", "had_failed_payment": "payment-failure status",
             "had_autopay": "autopay status", "bounce_reason": "NACH bounce reason", "nach_status": "NACH status", "emi_due_day": "EMI due day", "city": "city", "state": "state", "mob_band": "loan age band", "bureau_band": "bureau-score band", "ntc_flag": "new-to-credit flag",
             "employment_type": "employment type", "ticket_band": "ticket-size band", "emi_band": "EMI-size band", "product_type": "product", "region": "region"}
NATIVE = {"agency_id", "city", "state", "employment_type", "nach_status", "bounce_reason", "allocation_channel", "emi_due_day", "ntc_flag"}
def rule_detective(inv, sql, attr, g, run_id):
    lender, prod, reg = pool_from_node(inv["level"], inv["node"]); month = MS(inv["month"]); b = inv["bucket_from"]; metric = inv["metric"]
    prof = DP.profile(lender, month, b, metric, prod, reg, g=g, recent=1, direction=inv.get("direction"), rank="z"); sl = prof["slices"]; scope = " / ".join(x for x in [prod, reg] if x) or "all products and regions"
    ev, drivers, unexpl = [], [], None
    where = {"lender": lender, **({"product_type": prod} if prod else {}), **({"region": reg} if reg else {})}
    if len(sl):
        top = sl.iloc[0]; dim, val = top["dimension"], str(top["slice"]); spec = {"dimension": dim, "values": [val]}; best = None
        for lag in (0, 3):
            a = attr(month=month, bucket_from=b, metric=metric, product_type=prod, region=reg, recent_months=1, baseline_lag=lag, causes={"driver": spec})
            ex = R.excess_from_cause(a) if a.get("ok") else None
            if ex and (best is None or abs(ex["z"]) > abs(best[1]["z"])): best = (a, ex)
        if best:
            a, ex = best; ev.append(a["attribution_id"])
            filt = f"and product_type='{prod}' " if prod else ""; filt += f"and region='{reg}' " if reg else ""
            if dim in NATIVE: q = sql(f"select {dim} as slice, count(*) as accounts from d1_account_monthly where month_date=date '{month}' and bucket_prev='{b}' {filt}group by 1 order by 2 desc limit 15", f"size of each {DIM_LABEL.get(dim, dim)} group in the pool")
            else: q = sql(f"select month_date, count(*) as accounts from d1_account_monthly where bucket_prev='{b}' {filt}and month_date <= date '{month}' group by 1 order by 1 desc limit 8", "size of the pool in recent months (the slice is a derived band, so its own size is in the attribution call)")
            if q["ok"]: ev.append(q["query_id"])
            conf = "medium" if abs(ex["z"]) >= 3 else "low"
            drivers.append(dict(what=f"movement concentrated in {DIM_LABEL.get(dim, dim)} `{val}` (mechanism not confirmed by an analyst)", where={**where, "sub_slice": f"{DIM_LABEL.get(dim, dim)} `{val}`"},   # slice values go in backticks: they are identifiers (may contain digits), not numbers
                                 when={"start_month": month[:7], "ongoing": None}, category=DIM_CAT.get(dim, "unexplained"),
                                evidence_ids=ev, attribution_id=a["attribution_id"], control_group_note="all other accounts in the same pool and period", observed_shape="unknown", confidence=conf))
            unexpl = "the mechanism behind this concentration is not established: the rule-based investigator locates and quantifies movements but cannot name their cause"
    if not drivers: unexpl = "no slice moved significantly more than its control group; the cause of the alarm is not established"
    clue = f"{DIM_LABEL.get(sl.iloc[0]['dimension'], sl.iloc[0]['dimension'])} `{sl.iloc[0]['slice']}`" if len(sl) else None
    qs = ES.fallback_questions(inv, [clue] if clue else [])
    f = dict(headline=f"{scope} {b} {metric.replace('_', ' ')} moved unusually in {pd.Timestamp(month):%B %Y}", drivers=drivers, rejected_hypotheses=[], unexplained_note=unexpl, escalation_questions=qs)
    errs = det_validate(f, sql, attr)
    if errs: return {"status": "incomplete", "reason": "rule-based findings failed validation: " + "; ".join(errs)}
    return {"status": "complete", "investigation": inv, "findings": DG_final(f, attr), "queries_used": sql.used, "attributions_used": attr.n, "evidence": {**sql.evidence, **attr.evidence}, "run_id": run_id, "source": "rule-based investigator (no LLM)"}
def DG_final(f, attr):
    from detective import finalize; return finalize(f, attr)
# ------------------------------------------------------------------ run context
class Run:
    def __init__(self, cfg: RunConfig):
        self.cfg = cfg; self.L, self.O = cfg.lender, MS(cfg.origin); self.run_id = f"run_{cfg.lender}_{self.O[:7]}_{datetime.datetime.now():%Y%m%d%H%M%S}"
        self.nodes, self.warnings, self.t0 = [], [], time.time(); self.inv, self.results, self.incomplete, self.active, self.cls, self.outputs = [], [], [], [], {}, {}
        self.out = pathlib.Path(cfg.out_root) / "packs" / f"{cfg.lender}_{self.O[:7]}"; self.con = None; self.g = None
        self.trace = Trace(self.run_id, cfg.lender, self.O[:7], root_dir=pathlib.Path(cfg.out_root) / "trace")
    def node(self, name, fn, critical=True, fallback=None):
        t = time.time(); rec = {"node": name, "status": "ok", "secs": None, "error": None}; self.trace.emit("step_start", name, "system", f"start {name}")
        try: fn()
        except Exception as e:
            rec["status"] = "failed" if critical else "degraded"; rec["error"] = f"{type(e).__name__}: {e}"; rec["trace"] = traceback.format_exc(limit=3)
            if not critical:
                self.warnings.append(f"{name}: {rec['error']}")
                if fallback:
                    try: fallback()
                    except Exception as e2: rec["status"] = "failed"; rec["error"] += f" | fallback failed: {type(e2).__name__}: {e2}"
        rec["secs"] = round(time.time() - t, 2); self.nodes.append(rec)
        self.trace.emit("step_end", name, "system", f"{name} {rec['status']}", {"secs": rec["secs"], "status": rec["status"], "error": rec["error"]})
        if rec["status"] == "failed" and critical: raise RuntimeError(f"critical step '{name}' failed: {rec['error']}")
    @property
    def q(self): return lambda s: self.con.sql(s).df()
# ------------------------------------------------------------------ nodes
def build_graph(run: Run):
    cfg, inj = run.cfg, run.cfg.inject
    def checks(state):
        def f():
            rep = dq_checks.run()
            if inj.get("dq_fail"): rep["summary"]["FAIL"] = 1
            run.dq = rep["summary"]
            if rep["summary"]["FAIL"]: raise RuntimeError(f"data checks failed: {[c['check'] for c in rep['checks'] if c['status'] == 'FAIL']}")
        try: run.node("checks", f)
        except RuntimeError: return {"paused": True, "status": "paused: data checks failed"}
        return {"paused": False}
    def prepare(state):
        def f():
            run.con = duckdb.connect(str(DB), read_only=True); run.g = GuardedSQL(run.L, run.O, run_id=run.run_id)
        run.node("prepare", f); return {"stage": "prepare"}
    def detect(state):
        def f():
            d = run.con.sql(f"select * from mart.investigations where month=date '{run.O}' and priority and node like '{run.L}%' order by rank limit {cfg.max_investigations}").df()
            run.inv = d.to_dict("records")
        run.node("detect", f); return {"stage": "detect"}
    def investigate(state):
        def f():
            def work(k, inv):
                if inj.get("investigate_error") == k: raise RuntimeError("injected investigator crash")
                if inj.get("investigate_slow") == k: time.sleep(cfg.investigation_timeout + 5)
                g = run.g.fork(); rid = f"{run.run_id}_i{k}"; off = (k + 1) * 100      # evidence ids are unique across the whole run: investigation k uses Q/A<k+1>01...
                sql = SQLTool(run.L, run.O, run_id=rid, g=g, id_offset=off, trace=run.trace); attr = AttributionTool(run.L, run.O, run_id=rid, g=g, id_offset=off, trace=run.trace)
                if cfg.client is not None: return run_detective(inv, TracedClient(cfg.client, run.trace, f"investigate_i{k}"), run.con.cursor(), sql_tool=sql, attr_tool=attr, run_id=rid)
                return rule_detective(inv, sql, attr, g, rid)
            with ThreadPoolExecutor(max_workers=cfg.workers) as ex:
                futs = [(k, inv, ex.submit(work, k, inv)) for k, inv in enumerate(run.inv)]
                for k, inv, fu in futs:
                    label = f"{inv['node'].replace('|', ' / ')} {inv['bucket_from']} {inv['metric'].replace('_', ' ')}"
                    try: r = fu.result(timeout=cfg.investigation_timeout)
                    except FTimeout: r = {"status": "incomplete", "reason": f"timed out after {cfg.investigation_timeout:.0f}s"}
                    except Exception as e: r = {"status": "incomplete", "reason": f"{type(e).__name__}: {e}"}
                    r["label"] = label; r.setdefault("investigation", inv)
                    if r["status"] != "complete": run.incomplete.append(label); run.warnings.append(f"investigation incomplete: {label} ({r.get('reason')})")
                    run.results.append(r)
                    run.trace.emit("investigation", "investigate", "llm" if cfg.client else "code", f"{label}: {r['status']}", {"label": label, "status": r["status"], "source": r.get("source", "llm" if cfg.client else None), "reason": r.get("reason"), "drivers": [{"what": d["what"], "category": d["category"], "confidence": d["confidence"], "evidence_ids": d["evidence_ids"]} for d in r.get("findings", {}).get("drivers", [])], "unexplained": r.get("findings", {}).get("unexplained_note"), "queries_used": r.get("queries_used")})
        run.node("investigate", f, critical=False); return {"stage": "investigate"}
    def registry(state):
        def f():
            run.attr = AttributionTool(run.L, run.O, run_id=run.run_id + "_reg", g=run.g.fork(), id_offset=900, trace=run.trace); sp = cfg.state_path
            run.recheck = R.recheck_all(run.L, run.O, run.attr, sp, run.run_id)
            for x in run.recheck: run.trace.emit("registry", "registry_classify", "code", f"recheck {x['driver_id']}: {x.get('status')}", x)
            run.reg = []
            for r in run.results:
                if r["status"] != "complete": continue
                res = {**r, "investigation": r["investigation"]}; ev = r["evidence"]; led = {k: v for k, v in ev.items() if k.startswith("A")}
                for did, kind in R.register_from_result(res, led, sp, run.run_id):
                    run.trace.emit("registry", "registry_classify", "code", f"driver {did} {kind}", {"driver_id": did, "event": kind})
                    d = next(x for x in r["findings"]["drivers"] if x.get("attribution_id") in led); run.reg.append((did, kind, d, led[d["attribution_id"]], r))
            c = R._con(sp); run.active = [x[0] for x in c.sql("select driver_id from drivers where lender_id=? and status in ('open','persistent','fading') order by first_seen", params=[run.L]).fetchall()]; c.close()
            for did in run.active:
                try: run.cls[did] = CL.classify_driver(did, run.g.fork(), run.O, client=TracedClient(cfg.client, run.trace, f"classify_{did}") if cfg.client else None, state=sp)
                except Exception as e: run.warnings.append(f"classifier failed for {did} ({e}); using the deterministic prior"); d, o = CL.get_driver(did, sp); run.cls[did] = CL.prior(d, o)
        def f2():
            f()
            for did, c in run.cls.items(): run.trace.emit("classification", "registry_classify", c.get("source", "code") if c.get("source") == "llm" else "code", f"{did}: " + ", ".join(f"{x['name']} {x['weight']:.0%}" for x in c["scenarios"]), {"driver_id": did, "source": c.get("source"), "scenarios": c["scenarios"], "agrees_with_prior": c.get("agrees_with_prior"), "widen_ranges": c.get("widen_ranges"), "rationale": c.get("rationale")})
        run.node("registry_classify", f2, critical=False); return {"stage": "registry_classify"}
    def escalate(state):
        def f():
            disp = ES.Dispatcher(cfg.notifier or ES.FileOutbox(pathlib.Path(cfg.out_root) / "outbox"), state=cfg.state_path)
            for r in run.results:
                if r["status"] == "complete":
                    e = ES.create_from_result(r, disp, cfg.state_path, clues=[])
                    if e: run.trace.emit("escalation", "escalate", "code", f"{e['escalation_id']} {'re-asked' if e.get('deduplicated') else 'opened'}", {k: str(v)[:200] for k, v in e.items() if k != 'questions'} | {"n_questions": len(e.get("questions", []))})
            disp.wait(5)
        run.node("escalate", f, critical=False); return {"stage": "escalate"}
    def forecast(state):
        def f():
            if inj.get("forecast_error"): raise RuntimeError("injected forecast-intervention failure")
            attr = AttributionTool(run.L, run.O, run_id=run.run_id + "_fc", g=run.g.fork(), id_offset=950, trace=run.trace)
            run.fc = IF.forecast_with_interventions(run.L, run.O, run.active, run.con.cursor(), run.g.fork(), attr, classifications=run.cls, state=cfg.state_path, out_dir=pathlib.Path(cfg.out_root) / "forecasts")
            run.trace.emit("forecast_run", "forecast", "code", f"{run.fc['run_id']} ({len(run.active)} intervention(s))", {"forecast_run_id": run.fc["run_id"], "drivers": [d["driver_id"] for d in run.fc["drivers"]], "measured_effect_pp": {d["driver_id"]: d["measured_effect_pp"] for d in run.fc["drivers"]}})
        def fb():
            hist = IF.history(run.con.cursor(), run.O); hist = hist[hist.lender_id == run.L].copy(); hist["month_date"] = pd.to_datetime(hist.month_date); raw = IF.ensemble(run.con.cursor(), run.O, hist)
            run.fc = {"run_id": f"fc_{run.L}_{run.O[:7]}_baseline", "unadjusted": raw, "counterfactual": raw, "lasting": raw, "blip": raw, "adjusted": raw, "drivers": []}; run.active = []; run.cls = {}
        run.node("forecast", f, critical=False, fallback=fb); return {"stage": "forecast"}
    def ranges(state):
        def f():
            wl = np.mean([next((s["weight"] for s in run.cls[d]["scenarios"] if s["shape"] == "STEP"), 0.0) for d in run.active]) if run.active else 1.0
            var = [(run.fc["lasting"], wl), (run.fc["blip"], 1 - wl)] if run.active and 0 < wl < 1 else [(run.fc["adjusted"], 1.0)]
            run.summary, run.sim = RG.ranged_outlook(run.q, run.L, run.O, var, run.con.cursor(), N=cfg.n_sims, seed=7); cal = json.loads((root / "src/range_calibration.json").read_text())
            run.trace.emit("ranges_run", "ranges", "code", f"simulation for {run.fc['run_id']}: {cfg.n_sims} draws", {"forecast_run_id": run.fc["run_id"], "draws": cfg.n_sims, "seed": 7, "lambda": cal["lambda"], "phi": cal["phi"], "scenario_weights": [round(w, 3) for _, w in var]})
        run.node("ranges", f); return {"stage": "ranges"}
    def rollup(state):
        def f():
            run.ru = RU.build_rollup(run.q, run.L, run.O, run.sim)
            top = next((r for r in run.results if r["status"] == "complete"), None); b, m = (top["investigation"]["bucket_from"], top["investigation"]["metric"]) if top else ("31-60", "roll_forward")
            if b == "90+" or (m == "cure" and b == "CURRENT"): b, m = "31-60", "roll_forward"
            run.mv = RU.what_moved(run.q, run.L, run.O, b, m); run.mv_label = f"{b} {m.replace('_', ' ')} rate"
        run.node("rollup", f); return {"stage": "rollup"}
    def charts(state):
        def f():
            if inj.get("charts_error"): raise RuntimeError("injected chart failure")
            q, ru, L, O = run.q, run.ru, run.L, run.O; d = pathlib.Path(cfg.out_root) / "charts" / run.run_id
            def hist(b, m="roll_forward"): x = q(f"select month_date, sum({m}*opening_accounts)/sum(opening_accounts) v from mart.moves_segment where lender_id='{L}' and bucket_from='{b}' and month_date <= date '{O}' group by 1 order by 1"); x["month_date"] = pd.to_datetime(x.month_date); return x.set_index("month_date").v
            def fcr(b, m="roll_forward"): x = ru[(ru.level == "lender") & (ru.metric == f"{m}_{b}")].copy(); x["m"] = pd.Timestamp(O) + x.h.map(lambda h: pd.DateOffset(months=int(h))); return x.set_index("m")
            ev = q(f"select event_start_date d, event_name n from event_calendar where (lender_id is null or lender_id='{L}') and announced_date <= date '{O}' order by 1").values.tolist(); bk = ["CURRENT", "1-30", "31-60", "61-90"]
            bb, mm = run.mv_label.split(" ")[0], "roll_forward"; fb = fcr(bb)
            npa_h = q(f"select month_date, count(*) n from d1_account_monthly where lender_id='{L}' and bucket_curr='90+' and month_date <= date '{O}' group by 1 order by 1"); npa_h["month_date"] = pd.to_datetime(npa_h.month_date); npa_h = npa_h.set_index("month_date").n.tail(18)
            nf = ru[(ru.level == "lender") & (ru.metric == "npa_accounts")].copy(); nf["m"] = pd.Timestamp(O) + nf.h.map(lambda h: pd.DateOffset(months=int(h))); nf = nf.set_index("m")
            raw = IF.pool_metric(run.fc["unadjusted"], run.con.cursor(), {"lender": L, "bucket_from": bb}, mm, O)
            run.charts = {"rate_forecast": CH.rate_forecast(hist(bb).tail(18), raw, fb["p50"], fb[["p10", "p90"]], d / "rate_forecast.png", f"{L.replace('_', ' ').title()}, all products", f"{bb} roll-forward rate", ev),
                          "npa_outlook": CH.npa_outlook(npa_h, nf["p50"], nf[["p10", "p90"]], d / "npa_outlook.png", L.replace("_", " ").title()),
                          "what_moved": CH.what_moved(run.mv[0], run.mv[1], d / "what_moved.png", L.replace("_", " ").title(), run.mv_label, pd.Timestamp(O)),
                          "bucket_panels": CH.bucket_panels({b: hist(b).tail(18) for b in bk}, {b: fcr(b)["p50"] for b in bk}, {b: fcr(b)[["p10", "p90"]] for b in bk}, d / "bucket_panels.png", L.replace("_", " ").title(), "roll-forward rate")}
        run.charts = {}; run.node("charts", f, critical=False); return {"stage": "charts"}
    def pack(state):
        def f():
            drivers = []
            for did, kind, d, led, r in run.reg:
                cz = next((c for c in led["causes"].values() if c.get("status") == "ok"), None); dd, _ = CL.get_driver(did, cfg.state_path); p = r["investigation"]; lender, prod, reg = pool_from_node(p["level"], p["node"])
                drivers.append(dict(driver_id=did, what=d["what"], where=", ".join(x for x in [lender.replace("_", " ").title(), (prod or "").replace("_", " ").title() or None, (reg or "").title() or None, d["where"].get("sub_slice")] if x), start_label=pd.Timestamp(dd["start_month"]).strftime("%B %Y"),
                                    category=d["category"], status=dd["status"], evidence_ids=d["evidence_ids"], attribution_id=d["attribution_id"], observed_change_pp=led["observed_change_pp"], pool_label=f"{lender.replace('_', ' ').title()} {(prod or 'all products').replace('_', ' ').title()} {(reg or 'all regions').title()} {p['bucket_from']} {p['metric'].replace('_', ' ')} rate",
                                    contribution_pp=cz and cz["contribution_pp"], contribution_pp_80=cz and cz["contribution_pp_80"], share_of_change=cz and cz.get("share_of_change"), unexplained_share=led.get("unexplained_share"), control_change_pp=led.get("control_change_pp"),
                                    control_group_note=d["control_group_note"], scenarios=run.cls.get(did, {}).get("scenarios", [{"name": "lasting", "weight": 1.0}])))
            txt = (root / "docs/range_calibration.md").read_text(); covs = [float(x) / 100 for line in txt.split("Calibrated coverage (%):")[1].split("Mean 80%")[0].splitlines() if line.startswith("| npa") for x in line.split("|")[2:5]]
            ev_ids = sorted({i for r in run.results if r["status"] == "complete" for i in r["evidence"] if i[0] in "QA"})
            ctx = dict(lender=run.L, origin=run.O, rollup=run.ru, drivers=drivers, movers=dict(table=run.mv[0], total_pp=run.mv[1], label=run.mv_label, month=run.O, source="mart.moves_segment shift-share"), run_id=run.fc["run_id"], escalations=PA.escalations_for(run.L, cfg.state_path), changes=None,
                       evidence_ids=ev_ids, dq=run.dq, calibration=dict(min_cov=min(covs), max_cov=max(covs)), incomplete=run.incomplete)
            run.pack = PA.build_pack(ctx, cfg.client, out_dir=pathlib.Path(cfg.out_root) / "packs_md")
            led = {}
            for r in run.results:
                if r["status"] == "complete": led.update({k: v for k, v in r["evidence"].items() if k in ev_ids})
            meta = dict(lender=run.L, origin=run.O, run_id=run.fc["run_id"], generated=datetime.date.today().isoformat(), audit={"source": run.pack["source"], "rendered_issues": 0, "run": run.run_id})
            res = DG.generate(run.pack, run.charts, led, meta, run.out); run.outputs = {"pdf": res["pdf"], "md": res["md"], "manifest": res["manifest"]["files"].keys().__len__()}
            run.trace.emit("pack", "pack", "llm" if run.pack["source"] == "llm" else "code", f"pack written by {run.pack['source']} author; {len(run.pack['facts'].f)} facts; numeric audit clean", {"author": run.pack["source"], "facts": len(run.pack["facts"].f), "llm_issues": run.pack["llm_issues"]})
            for name, h in res["manifest"]["files"].items():
                if name in ("pack.pdf", "pack.md", "evidence.json"): run.trace.emit("output", "pack", "code", f"{name} sha256 {h[:12]}", {"file": name, "sha256": h})
        run.node("pack", f); return {"stage": "pack"}
    def finalize(state):
        st = state.get("status") or ("complete" if not run.warnings else "complete_with_warnings")
        return {"status": st}
    g = StateGraph(S)
    for n, fn in [("checks", checks), ("prepare", prepare), ("detect", detect), ("investigate", investigate), ("registry_classify", registry), ("escalate", escalate), ("forecast", forecast), ("ranges", ranges), ("rollup", rollup), ("charts", charts), ("pack", pack), ("finalize", finalize)]: g.add_node(n, fn)
    g.set_entry_point("checks"); g.add_conditional_edges("checks", lambda s: "finalize" if s.get("paused") else "prepare", {"finalize": "finalize", "prepare": "prepare"})
    seq = ["prepare", "detect", "investigate", "registry_classify", "escalate", "forecast", "ranges", "rollup", "charts", "pack", "finalize"]
    for a, b in zip(seq, seq[1:]): g.add_edge(a, b)
    g.add_edge("finalize", END); return g.compile()
def run_lender(cfg: RunConfig):
    run = Run(cfg); status, err = None, None
    _c = duckdb.connect(str(DB), read_only=True); run.trace.emit("run_start", "start", "system", f"run {run.run_id}", {"lender": run.L, "origin": run.O[:7], "code": code_version(), "data": data_fingerprint(_c), "config": {"draws": cfg.n_sims, "max_investigations": cfg.max_investigations, "workers": cfg.workers, "timeout_s": cfg.investigation_timeout, "llm": cfg.client is not None, "injected_faults": list(cfg.inject)}}); _c.close()
    try: out = build_graph(run).invoke({"stage": "start"}); status = out.get("status")
    except Exception as e: status, err = "failed", f"{type(e).__name__}: {e}"
    finally:
        try: run.con and run.con.close()
        except Exception: pass
    run.trace.emit("run_end", "end", "system", f"run finished: {status}", {"status": status, "error": err, "warnings": run.warnings, "total_secs": round(time.time() - run.t0, 1)}); trace_report(run.trace.path, run.trace.path.with_suffix(".report.md"))
    rec = {"trace": str(run.trace.path), "run_id": run.run_id, "lender": run.L, "origin": run.O[:7], "status": status, "error": err, "total_secs": round(time.time() - run.t0, 1), "nodes": run.nodes, "warnings": run.warnings, "incomplete_investigations": run.incomplete,
           "investigations": [{"label": r.get("label"), "status": r["status"], "source": r.get("source", "llm" if cfg.client else None), "reason": r.get("reason")} for r in run.results], "active_drivers": run.active, "outputs": run.outputs}
    d = pathlib.Path(cfg.out_root) / "runs"; d.mkdir(parents=True, exist_ok=True); (d / f"{run.run_id}.json").write_text(json.dumps(rec, indent=1, default=str)); return rec
def prepare(origin):
    """shared, sequential, read-write preparation (all RW connections are closed before any parallel work)."""
    con = duckdb.connect(str(DB)); have = con.sql(f"select count(*) from mart.investigations where month=date '{MS(origin)}'").fetchone()[0]; con.close()
    if not have: detection.run()
    leading_scan.run(as_of=MS(origin))
def run_month(origin, lenders=("LENDER_A", "LENDER_B", "LENDER_C"), **kw):
    prepare(origin); t = time.time()
    with ThreadPoolExecutor(max_workers=len(lenders)) as ex: recs = list(ex.map(lambda L: run_lender(RunConfig(lender=L, origin=origin, **kw)), lenders))
    return recs, round(time.time() - t, 1)
if __name__ == "__main__":
    recs, secs = run_month(sys.argv[1] if len(sys.argv) > 1 else "2025-06-01")
    for r in recs: print(r["lender"], r["status"], f"{r['total_secs']}s", "| warnings:", len(r["warnings"]), "|", r["outputs"].get("pdf"))
    print("wall time:", secs, "s")
