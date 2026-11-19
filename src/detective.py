"""Section 15: Agent 1 - the Root-Cause Detective.
An LLM tool-use loop that investigates ONE investigation (from section 10) by testing hypotheses with control groups.
Tools: run_sql (s13), attribute_change (s14), profile_drift (s12), submit_findings.  Rules enforced in CODE, not just in the prompt:
  * every confirmed driver must cite query/attribution ids that exist in this run's ledgers and name its control group;
  * the attribution numbers in the final output are COPIED from the attribution ledger by code - the model only supplies the id;
  * a malformed submission is bounced back to the model (max 2 retries); running out of turns yields an 'incomplete' result, never a guess.
The LLM client is pluggable: AnthropicClient (live, needs ANTHROPIC_API_KEY) or ScriptedClient (offline tests)."""
import json, os, pathlib, sys, datetime
import pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from sql_tool import SQLTool
from attribution import AttributionTool
root = pathlib.Path(__file__).resolve().parent.parent
MODEL = "claude-sonnet-5-5"
CATEGORIES = ["festival", "lender_process", "regulatory", "operational", "cohort", "macro_shock", "technical_failure", "unexplained"]
SUBMIT = {"name": "submit_findings", "description": "Submit your FINAL findings once. Include every hypothesis you tested. A driver may be marked confirmed only if a control-group test supports it.",
  "input_schema": {"type": "object", "required": ["headline", "drivers", "rejected_hypotheses", "escalation_questions"], "properties": {
    "headline": {"type": "string", "description": "one plain sentence: what moved, where, and the main cause (or that it is unexplained). No numbers you did not get from a tool."},
    "drivers": {"type": "array", "items": {"type": "object", "required": ["what", "where", "when", "category", "evidence_ids", "control_group_note", "confidence"], "properties": {
        "what": {"type": "string", "description": "the mechanism, e.g. 'field visits stopped for EMIs under 10k'"},
        "where": {"type": "object", "properties": {"lender": {"type": "string"}, "product_type": {"type": "string"}, "region": {"type": "string"}, "sub_slice": {"type": "string"}}},
        "when": {"type": "object", "properties": {"start_month": {"type": "string"}, "ongoing": {"type": "boolean"}}},
        "category": {"type": "string", "enum": CATEGORIES}, "evidence_ids": {"type": "array", "items": {"type": "string"}, "description": "query ids (Q..) and attribution ids (A..) you rely on"},
        "attribution_id": {"type": "string", "description": "id of the attribute_change call quantifying this driver; do not write the percentage yourself"},
        "control_group_note": {"type": "string", "description": "which unaffected group you compared against"},
        "observed_shape": {"type": "string", "enum": ["one_month_spike", "fading", "persistent", "unknown"]}, "confidence": {"type": "string", "enum": ["high", "medium", "low"]}}}},
    "rejected_hypotheses": {"type": "array", "items": {"type": "object", "required": ["hypothesis", "why_rejected", "evidence_ids"], "properties": {"hypothesis": {"type": "string"}, "why_rejected": {"type": "string"}, "evidence_ids": {"type": "array", "items": {"type": "string"}}}}},
    "unexplained_note": {"type": "string", "description": "what part of the movement you could not explain"},
    "escalation_questions": {"type": "array", "items": {"type": "string"}, "description": "2-3 concrete questions for the lender's operations team if something is unexplained"}}}}
PROFILE = {"name": "profile_drift", "description": "Rank what changed in a pool between the current window and a baseline: feature drift and slice outcome shifts (cities, agencies, EMI bands, call/visit activity...). Use it to generate hypotheses, then TEST them with run_sql / attribute_change.",
  "input_schema": {"type": "object", "required": ["month", "bucket_from", "metric"], "properties": {"month": {"type": "string"}, "bucket_from": {"type": "string"}, "metric": {"type": "string", "enum": ["roll_forward", "cure"]},
     "product_type": {"type": "string"}, "region": {"type": "string"}, "recent_months": {"type": "integer"}}}}
SYSTEM = """You are the Root-Cause Detective for a collections analytics team. A statistical alarm says a roll-forward or cure rate moved unusually. Your job: find out WHY, or say honestly that it is unexplained.

Think along the collections funnel, in this order, and test each hypothesis:
 1. calendar: festival, fiscal period, regulation, lender policy or process change (event_calendar) - but many real causes are NOT in the calendar, and a calendar event is only a suspect, not a cause;
 2. portfolio mix: new cohort, bureau score, new-to-credit share, ticket size, loan age (MOB), product/region/city mix;
 3. outreach: calls, SMS, WhatsApp, field visits per account; which agency or desk; time of day;
 4. contactability: connect rate, right-party contact, wrong/invalid numbers;
 5. promises and payments: promise-to-pay rate and kept rate, payment failures, gateway timeouts, payment mode, NACH bounce reasons.

Rules:
- Falsify, do not confirm. For every suspect compare AFFECTED accounts with a CONTROL group in the same period (e.g. same product in another region, accounts above the EMI threshold). A cause that also hits the control is probably not the cause.
- Never write a percentage, rate or count that did not come from a tool result. Quantify a driver by calling attribute_change and cite its id; do not do the arithmetic yourself.
- Cite the query/attribution ids behind every claim. Include rejected hypotheses with the evidence that rejected them.
- Causes must be specific (what, where, when, category). If the evidence does not support any cause, report it as unexplained, and write 2-3 concrete questions for the lender's operations team.
- You have a limited query budget; be economical. Finish by calling submit_findings exactly once."""
# ------------------------------------------------ pool + brief
def pool_from_node(level, node):
    p = node.split("|"); lender = p[0]
    prod = reg = None
    if level == "lender_product": prod = p[1]
    elif level == "lender_region": reg = p[1]
    elif level == "segment": prod, reg = p[1], p[2]
    return lender, prod, reg
def build_brief(inv, con):
    lender, prod, reg = pool_from_node(inv["level"], inv["node"]); m = pd.Timestamp(inv["month"]).strftime("%Y-%m-%d")
    q = lambda s: con.sql(s).df()
    li = q(f"select level,node,indicator,round(\"value\",4) \"value\",round(base_mean,4) base_mean,round(z,1) z from mart.leading_indicators where flag and lender_id='{lender}' and month_date=date '{m}' order by abs(z) desc limit 8")
    ev = q(f"select kind,event_name,category,region,product_type,months_hit from mart.forward_scan where lender_id='{lender}' limit 12")
    return (f"INVESTIGATION\n- lender {lender}; product {prod or 'ALL'}; region {reg or 'ALL'}; opening bucket {inv['bucket_from']}; metric {inv['metric']}; month {m}\n"
            f"- alarm: {inv['direction'].upper()} {abs(inv['diff_pp']):.2f} percentage points vs the model's expectation (z={inv['z']:.1f}); detected at level '{inv['level']}' ({inv['via']}); "
            f"~{int(abs(inv['excess_accounts']))} excess accounts.\n\nLEADING INDICATORS that moved this month for this lender (automatic scan; clues only):\n{li.to_string(index=False) if len(li) else '(none)'}\n\n"
            f"CALENDAR / STRUCTURAL EVENTS known for this lender:\n{ev.to_string(index=False) if len(ev) else '(none)'}\n\n"
            f"Start by calling profile_drift for this pool, then test hypotheses with run_sql and quantify with attribute_change. Schema:\n")
# ------------------------------------------------ clients
class AnthropicClient:
    def __init__(self, model=MODEL):
        import anthropic; self.c = anthropic.Anthropic(); self.model = model
    def create(self, system, messages, tools):
        r = self.c.messages.create(model=self.model, max_tokens=4096, system=system, messages=messages, tools=tools)
        return {"stop_reason": r.stop_reason, "content": [b.model_dump() for b in r.content], "usage": {"in": r.usage.input_tokens, "out": r.usage.output_tokens}}
class ScriptedClient:
    """offline deterministic client for tests: replays a list of assistant turns, each a list of content blocks."""
    def __init__(self, turns): self.turns, self.i = turns, 0
    def create(self, system, messages, tools):
        t = self.turns[min(self.i, len(self.turns) - 1)]; self.i += 1
        blocks = [{**b, "id": f"toolu_{self.i}_{k}"} if b["type"] == "tool_use" else b for k, b in enumerate(t)]
        return {"stop_reason": "tool_use" if any(b["type"] == "tool_use" for b in blocks) else "end_turn", "content": blocks, "usage": {"in": 0, "out": 0}}
# ------------------------------------------------ validation + loop
def validate(f, sql, attr):
    errs = []
    for k in ("headline", "drivers", "rejected_hypotheses", "escalation_questions"):
        if k not in f: errs.append(f"missing '{k}'")
    ids = lambda lst: [i for i in lst]
    def known(i): return (i in sql.evidence) or (i in attr.evidence)
    for n, d in enumerate(f.get("drivers", []), 1):
        for k in ("what", "where", "when", "category", "evidence_ids", "control_group_note", "confidence"):
            if not d.get(k): errs.append(f"driver {n}: missing '{k}'")
        if d.get("category") not in CATEGORIES: errs.append(f"driver {n}: category must be one of {CATEGORIES}")
        for i in d.get("evidence_ids", []) + ([d["attribution_id"]] if d.get("attribution_id") else []):
            if not known(i): errs.append(f"driver {n}: evidence id {i} does not exist in this run (use ids returned by tools)")
    for n, h in enumerate(f.get("rejected_hypotheses", []), 1):
        for i in h.get("evidence_ids", []):
            if not known(i): errs.append(f"rejected hypothesis {n}: evidence id {i} does not exist")
    if not f.get("drivers") and not f.get("unexplained_note"): errs.append("no drivers and no unexplained_note: say what could not be explained")
    return errs
def finalize(f, attr):
    """copy attribution numbers from the ledger (the model only supplied the id)."""
    for d in f.get("drivers", []):
        a = attr.evidence.get(d.get("attribution_id", ""))
        if a:
            cause = next((c for c in a["causes"].values() if c.get("status") == "ok"), None)
            d["attribution"] = {"id": a["attribution_id"], "metric": a["metric"], "observed_change_pp": round(a["observed_change_pp"], 2),
                                "contribution_pp": cause and round(cause["contribution_pp"], 2), "contribution_pp_80": cause and [round(x, 2) for x in cause["contribution_pp_80"]],
                                "share_of_change": cause and cause.get("share_of_change") and round(cause["share_of_change"], 2), "unexplained_share": a.get("unexplained_share") and round(a["unexplained_share"], 2),
                                "warnings": a["warnings"]}
    return f
def run_detective(inv, client, con, sql_tool=None, attr_tool=None, max_turns=24, run_id=None, brief=None):
    lender, prod, reg = pool_from_node(inv["level"], inv["node"]); month = pd.Timestamp(inv["month"]).strftime("%Y-%m-%d")
    run_id = run_id or f"det_{lender}_{month}_{abs(hash(inv['node'] + inv['metric'] + inv['bucket_from'])) % 10**6}"
    sql = sql_tool or SQLTool(lender, month, run_id=run_id); attr = attr_tool or AttributionTool(lender, month, run_id=run_id, g=sql.g)
    import drift_profiler as dp
    try:
        import escalations; fu = escalations.followups_text(lender)      # operations' earlier replies = hypotheses to test
    except Exception: fu = ""
    brief = (brief or build_brief(inv, con)) + fu + sql.schema_text()
    tools = [SUBMIT, SQLTool.spec, AttributionTool.spec, PROFILE]; msgs = [{"role": "user", "content": brief}]; trace = []; bounces = 0; usage = [0, 0]
    for turn in range(max_turns):
        r = client.create(SYSTEM, msgs, tools); usage[0] += r["usage"]["in"]; usage[1] += r["usage"]["out"]
        msgs.append({"role": "assistant", "content": r["content"]}); calls = [b for b in r["content"] if b["type"] == "tool_use"]
        for b in r["content"]:
            if b["type"] == "text" and b["text"].strip(): trace.append({"turn": turn, "text": b["text"]})
        if not calls:
            msgs.append({"role": "user", "content": "Continue investigating, or call submit_findings with your findings."}); continue
        results = []
        for c in calls:
            n, a = c["name"], c["input"]
            if n == "run_sql": res = sql(a.get("sql", ""), a.get("purpose", "")); out = sql.as_text(res)
            elif n == "attribute_change":
                try: res = attr(**a); out = json.dumps(res, default=str)[:6000]
                except TypeError as e: out = f"ERROR: bad arguments: {e}"
            elif n == "profile_drift":
                try:
                    p = dp.profile(lender, a["month"], a["bucket_from"], a["metric"], a.get("product_type"), a.get("region"), g=sql.g, recent=a.get("recent_months", 1))
                    out = json.dumps({"features": p["features"].head(8)[["feature", "effect", "direction", "detail"]].round(3).to_dict("records") if len(p["features"]) else [],
                                      "slices": p["slices"].head(8)[["dimension", "slice", "n_T", "rate_base", "rate_T", "did_pp", "z", "excess_accounts"]].round(3).to_dict("records") if len(p["slices"]) else []}, default=str)
                except Exception as e: out = f"ERROR: {str(e).splitlines()[0]}"
            elif n == "submit_findings":
                errs = validate(a, sql, attr)
                if errs and bounces < 2:
                    bounces += 1; out = "REJECTED - fix and resubmit:\n- " + "\n- ".join(errs)
                elif errs:
                    return {"status": "incomplete", "reason": "findings failed validation after retries: " + "; ".join(errs), "trace": trace, "queries_used": sql.used, "usage": usage}
                else:
                    return {"status": "complete", "investigation": inv, "findings": finalize(a, attr), "trace": trace, "queries_used": sql.used, "attributions_used": attr.n,
                            "usage": usage, "evidence": {**sql.evidence, **attr.evidence}, "run_id": run_id}
            else: out = f"ERROR: unknown tool {n}"
            trace.append({"turn": turn, "tool": n, "input": a, "output": out[:1500]}); results.append({"type": "tool_result", "tool_use_id": c["id"], "content": out})
        msgs.append({"role": "user", "content": results})
    return {"status": "incomplete", "reason": f"no valid findings after {max_turns} turns", "trace": trace, "queries_used": sql.used, "usage": usage}
if __name__ == "__main__":
    import duckdb
    if not os.environ.get("ANTHROPIC_API_KEY"): sys.exit("Set ANTHROPIC_API_KEY to run the live Detective (offline tests: tests/test_detective.py).")
    con = duckdb.connect(str(root / "rollrate.duckdb"), read_only=True)
    inv = con.sql("select * from mart.investigations where priority order by month desc, rank limit 1").df().iloc[0].to_dict()
    res = run_detective(inv, AnthropicClient(), con); print(json.dumps({k: v for k, v in res.items() if k not in ("evidence", "trace")}, indent=1, default=str))
