import sys, pathlib, tempfile, json, threading, re, zipfile, hashlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import audit_trace as AT, orchestrator as O
from detective import ScriptedClient
from sql_tool import SQLTool
ok = lambda n, c: print(("PASS " if c else "FAIL ") + n) or c
r = []; tmp = pathlib.Path(tempfile.mkdtemp())
# ---- 1. chain, tamper detection, redaction, thread safety
tr = AT.Trace("unit", "L", "2025-03", tmp); [tr.emit("query", "s", "code", f"event {i}", {"i": i}) for i in range(10)]
r += [ok("a clean chain verifies", AT.verify_chain(tr.path)[0])]
lines = tr.path.read_text().splitlines(); mod = [json.loads(l) for l in lines]; mod[4]["payload"]["i"] = 999; p2 = tmp / "edited.jsonl"; p2.write_text("\n".join(json.dumps(e) for e in mod) + "\n"); v = AT.verify_chain(p2)
r += [ok(f"an edited event is detected at the exact event ({v[2]})", not v[0] and v[1] == 5)]
p3 = tmp / "deleted.jsonl"; p3.write_text("\n".join(lines[:3] + lines[4:]) + "\n"); v = AT.verify_chain(p3); r += [ok(f"a deleted event is detected ({v[2]})", not v[0])]
p4 = tmp / "reordered.jsonl"; p4.write_text("\n".join(lines[:2] + [lines[3], lines[2]] + lines[4:]) + "\n"); r += [ok("reordered events are detected", not AT.verify_chain(p4)[0])]
t2 = AT.Trace("secret", "L", "x", tmp); t2.emit("note", "s", "code", "key github_pat_11ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890abcdef used", {"api_key": "sk-ant-abc", "nested": {"password": "hunter2", "msg": "token ghp_abcdefghijklmnopqrstuvwxyz0123456789"}})
raw = t2.path.read_text(); r += [ok("secrets are redacted before they reach disk", "github_pat_" not in raw and "hunter2" not in raw and "sk-ant" not in raw and "ghp_" not in raw and "[REDACTED]" in raw)]
t3 = AT.Trace("threads", "L", "x", tmp); ths = [threading.Thread(target=lambda k=k: [t3.emit("query", "s", "code", f"t{k}-{i}") for i in range(50)]) for k in range(8)]; [t.start() for t in ths]; [t.join() for t in ths]
r += [ok("8 threads x 50 events: sequence contiguous and chain intact (parallel workers are safe)", AT.verify_chain(t3.path)[0] and len(AT.load(t3.path)) == 400)]
# ---- 2. LLM client wrapper never stores prompts
t4 = AT.Trace("llm", "L", "x", tmp); secret_prompt = "CONFIDENTIAL-PROMPT-TEXT-12345"; c = AT.TracedClient(ScriptedClient([[{"type": "tool_use", "name": "run_sql", "input": {"sql": "select 1", "purpose": "x"}}]]), t4, "investigate_i0")
c.create(secret_prompt, [{"role": "user", "content": "hello"}], [{"name": "run_sql"}]); e = AT.load(t4.path)[0]
r += [ok("LLM call logged with tool names, token counts and a prompt hash, not the prompt", e["payload"]["tool_calls"] == ["run_sql"] and "tokens" in e["payload"] and secret_prompt not in t4.path.read_text())]
# ---- 3. a real orchestrated run
O.prepare("2025-03-01"); out = tmp / "run"; rec = O.run_lender(O.RunConfig(lender="LENDER_C", origin="2025-03-01", state_path=out / "state.duckdb", out_root=out, n_sims=600)); path = pathlib.Path(rec["trace"]); ev = AT.load(path); types = [e["type"] for e in ev]
print(f"    run {rec['status']} in {rec['total_secs']}s, {len(ev)} trace events, types: {sorted(set(types))}")
r += [ok("run trace exists and its hash chain verifies", AT.verify_chain(path)[0])]
need = {"run_start", "step_start", "step_end", "query", "attribution", "investigation", "registry", "classification", "escalation", "forecast_run", "ranges_run", "pack", "output", "run_end"}; r += [ok(f"every kind of event is present (missing: {sorted(need - set(types))})", need <= set(types))]
r += [ok("all 11 steps logged as start+end pairs", types.count("step_start") == 11 and types.count("step_end") == 11)]
st = ev[0]; r += [ok("run_start fixes code version and data fingerprint", st["type"] == "run_start" and len(st["payload"]["code"]["git_commit"]) == 40 and st["payload"]["data"]["fingerprint"] and st["payload"]["data"]["d1_account_monthly"]["last_month"] == "2025-09")]
md = pathlib.Path(rec["outputs"]["md"]).read_text(); cited = set(re.findall(r"\b([QA]\d{3})\b", md.split("## Appendix")[0])); ids = {}
for e in ev:
    if e["type"] in ("query", "attribution"): ids.setdefault(e["payload"].get("query_id") or e["payload"].get("attribution_id"), []).append(e)
r += [ok(f"evidence ids are unique across the whole run ({sorted(i for i, v in ids.items() if len(v) > 1)} duplicated)", all(len(v) == 1 for v in ids.values()))]
r += [ok(f"every id cited in the pack resolves to exactly one logged event ({sorted(cited)})", cited and all(len(ids.get(i, [])) == 1 for i in cited))]
d = [e for e in ev if e["type"] == "investigation"]; r += [ok("investigation outcomes logged with sources and evidence", len(d) >= 2 and all("status" in e["payload"] for e in d))]
# rejected query is logged
t5 = AT.Trace("rejected", "L", "x", tmp); s = SQLTool("LENDER_C", "2025-03-01", run_id="rej", trace=t5); s("select * from hidden.d1_account_monthly", "probe the hidden period"); s("select 1 as one", "ok query")
q = [e for e in AT.load(t5.path)]; r += [ok("a rejected query is logged as such (the attempt is part of the record)", q[0]["payload"]["ok"] is False and q[0]["payload"]["error"] and q[1]["payload"]["ok"])]
# ---- 4. explain a number in the pack
facts = out / "packs_md" / "LENDER_C_2025-03.facts.json"; F = json.load(open(facts))
by_src = lambda pre: next(f for f in F if f["source"].startswith(pre))
fa = by_src("A"); x = AT.explain_fact(path, facts, fa["id"]); r += [ok(f"fact {fa['id']} ('{fa['label'][:40]}') traces to its attribution call and the run's code/data versions", any(e["type"] == "attribution" and e["payload"]["attribution_id"] == fa["source"][:4] for e in x["events"]) and any(e["type"] == "run_start" for e in x["events"]))]
fs = by_src("simulation"); x = AT.explain_fact(path, facts, fs["id"]); r += [ok(f"fact {fs['id']} (forecast) traces to the simulation run with its seed and calibration", any(e["type"] == "ranges_run" and e["payload"]["seed"] == 7 and e["payload"]["lambda"] for e in x["events"]))]
fd = by_src("D1 closing"); x = AT.explain_fact(path, facts, fd["id"]); r += [ok("an actual (D1) figure traces to the data fingerprint", any(e["type"] == "run_start" for e in x["events"]))]
# ---- 5. report + export
rep = path.with_suffix(".report.md").read_text(); r += [ok("human-readable audit report states chain integrity, steps, queries, outputs", "Chain integrity: **intact**" in rep and rep.count("| ") > 15 and "## Outputs" in rep and "SQL queries" in rep)]
z = AT.export_bundle(path, out / "packs" / "LENDER_C_2025-03", tmp / "audit.zip"); names = zipfile.ZipFile(z).namelist(); r += [ok("auditor bundle contains trace, report, PDF, Markdown and manifest", {"trace.jsonl", "audit_report.md", "pack/pack.pdf", "pack/pack.md", "pack/manifest.json"} <= set(names))]
outs = {e["payload"]["file"]: e["payload"]["sha256"] for e in ev if e["type"] == "output"}; pk = out / "packs" / "LENDER_C_2025-03"
r += [ok("output hashes in the trace match the delivered files", outs and all(hashlib.sha256((pk / f).read_bytes()).hexdigest() == h for f, h in outs.items()))]
r += [ok("no secret-looking strings anywhere in the trace", not re.search(r"github_pat_|sk-ant-|ghp_", path.read_text()))]
sys.exit(0 if all(r) else 1)
