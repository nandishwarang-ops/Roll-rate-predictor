"""Section 27: audit trace and logging.
One append-only, HASH-CHAINED JSONL file per run (outputs/trace/<run_id>.jsonl). Every event carries seq, timestamp, step, actor (code | llm | human | system), type, a short summary,
a redacted payload and  hash = sha256(prev_hash + canonical event)  so any edit, deletion or reordering is detectable (verify_chain names the first bad event).
What is logged: data fingerprint + code version at run start; every SQL query (allowed or rejected) with a result hash; every attribution call; every LLM call (model, token counts, prompt hash,
tools requested); step timings and failures; investigation outcomes; registry transitions; classifier decisions; escalations; forecast and simulation runs (ids, seeds, calibration); pack audit result;
hashes of every output file.  What is NOT logged: raw prompts and full result sets (sizes + hashes only; full text lives in the evidence ledger of the pack), secrets (redacted on write).
explain_fact() walks from a number in the pack back to its source events; report() renders the human-readable audit summary."""
import json, hashlib, pathlib, re, threading, time, datetime, subprocess, sys, zipfile
root = pathlib.Path(__file__).resolve().parent.parent
SECRET_KEY = re.compile(r"(token|secret|password|api[_-]?key|authorization)", re.I)
SECRET_VAL = re.compile(r"(github_pat_[A-Za-z0-9_]{20,}|sk-ant-[A-Za-z0-9_-]{10,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})")
def redact(x):
    if isinstance(x, dict): return {k: ("[REDACTED]" if SECRET_KEY.search(str(k)) else redact(v)) for k, v in x.items()}
    if isinstance(x, (list, tuple)): return [redact(v) for v in x]
    if isinstance(x, str): return SECRET_VAL.sub("[REDACTED]", x)
    return x
def canon(o): return json.dumps(o, sort_keys=True, separators=(",", ":"), default=str)
def sha(x): return hashlib.sha256((x if isinstance(x, bytes) else str(x).encode())).hexdigest()
GENESIS = "0" * 64
class Trace:
    def __init__(self, run_id, lender=None, origin=None, root_dir=None):
        self.run_id, self.lender, self.origin = run_id, lender, origin; d = pathlib.Path(root_dir or root / "outputs/trace"); d.mkdir(parents=True, exist_ok=True)
        self.path = d / f"{run_id}.jsonl"; self.lock = threading.Lock(); self.seq = 0; self.prev = GENESIS
        if self.path.exists(): self.path.unlink()
    def emit(self, type, step, actor, summary, payload=None, ref=None):
        """append one event; returns its id (e.g. 'e0042')."""
        with self.lock:
            self.seq += 1; ev = {"seq": self.seq, "id": f"e{self.seq:04d}", "ts": datetime.datetime.now().isoformat(timespec="milliseconds"), "run_id": self.run_id, "lender": self.lender, "step": step, "actor": actor, "type": type,
                                 "summary": redact(str(summary))[:300], "payload": redact(payload or {}), "ref": ref}
            ev["prev"] = self.prev; ev["hash"] = sha(self.prev + canon({k: v for k, v in ev.items() if k != "hash"})); self.prev = ev["hash"]
            with open(self.path, "a") as f: f.write(json.dumps(ev, default=str) + "\n")
            return ev["id"]
    def step(self, name):
        tr = self
        class _S:
            def __enter__(s): s.t = time.time(); tr.emit("step_start", name, "system", f"start {name}"); return s
            def __exit__(s, et, ev, tb): tr.emit("step_end", name, "system", f"{name} {'failed' if et else 'ok'}", {"secs": round(time.time() - s.t, 2), "error": f"{et.__name__}: {ev}" if et else None}); return False
        return _S()
class TracedClient:
    """wraps any LLM client (Anthropic or scripted): logs model, sizes, hashes and token counts for every call - never the prompt text."""
    def __init__(self, inner, trace, step): self.inner, self.trace, self.step, self.n = inner, trace, step, 0
    def create(self, system, messages, tools):
        t = time.time(); r = self.inner.create(system, messages, tools); self.n += 1
        self.trace.emit("llm_call", self.step, "llm", f"{getattr(self.inner, 'model', type(self.inner).__name__)} call {self.n}", {"model": getattr(self.inner, "model", type(self.inner).__name__), "system_sha": sha(system)[:16], "n_messages": len(messages),
                        "last_message_sha": sha(canon(messages[-1]))[:16], "tools_offered": [x["name"] for x in tools], "tool_calls": [b["name"] for b in r["content"] if b["type"] == "tool_use"], "stop_reason": r["stop_reason"], "tokens": r["usage"], "secs": round(time.time() - t, 2)})
        return r
    def __getattr__(self, k): return getattr(self.inner, k)
# ------------------------------------------------------------------ run-start fingerprints
def code_version():
    try:
        h = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10).stdout.strip(); dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "src"], cwd=root, capture_output=True, text=True, timeout=10).stdout.strip())
    except Exception: h, dirty = "unknown", None
    import importlib.metadata as m; libs = {k: m.version(k) for k in ("duckdb", "pandas", "statsmodels", "scikit-learn", "numpy", "langgraph") if k}
    return {"git_commit": h, "src_uncommitted_changes": dirty, "python": sys.version.split()[0], "libraries": libs}
def data_fingerprint(con):
    """cheap, stable fingerprint of what the run could see: row counts and month range per table (not a hash of 700 MB)."""
    fp = {}
    for t in ["d1_account_monthly", "d3_collection_events", "bucket_flow_history", "event_calendar"]:
        n, lo, hi = con.sql(f"select count(*), min(month_date), max(month_date) from {t}").fetchone() if t != "event_calendar" else (*con.sql("select count(*) from event_calendar").fetchone(), None, None)
        fp[t] = {"rows": int(n), "first_month": str(lo)[:7] if lo else None, "last_month": str(hi)[:7] if hi else None}
    fp["fingerprint"] = sha(canon(fp))[:16]; return fp
# ------------------------------------------------------------------ verify / read / explain / report
def load(path): return [json.loads(l) for l in open(path) if l.strip()]
def verify_chain(path):
    """-> (ok, first_bad_seq or None, message). Recomputes every hash from the genesis value."""
    prev = GENESIS; seqs = []
    for i, line in enumerate(open(path), 1):
        ev = json.loads(line)
        if ev["seq"] != i: return False, ev["seq"], f"event {i}: sequence number {ev['seq']} (events missing, duplicated or reordered)"
        if ev["prev"] != prev: return False, ev["seq"], f"event {i}: chain link broken"
        if sha(prev + canon({k: v for k, v in ev.items() if k != "hash"})) != ev["hash"]: return False, ev["seq"], f"event {i}: content altered"
        prev = ev["hash"]
    return True, None, f"{i} events, chain intact"
def explain_fact(trace_path, facts_json, fact_id):
    """lineage of one pack number: the fact, its stated source, and the trace events behind it."""
    facts = {f["id"]: f for f in json.load(open(facts_json))}; f = facts[fact_id]; ev = load(trace_path); src = f["source"]; out = {"fact": f, "events": []}
    start = next((e for e in ev if e["type"] == "run_start"), None); find = lambda **kw: [e for e in ev if all(e["payload"].get(k) == v or e.get(k) == v for k, v in kw.items())]
    m = re.match(r"^(A\d{3})", src)
    if m:
        for e in ev:
            if e["type"] == "attribution" and e["payload"].get("attribution_id") == m.group(1):
                out["events"].append(e)
                for qid in e["payload"].get("sibling_query_ids", []): out["events"] += [x for x in ev if x["type"] == "query" and x["payload"].get("query_id") == qid and x["payload"].get("tool_run") == e["payload"].get("tool_run")]
    elif src.startswith("simulation") or "sim" in src.lower():
        rid = re.search(r"(fc_\w+)", src); out["events"] += [e for e in ev if e["type"] in ("forecast_run", "ranges_run") and (not rid or rid.group(1) in canon(e["payload"]))]
    elif src.startswith("classifier"): out["events"] += [e for e in ev if e["type"] == "classification" and e["payload"].get("driver_id") in src]
    elif src.startswith("escalation"): out["events"] += [e for e in ev if e["type"] == "escalation"]
    elif src.startswith(("D1", "mart.")): out["events"] += [e for e in ev if e["type"] == "run_start"]
    if start and start not in out["events"]: out["events"].append(start)
    return out
def report(trace_path, out_path=None):
    ev = load(trace_path); ok, bad, msg = verify_chain(trace_path); st = next(e for e in ev if e["type"] == "run_start"); en = next((e for e in reversed(ev) if e["type"] == "run_end"), None)
    q = [e for e in ev if e["type"] == "query"]; steps = [e for e in ev if e["type"] == "step_end"]; llm = [e for e in ev if e["type"] == "llm_call"]; fails = [e for e in ev if e["type"] == "step_end" and e["payload"].get("error")]
    L = [f"# Audit report: {st['run_id']}", "", f"- Chain integrity: **{'intact' if ok else 'BROKEN at event ' + str(bad)}** ({msg})", f"- Lender / cut-off: {st['payload'].get('lender')} / {st['payload'].get('origin')}", f"- Code: commit {st['payload']['code']['git_commit'][:10]}, uncommitted src changes: {st['payload']['code']['src_uncommitted_changes']}",
         f"- Data fingerprint: {st['payload']['data']['fingerprint']}", f"- Outcome: {en['payload'].get('status') if en else 'run did not finish'}", f"- Events: {len(ev)}; SQL queries: {len(q)} ({sum(not e['payload'].get('ok') for e in q)} rejected or failed); LLM calls: {len(llm)} ({sum((e['payload'].get('tokens') or {}).get('in', 0) + (e['payload'].get('tokens') or {}).get('out', 0) for e in llm)} tokens)", "", "## Steps", "", "| Step | Result | Seconds |", "|---|---|---|"]
    L += [f"| {e['step']} | {'FAILED: ' + e['payload']['error'] if e['payload'].get('error') else 'ok'} | {e['payload']['secs']} |" for e in steps]
    for title, t in [("Investigations", "investigation"), ("Registry changes", "registry"), ("Classifier decisions", "classification"), ("Escalations", "escalation"), ("Forecast and simulation runs", None), ("Outputs", "output")]:
        sel = [e for e in ev if e["type"] in (("forecast_run", "ranges_run") if t is None else (t,))]
        if sel: L += ["", f"## {title}", ""] + [f"- [{e['id']}] {e['summary']}" for e in sel]
    bl = [e for e in q if not e["payload"].get("ok")]
    if bl: L += ["", "## Rejected or failed queries", ""] + [f"- [{e['id']}] {e['payload'].get('query_id')}: {e['payload'].get('error')}" for e in bl]
    txt = "\n".join(L); 
    if out_path: pathlib.Path(out_path).write_text(txt)
    return txt
def export_bundle(trace_path, pack_dir, out_zip):
    """everything an auditor needs in one zip: trace, human report, pack files, evidence ledger, manifest."""
    pack_dir = pathlib.Path(pack_dir); rep = pathlib.Path(trace_path).with_suffix(".report.md"); report(trace_path, rep)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(trace_path, "trace.jsonl"); z.write(rep, "audit_report.md")
        for p in sorted(pack_dir.rglob("*")):
            if p.is_file() and not p.name.startswith("preview_"): z.write(p, "pack/" + str(p.relative_to(pack_dir)))
    return out_zip
