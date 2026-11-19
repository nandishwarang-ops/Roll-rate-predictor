"""Section 18: Agent 2 - Regime Classifier and scenario builder.
Decides the SHAPE of each driver's effect going forward (never its size - the forecasting tool measures that, section 19):
  DOT       one-off blip, gone next month             TRANSIENT  fades with a half-life (or ends on a known date)
  STEP      lasting level shift (optionally lagged, e.g. a cohort that seasons in over 2-4 months)
With only one month of evidence (registry status 'open') nobody can know which, so it emits TWO weighted scenarios (blip vs lasting);
once the registry confirms or closes the driver, the weights collapse to 1.0 / 0.
Two paths, same output contract:  (1) deterministic PRIOR (rules below, always available, the default and the fallback);
(2) LLM path (tool-use, needs ANTHROPIC_API_KEY) that may deviate from the prior only with a stated reason and cited evidence; code validates the result.
Output = an intervention spec consumed by the forecasting tool."""
import json, math, pathlib, sys, datetime
import numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import driver_registry as R
root = pathlib.Path(__file__).resolve().parent.parent
SHAPES = ["DOT", "TRANSIENT", "STEP"]
# P(lasting) for a driver seen once, by category and whether it is ongoing / has a known end
PRIOR_LASTING = {"festival": 0.03, "technical_failure": 0.15, "macro_shock": 0.30, "operational": 0.60, "lender_process": 0.80, "regulatory": 0.85, "cohort": 0.85, "unexplained": 0.60}
LAG = {"cohort": 3}          # months before the effect fully shows
def clip(w): return float(min(0.95, max(0.05, w)))
def months_after(m, k): m = R.M(m); y, mo = divmod(m.month - 1 + k, 12); return datetime.date(m.year + y, mo + 1, 1)
def get_driver(driver_id, state=None):
    c = R._con(state); d = c.sql("select driver_id, lender_id, category, what, where_json, slice_spec, first_seen, start_month, last_seen, status, n_obs, excess_first from drivers where driver_id=?", params=[driver_id]).fetchone()
    o = c.sql("select month_date, excess_pp, z from driver_obs where driver_id=? order by 1", params=[driver_id]).df(); c.close()
    cols = ["driver_id", "lender_id", "category", "what", "where_json", "slice_spec", "first_seen", "start_month", "last_seen", "status", "n_obs", "excess_first"]
    return dict(zip(cols, d)), o
def calendar_match(g, driver):
    """best event_calendar entry for this driver (start within +-1 month, same category family, word overlap) -> dict or None."""
    cat = {"festival": ["FESTIVAL", "FISCAL_PERIOD"], "lender_process": ["LENDER_PROCESS"], "regulatory": ["REGULATORY_POLICY"], "macro_shock": ["MACRO_SHOCK"]}.get(driver["category"])
    if not cat: return None
    ev = g.query("select event_name, event_category, event_start_date, event_end_date, description from event_calendar", max_rows=500); best, bs = None, 0
    words = {w for w in R.tokens({"w": driver["what"]})}
    for e in ev.itertuples():
        if e.event_category not in cat or abs(R.months_between(e.event_start_date, driver["start_month"])) > 1: continue
        sc = len(words & R.tokens({"w": f"{e.event_name} {e.description}"}))
        if sc > bs: best, bs = e, sc
    if not best: return None
    end = None if pd.isna(best.event_end_date) else R.M(best.event_end_date)
    return {"event_name": best.event_name, "start": R.M(best.event_start_date), "end": end, "permanent": end is None, "overlap_words": bs}
def half_life(excess_first, obs):
    """per-month retention from the registry history -> half-life in months, clipped to [0.5, 6]."""
    if len(obs) < 2 or not excess_first: return 2.0
    ratio = max(obs.excess_pp.iloc[-1] / excess_first, 0.02); k = max(R.months_between(obs.month_date.iloc[0], obs.month_date.iloc[-1]), 1)
    r = ratio ** (1 / k)
    return 6.0 if r >= 0.99 else float(min(6.0, max(0.5, math.log(0.5) / math.log(r))))
# ------------------------------------------------------------ recovery check (within-month timing proxy)
def recovery_check(g, driver, month):
    """effect (excess over control, pp) split by EMI due-day group - a proxy for early vs late in the month. 'no_recovery' = the effect is as large late as early."""
    import drift_profiler as dp
    s = json.loads(driver["slice_spec"]); p = s["pool"]; lag = max(0, R.months_between(driver["start_month"], month))
    df = dp.pull(g, str(R.M(month)), p["bucket_from"], p["product_type"], p["region"], 6, lag, 1); y = p["metric"]
    inside = df[dp._mask(df, s["cause"])] if hasattr(dp, "_mask") else None
    from attribution import _mask
    m = _mask(df, s["cause"]); ctl = ~m if not s["control"] else _mask(df, s["control"]); out = {}
    for name, days in {"early_due_days_2_5_7": ["2", "5", "7"], "mid_due_day_10": ["10"], "late_due_day_15": ["15"]}.items():
        sel = df.emi_due_day.isin(days); cur = df.is_T
        a1, a0, c1, c0 = (df[sel & m & cur][y], df[sel & m & ~cur][y], df[sel & ctl & cur][y], df[sel & ctl & ~cur][y])
        out[name] = round(float(100 * ((a1.mean() - a0.mean()) - (c1.mean() - c0.mean()))), 2) if min(len(a1), len(a0), len(c1), len(c0)) >= 30 else None
    vals = [v for v in out.values() if v is not None]; trend = "insufficient_data"
    if len(vals) >= 2 and out.get("early_due_days_2_5_7") is not None and out.get("late_due_day_15") is not None:
        e, l = out["early_due_days_2_5_7"], out["late_due_day_15"]; trend = "recovering" if e > 0 and l < 0.4 * e else "no_recovery"
    return {"effect_pp_by_group": out, "trend": trend, "note": "due-day groups are a proxy for timing within the month"}
# ------------------------------------------------------------ deterministic prior
def prior(driver, obs, calendar=None, recovery=None, ongoing=None):
    st, cat = driver["status"], driver["category"]; start = R.M(driver["start_month"]); first = R.M(driver["first_seen"]); lag = LAG.get(cat, 0); why = []
    def spec(scen, conf, widen=False): return {"driver_id": driver["driver_id"], "lender": driver["lender_id"], "category": cat, "registry_status": st, "scenarios": scen, "widen_ranges": widen,
                                                 "confidence": conf, "rationale": " ".join(why), "source": "prior"}
    if st == "persistent":
        why.append(f"Registry confirmed the effect persisted ({driver['n_obs']} observations): lasting level shift.")
        return spec([dict(name="lasting", shape="STEP", weight=1.0, start_month=str(start), lag_months=lag)], "high")
    if st == "closed_transient":
        why.append("Registry closed this driver: the effect is gone, so no forward intervention."); return spec([dict(name="blip", shape="DOT", weight=1.0, start_month=str(start), active=False)], "high")
    if st == "closed_reverted":
        why.append("A persistent driver reverted for two months running: closed, no forward intervention."); return spec([dict(name="reverted", shape="DOT", weight=1.0, start_month=str(start), active=False)], "high")
    if st == "fading":
        hl = half_life(driver["excess_first"], obs); why.append(f"Effect still present but shrinking; observed retention implies a half-life of about {hl:.1f} months.")
        return spec([dict(name="fading", shape="TRANSIENT", weight=1.0, start_month=str(start), half_life_months=round(hl, 1))], "medium")
    # open: one observation -> two scenarios
    p = PRIOR_LASTING.get(cat, 0.6); widen = cat == "unexplained"
    if calendar and calendar["end"]:
        end = calendar["end"]; why.append(f"Calendar event '{calendar['event_name']}' has a known end ({end:%b %Y}): transient until then."); p = 0.05
        scen = [dict(name="until_event_end", shape="TRANSIENT", weight=1 - p, start_month=str(start), end_month=str(end), half_life_months=None),
                dict(name="lasting", shape="STEP", weight=p, start_month=str(start), lag_months=lag)]
        return spec(scen, "medium")
    if calendar and calendar["permanent"]: p = max(p, 0.85); why.append(f"Calendar event '{calendar['event_name']}' has no end date: more likely lasting.")
    elif ongoing is True: p = max(p, 0.70); why.append("Detective reports the cause is ongoing at the end of the month.")
    elif ongoing is False: p = min(p, 0.30); why.append("Detective reports the cause had stopped by the end of the month.")
    if recovery:
        if recovery["trend"] == "no_recovery": p += 0.10; why.append("No recovery within the month (effect as large for late due dates).")
        elif recovery["trend"] == "recovering": p -= 0.20; why.append("Effect shrinks for later due dates, suggesting recovery inside the month.")
    if not why: why.append(f"Base rate for a '{cat}' driver seen once.")
    if widen: why.append("Cause unexplained: lasting is used as the cautious default and ranges are widened.")
    p = clip(p); why.append(f"Only one month of evidence, so two scenarios: lasting {p:.0%}, blip {1-p:.0%}; next month's re-check decides.")
    first_shape = "TRANSIENT" if cat in ("festival", "macro_shock") else "DOT"
    return spec([dict(name="lasting", shape="STEP", weight=round(p, 3), start_month=str(start), lag_months=lag), dict(name="blip", shape=first_shape, weight=round(1 - p, 3), start_month=str(start), **({"half_life_months": 1.0} if first_shape == "TRANSIENT" else {}))],
                "medium" if not widen else "low", widen)
# ------------------------------------------------------------ validation + LLM path
def validate(spec, sql=None):
    errs = []; sc = spec.get("scenarios") or []
    if not sc: return ["no scenarios"]
    if abs(sum(s.get("weight", 0) for s in sc) - 1) > 0.011: errs.append("scenario weights must sum to 1")
    for s in sc:
        if s.get("shape") not in SHAPES: errs.append(f"shape must be one of {SHAPES}")
        if s.get("shape") == "TRANSIENT" and not (s.get("half_life_months") or s.get("end_month")): errs.append("TRANSIENT needs half_life_months or end_month")
        if s.get("shape") == "STEP" and not 0 <= (s.get("lag_months") or 0) <= 6: errs.append("lag_months must be 0-6")
        if s.get("half_life_months") is not None and not 0.5 <= s["half_life_months"] <= 6: errs.append("half_life_months must be 0.5-6")
    if len(sc) > 2: errs.append("at most two scenarios")
    if not spec.get("rationale"): errs.append("rationale required")
    return errs
SUBMIT = {"name": "submit_classification", "description": "Submit the final scenario set for this driver. Shapes only - never the size of the effect.",
  "input_schema": {"type": "object", "required": ["scenarios", "rationale", "confidence"], "properties": {
    "scenarios": {"type": "array", "items": {"type": "object", "required": ["name", "shape", "weight", "start_month"], "properties": {"name": {"type": "string"}, "shape": {"type": "string", "enum": SHAPES},
        "weight": {"type": "number"}, "start_month": {"type": "string"}, "half_life_months": {"type": "number"}, "end_month": {"type": "string"}, "lag_months": {"type": "integer"}}}},
    "rationale": {"type": "string"}, "confidence": {"type": "string", "enum": ["high", "medium", "low"]}, "widen_ranges": {"type": "boolean"},
    "deviation_reason": {"type": "string", "description": "REQUIRED if your dominant scenario differs from the prior's; cite evidence ids"}, "evidence_ids": {"type": "array", "items": {"type": "string"}}}}}
RECOVERY = {"name": "recovery_check", "description": "Effect of this driver split by EMI due-day group (proxy for early vs late in the month): tells whether the effect recovered within the month.", "input_schema": {"type": "object", "properties": {}}}
SYSTEM = """You are the Regime Classifier. A root-cause driver has been found. Decide how its effect will BEHAVE over the next 3 months: DOT (one-off blip), TRANSIENT (fades, with a half-life or a known end date) or STEP (lasting; optionally lagged).
You decide the SHAPE and the scenario WEIGHTS only; the size of the effect is measured elsewhere - never write a rate or a percentage effect.
With only one month of evidence, give two scenarios (lasting vs blip) with weights, and say what next month's data would settle. A policy with no end date points to lasting; a festival or an outage points to transient; a cohort effect is lasting and lagged.
You are given a deterministic PRIOR. Accept it unless the evidence argues otherwise; if your dominant scenario differs, you must give deviation_reason and cite evidence ids (run_sql or recovery_check results). Finish with submit_classification."""
def classify_driver(driver_id, g, month, client=None, state=None, ongoing=None, sql_tool=None, max_turns=8):
    driver, obs = get_driver(driver_id, state); cal = calendar_match(g, driver) if driver["status"] == "open" else None
    rec = recovery_check(g, driver, month) if driver["status"] == "open" else None
    base = prior(driver, obs, cal, rec, ongoing); base["calendar_match"] = cal and {k: str(v) for k, v in cal.items()}; base["recovery_check"] = rec
    if client is None or driver["status"] != "open": return base           # only the genuinely uncertain case needs judgment; confirmed/closed are rule-decided
    from sql_tool import SQLTool
    sql = sql_tool or SQLTool(driver["lender_id"], month, run_id=f"cls_{driver_id}", g=g); msgs = [{"role": "user", "content": "DRIVER\n" + json.dumps({k: str(v) for k, v in driver.items() if k != "slice_spec"}) + "\n\nPRIOR\n" + json.dumps(base, default=str) + "\n\nSchema:\n" + sql.schema_text()}]
    tools = [SUBMIT, RECOVERY, sql.spec]; bounces = 0
    for _ in range(max_turns):
        r = client.create(SYSTEM, msgs, tools); msgs.append({"role": "assistant", "content": r["content"]}); calls = [b for b in r["content"] if b["type"] == "tool_use"]
        if not calls: msgs.append({"role": "user", "content": "Call submit_classification."}); continue
        results = []
        for c in calls:
            n, a = c["name"], c["input"]
            if n == "recovery_check": out = json.dumps(rec)
            elif n == "run_sql": out = sql.as_text(sql(a.get("sql", ""), a.get("purpose", "")))
            elif n == "submit_classification":
                spec = {**base, **a, "source": "llm", "driver_id": driver_id, "lender": driver["lender_id"], "category": driver["category"], "registry_status": driver["status"]}
                errs = validate(spec); top = lambda s: max(s["scenarios"], key=lambda x: x["weight"])["shape"]; spec["agrees_with_prior"] = top(spec) == top(base)
                if not spec["agrees_with_prior"] and not a.get("deviation_reason"): errs.append("dominant scenario differs from the prior: deviation_reason with evidence ids is required")
                if errs and bounces < 2: bounces += 1; out = "REJECTED - fix and resubmit:\n- " + "\n- ".join(errs)
                elif errs: base["llm_rejected"] = errs; return base            # fall back to the prior, never to an invalid LLM answer
                else: return spec
            else: out = f"ERROR: unknown tool {n}"
            results.append({"type": "tool_result", "tool_use_id": c["id"], "content": out})
        msgs.append({"role": "user", "content": results})
    base["llm_rejected"] = ["no valid submission"]; return base
