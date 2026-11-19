import sys, pathlib, tempfile, json, time, re; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import orchestrator as O, escalations as ES
from pypdf import PdfReader
ok = lambda n, c: print(("PASS " if c else "FAIL ") + n) or c
r = []; ORIGIN = "2025-03-01"; O.prepare(ORIGIN)
def run(L="LENDER_C", **kw):
    tmp = pathlib.Path(tempfile.mkdtemp()); kw.setdefault("n_sims", 600); return O.run_lender(O.RunConfig(lender=L, origin=ORIGIN, state_path=tmp / "state.duckdb", out_root=tmp, **kw)), tmp
# 1. happy path
rec, tmp = run(); pdf = pathlib.Path(rec["outputs"]["pdf"]); md = pathlib.Path(rec["outputs"]["md"]).read_text()
r += [ok(f"happy path completes end to end in {rec['total_secs']}s with all 11 steps ok", rec["status"] == "complete" and all(n["status"] == "ok" for n in rec["nodes"]) and len(rec["nodes"]) == 11)]
r += [ok("investigations ran in parallel workers and completed", len(rec["investigations"]) >= 2 and all(i["status"] == "complete" for i in rec["investigations"]))]
r += [ok("PDF + Markdown + manifest produced with 4 charts", pdf.exists() and len(PdfReader(str(pdf)).pages[0].images) + sum(len(p.images) for p in PdfReader(str(pdf)).pages[1:]) >= 4 and md.count("![") == 4)]
r += [ok("pack states the rule-based investigator cannot name the mechanism and asks operations", "mechanism not confirmed" in md and "Open questions for operations" in md and "E-C-" in md)]
r += [ok("driver registered, classified and forecast (intervention run used)", len(rec["active_drivers"]) >= 1 and "fc_LENDER_C_2025-03_" in md and "Forecast scenarios" in md)]
print("    drivers section:\n" + "\n".join("      " + l for l in md.split("## Drivers")[1].split("## Changes")[0].strip().splitlines()[:6])[:1500])
rj = json.loads((tmp / "runs" / f"{rec['run_id']}.json").read_text()); r += [ok("run record written with per-step timings", len(rj["nodes"]) == 11 and all(n["secs"] is not None for n in rj["nodes"]))]
# 2. one investigator crashes -> marked incomplete, the rest proceed, pack still produced and says so
rec2, tmp2 = run(inject={"investigate_error": 0}); md2 = pathlib.Path(rec2["outputs"]["pdf"]).with_name("pack.md").read_text()
r += [ok("investigator crash: that movement incomplete, others complete, run continues", rec2["status"] == "complete_with_warnings" and len(rec2["incomplete_investigations"]) == 1 and sum(i["status"] == "complete" for i in rec2["investigations"]) >= 1)]
r += [ok("pack discloses the incomplete investigation and keeps the baseline for it", "could not be investigated automatically" in md2 and "statistical baseline forecast" in md2)]
# 3. investigator timeout
t0 = time.time(); rec3, _ = run(inject={"investigate_slow": 1}, investigation_timeout=2.0)
r += [ok("investigator timeout is handled as incomplete", any("timed out" in (i["reason"] or "") for i in rec3["investigations"]) and rec3["outputs"].get("pdf"))]
# 4. data checks fail -> paused, no pack
rec4, tmp4 = run(inject={"dq_fail": True}); r += [ok("failed data checks pause the run: no pack, reason recorded", rec4["status"].startswith("paused") and not rec4["outputs"] and not (tmp4 / "packs").exists())]
# 5. chart failure -> pack without charts
rec5, _ = run(inject={"charts_error": True}); p5 = pathlib.Path(rec5["outputs"]["pdf"]); r += [ok("chart failure: pack still produced, without charts", rec5["status"] == "complete_with_warnings" and p5.exists() and sum(len(p.images) for p in PdfReader(str(p5)).pages) == 0)]
# 6. intervention forecast failure -> baseline forecast + warning
rec6, _ = run(inject={"forecast_error": True}); md6 = pathlib.Path(rec6["outputs"]["pdf"]).with_name("pack.md").read_text()
r += [ok("intervention-forecast failure falls back to the baseline forecast with a warning", rec6["status"] == "complete_with_warnings" and any("forecast" in w for w in rec6["warnings"]) and "_baseline" in md6 and rec6["outputs"].get("pdf"))]
# 7. idempotent escalations on re-run with the same state
tmp7 = pathlib.Path(tempfile.mkdtemp()); st = tmp7 / "state.duckdb"
for _ in range(2): O.run_lender(O.RunConfig(lender="LENDER_C", origin=ORIGIN, state_path=st, out_root=tmp7, n_sims=400))
c = ES._con(st); n, again = c.sql("select count(*), max(reask_count) from escalations").fetchone(); c.close()
r += [ok(f"re-running the same month re-asks open questions instead of duplicating them ({n} escalations, max re-ask {again})", again >= 1 and n <= 6)]
# 8. all three lenders in parallel
recs, wall = O.run_month(ORIGIN, n_sims=600, state_path=st, out_root=tmp7); seq = sum(x["total_secs"] for x in recs)
r += [ok(f"three lenders in parallel: all complete; wall {wall}s vs {seq:.0f}s if run one after another", all(x["status"].startswith("complete") for x in recs) and len(recs) == 3 and wall < seq)]
r += [ok("whole monthly run for all lenders is far inside the 30-minute target", wall < 1800)]
sys.exit(0 if all(r) else 1)
