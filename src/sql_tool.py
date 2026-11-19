"""Section 13: the read-only SQL tool the agents call (Anthropic tool-use format).
Wraps the lender-locked, time-locked sandbox (section 5) and adds what an LLM needs:
  * a tool spec + an auto-generated schema description built from the sandbox itself (so the agent only sees columns that exist),
  * errors returned AS TOOL RESULTS (never exceptions) so the agent can fix its query,
  * row cap, query timeout, per-run query budget, result de-duplication cache,
  * an EVIDENCE LEDGER: every query gets an id (Q001...) that the agents cite next to each claim; each is also appended to
    outputs/audit/<run_id>.jsonl (the audit trail, section 27 extends it)."""
import json, pathlib, threading, hashlib, datetime, sys, re
import pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from guarded_sql import GuardedSQL, Blocked
root = pathlib.Path(__file__).resolve().parent.parent
HINTS = """Grain and meaning:
- Every table is already restricted to ONE lender and to months up to the run's cutoff; you cannot see other lenders or later months.
- month_date is the first day of the month. d1_account_monthly has one row per account per month.
- bucket_prev = opening bucket of the month, bucket_curr = closing bucket. Buckets, mildest to worst: CURRENT, 1-30, 31-60, 61-90, 90+; exits: CLOSED, WRITTEN_OFF; NEW = disbursed this month.
- roll-forward = closing bucket is worse than opening bucket (and not CLOSED/WRITTEN_OFF); cure = closing bucket is better.
- d3_collection_events is one row per outreach or payment event (channel: VOICE_CALL, SMS, WHATSAPP, FIELD_VISIT, FIELD_COLLECTION, LEGAL_NOTICE, PAYMENT). Join to d1 on account_id AND month_date.
- bucket_flow_history = counts of accounts moving bucket_from -> bucket_to by lender/product/region/month. transitions_segment, moves_segment hold ready-made rates.
- event_calendar lists known events; an absent event does NOT mean nothing happened. Many causes are not in it.
- Prove a cause with a CONTROL GROUP (same period, unaffected accounts), not by a single before/after number."""
SPEC = {"name": "run_sql", "description": "Run ONE read-only SQL SELECT (DuckDB dialect) against this run's collections data and return the rows. "
        "Use it to test hypotheses with control groups. Data is limited to the current lender and cutoff month. Returns a query_id (e.g. Q003) - cite it for every number you report.",
        "input_schema": {"type": "object", "properties": {"sql": {"type": "string", "description": "A single SELECT or WITH ... SELECT statement. Aggregate in SQL; results are capped."},
                                                           "purpose": {"type": "string", "description": "One line: which hypothesis or number this query tests."}}, "required": ["sql", "purpose"]}}
class SQLTool:
    def __init__(self, lender_id, as_of, run_id="run", budget=40, max_rows=100, timeout_s=20, g=None, audit_dir=root / "outputs/audit"):
        self.g = g or GuardedSQL(lender_id, as_of, run_id=run_id); self.run_id, self.budget, self.max_rows, self.timeout_s = run_id, budget, max_rows, timeout_s
        self.used, self.evidence, self._cache = 0, {}, {}
        audit_dir.mkdir(parents=True, exist_ok=True); self.audit_path = audit_dir / f"{run_id}.jsonl"
    spec = SPEC
    def schema_text(self):
        cat = json.loads((root / "docs/column_catalogue.json").read_text())["tables"]; out = [HINTS, "", "Tables:"]
        for (t,) in self.g.con.sql("select table_name from duckdb_tables() order by 1").fetchall():
            cols = []
            for c, ty, *_ in self.g.con.sql(f"describe {t}").fetchall():
                v = cat.get(t, {}).get("columns", {}).get(c, {}).get("values")
                note = f" [{', '.join(list(v)[:10])}]" if v and c not in ("agency_id", "month_date") and len(v) <= 12 else ""
                cols.append(f"{c} {ty.lower()}{note}")
            n = self.g.con.sql(f"select count(*) from {t}").fetchone()[0]; out.append(f"- {t} ({n:,} rows): " + "; ".join(cols))
        return "\n".join(out)
    def _log(self, rec):
        with open(self.audit_path, "a") as f: f.write(json.dumps(rec, default=str) + "\n")
    def __call__(self, sql, purpose=""):
        """Returns a dict the agent loop serialises back to the model. Never raises."""
        key = hashlib.sha1(re.sub(r"\s+", " ", sql.strip().rstrip(";")).lower().encode()).hexdigest()
        if key in self._cache: return {**self._cache[key], "note": "identical query already run; cached result"}
        if self.used >= self.budget: return {"ok": False, "error": f"query budget of {self.budget} used up; stop investigating and report what you have"}
        self.used += 1; qid = f"Q{self.used:03d}"; ts = datetime.datetime.now().isoformat(timespec="seconds")
        base = {"query_id": qid, "remaining_budget": self.budget - self.used}
        if len(sql) > 4000: res = {"ok": False, "error": "query too long (max 4000 characters)"}
        else:
            timer = threading.Timer(self.timeout_s, self.g.con.interrupt); timer.start()
            try:
                df = self.g.query(sql, max_rows=self.max_rows + 1); timer.cancel()
                trunc = len(df) > self.max_rows; df = df.head(self.max_rows)
                rows = [[_fmt(v) for v in r] for r in df.itertuples(index=False)]
                res = {"ok": True, "columns": list(df.columns), "rows": rows, "row_count": len(rows), "truncated": trunc}
                if trunc: res["note"] = f"truncated to {self.max_rows} rows; aggregate or add LIMIT/ORDER BY"
            except Blocked as e:
                timer.cancel(); msg = str(e)
                res = {"ok": False, "error": "query exceeded the time limit; simplify or aggregate" if "interrupt" in msg.lower() else msg}
        res = {**base, **res}
        self.evidence[qid] = {"sql": sql, "purpose": purpose, "ts": ts, "ok": res["ok"], "result": {k: res.get(k) for k in ("columns", "rows", "row_count", "error")}}
        self._log({"run_id": self.run_id, "query_id": qid, "ts": ts, "lender": self.g.lender_id, "as_of": self.g.as_of, "purpose": purpose, "sql": sql,
                   "ok": res["ok"], "row_count": res.get("row_count"), "error": res.get("error")})
        if res["ok"]: self._cache[key] = res
        return res
    def as_text(self, res):
        """compact text rendering for the model."""
        if not res["ok"]: return f"[{res.get('query_id','-')}] ERROR: {res['error']}  (budget left: {res.get('remaining_budget','?')})"
        head = f"[{res['query_id']}] {res['row_count']} rows" + (" (truncated)" if res["truncated"] else "") + f"  (budget left: {res['remaining_budget']})"
        return "\n".join([head, " | ".join(res["columns"])] + [" | ".join(str(v) for v in r) for r in res["rows"]])
    def cite(self, qid):
        e = self.evidence[qid]; return f"{qid}: {e['purpose']}\n{e['sql']}"
def _fmt(v):
    if v is None or (isinstance(v, float) and v != v): return None
    if isinstance(v, float): return float(f"{v:.4g}")
    if hasattr(v, "isoformat"): return str(v)[:10]
    return v.item() if hasattr(v, "item") else v
