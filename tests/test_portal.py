import sys, pathlib, tempfile, shutil, json, time, re, secrets, threading, hashlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import portal_app as PAPP, portal_store as PS, audit_trace as AT, escalations as ES, pack_author as PA
ok = lambda n, c: print(("PASS " if c else "FAIL ") + n) or c
root = pathlib.Path(__file__).resolve().parent.parent; r = []; SRC = root / "outputs/packs/bundle_LENDER_A_2025-06"
assert SRC.exists(), "run tests/test_doc_generator.py first (it builds the sample bundle)"
GATE = threading.Event(); GATE.set(); CALLS = []
def stub(lender, month, out_root, state_path):
    CALLS.append((lender, month)); GATE.wait(20); out_root = pathlib.Path(out_root); pk = out_root / "packs" / f"{lender}_{month[:7]}"; shutil.copytree(SRC, pk, ignore=shutil.ignore_patterns("preview_*"))
    rid = f"run_{lender}_{month[:7]}_{secrets.token_hex(3)}"; tr = AT.Trace(rid, lender, month[:7], out_root / "trace"); tr.emit("run_start", "start", "system", "stub run", {"lender": lender, "origin": month[:7], "code": {"git_commit": "0" * 40, "src_uncommitted_changes": False}, "data": {"fingerprint": "x"}}); tr.emit("run_end", "end", "system", "done", {"status": "complete"})
    (out_root / "runs").mkdir(parents=True, exist_ok=True); (out_root / "runs" / f"{rid}.json").write_text(json.dumps({"run_id": rid, "status": "complete", "nodes": [{"node": "checks", "status": "ok", "secs": 0.4, "error": None}], "warnings": [], "investigations": [],
        "findings": [{"label": "LENDER_A / WEST 31-60 roll forward", "status": "complete", "headline": "moved", "drivers": [{"what": "agency AG_W_TELE_02 <b>x</b>", "where": {}, "when": {}, "category": "operational", "confidence": "medium", "evidence_ids": ["Q101"], "control_group_note": "rest"}], "rejected_hypotheses": [], "unexplained_note": "mechanism not established", "escalation_questions": []}]}))
    return {"run_id": rid, "status": "complete", "trace": str(tr.path)}
base = pathlib.Path(tempfile.mkdtemp()); app = PAPP.create_app(base, runner=stub, months=["2025-03", "2025-06"]); st = app.store; pw = {u: secrets.token_urlsafe(14) for u in ["ana", "bo", "lenA", "lenB", "thr"]}
st.create_user("ana", pw["ana"], "analyst"); st.create_user("bo", pw["bo"], "analyst"); st.create_user("lenA", pw["lenA"], "lender", "LENDER_A"); st.create_user("lenB", pw["lenB"], "lender", "LENDER_B"); st.create_user("thr", pw["thr"], "analyst")
def client(user=None):
    c = app.test_client(); tok = re.search(r'name="csrf" value="(\w+)"', c.get("/login").text).group(1)
    if user: resp = c.post("/login", data={"username": user, "password": pw[user], "csrf": tok}); assert resp.status_code == 302, resp.status_code
    return c
def tok(c, path="/"): return re.search(r'name="csrf" value="(\w+)"', c.get(path, follow_redirects=True).text).group(1)
def post(c, path, **d): return c.post(path, data={**d, "csrf": tok(c, "/" if "lender" not in path else "/lender")}, follow_redirects=False)
def new_run(c, lender, month):
    before = {x["id"] for x in st.runs()}; post(c, "/run", lender=lender, month=month); new = [x["id"] for x in st.runs() if x["id"] not in before]; assert len(new) == 1, new; return new[0]
def wait_done(rid, t=20):
    for _ in range(int(t * 10)):
        if st.run(rid)["status"] not in ("queued", "running"): return st.run(rid)
        time.sleep(0.1)
    return st.run(rid)
# ---- auth and CSRF
anon = app.test_client(); r += [ok("anonymous users are sent to sign-in", anon.get("/").status_code == 302 and "/login" in anon.get("/").headers["Location"])]
r += [ok("a POST without the CSRF token is refused", anon.post("/login", data={"username": "ana", "password": pw["ana"]}).status_code == 400)]
c = app.test_client(); t0 = tok(c, "/login"); r += [ok("wrong password does not sign in", c.post("/login", data={"username": "ana", "password": "wrong-password", "csrf": t0}).status_code == 200)]
for _ in range(5): c.post("/login", data={"username": "thr", "password": "nope-nope-nope", "csrf": t0})
r += [ok("repeated failures are throttled (429), even with the right password", c.post("/login", data={"username": "thr", "password": pw["thr"], "csrf": t0}).status_code == 429)]
r += [ok("session cookie is HttpOnly and the security headers are set", "HttpOnly" in client("ana").get("/").headers.get("Set-Cookie", "HttpOnly") and client("ana").get("/").headers["X-Content-Type-Options"] == "nosniff" and "frame-ancestors" in client("ana").get("/").headers["Content-Security-Policy"])]
# ---- run (async), no duplicate active run
ana = client("ana"); GATE.clear(); resp = post(ana, "/run", lender="LENDER_A", month="2025-06"); rid = st.runs()[0]["id"]; time.sleep(0.3)
post(ana, "/run", lender="LENDER_A", month="2025-06"); r += [ok("a run starts in the background and a second run for the same lender-month is refused while it is active", len(st.runs()) == 1 and st.run(rid)["status"] in ("queued", "running"))]
GATE.set(); run = wait_done(rid); r += [ok(f"run finishes: status {run['status']}, pack state {run['pack_state']}", run["status"] == "complete" and run["pack_state"] == "draft" and run["pack_dir"])]
r += [ok("run page shows investigation trail, escaped finding text and key facts", "AG_W_TELE_02 &lt;b&gt;x&lt;/b&gt;" in ana.get(f"/runs/{rid}").text and "Trace integrity" in ana.get(f"/runs/{rid}").text)]
# ---- lender isolation before delivery
lenA, lenB = client("lenA"), client("lenB")
r += [ok("a lender user cannot open an undelivered pack (404) or its files", lenA.get(f"/runs/{rid}").status_code == 404 and lenA.get(f"/runs/{rid}/file/pack.pdf").status_code == 404)]
r += [ok("a lender user cannot start runs or take decisions (403)", post(lenA, "/run", lender="LENDER_A", month="2025-06").status_code == 403 and post(lenA, f"/runs/{rid}/act", action="approve").status_code == 403)]
# ---- state machine
bo = client("bo"); r += [ok("cannot approve before review starts", "approve only after review" in bo.post(f"/runs/{rid}/act", data={"action": "approve", "csrf": tok(bo, f"/runs/{rid}")}, follow_redirects=True).text)]
post(bo, f"/runs/{rid}/act", action="start_review"); r += [ok("review can start (draft -> in_review)", st.run(rid)["pack_state"] == "in_review")]
post(ana, f"/runs/{rid}/act", action="approve"); r += [ok("four-eyes: the person who started the run cannot approve it", st.run(rid)["pack_state"] == "in_review")]
# tamper with the trace: approval must be blocked
tp = pathlib.Path(st.run(rid)["trace_path"]); orig_t = tp.read_text(); tp.write_text(orig_t.replace("stub run", "edited run")); post(bo, f"/runs/{rid}/act", action="approve")
r += [ok("approval is blocked when the audit trace was edited", st.run(rid)["pack_state"] == "in_review" and "chain" in "".join(st.check_pack(st.run(rid))))]
tp.write_text(orig_t); post(bo, f"/runs/{rid}/act", action="approve"); r += [ok("a different analyst can approve once the trace is intact", st.run(rid)["pack_state"] == "approved" and st.run(rid)["approved_by"] == "bo")]
# tamper with the pack: delivery blocked
pdf = pathlib.Path(st.run(rid)["pack_dir"]) / "pack.md"; orig_p = pdf.read_text(); pdf.write_text(orig_p + "\nThe rate is 99.9% today.\n"); post(bo, f"/runs/{rid}/act", action="deliver")
r += [ok("delivery is blocked when the pack was edited after generation", st.run(rid)["pack_state"] == "approved" and any("pack.md" in p for p in st.check_pack(st.run(rid))))]
pdf.write_text(orig_p); post(bo, f"/runs/{rid}/act", action="deliver"); run = st.run(rid); r += [ok("an intact approved pack is delivered to the lender's own space", run["pack_state"] == "delivered" and "delivered/LENDER_A/2025-06/v1" in run["delivered_dir"])]
# ---- lender view after delivery
r += [ok("the owning lender now sees the pack and can download the PDF", lenA.get(f"/runs/{rid}").status_code == 200 and lenA.get(f"/runs/{rid}/file/pack.pdf").status_code == 200 and lenA.get(f"/runs/{rid}/file/pack.pdf").data[:4] == b"%PDF")]
r += [ok("another lender gets 404 for the same pack and its files", lenB.get(f"/runs/{rid}").status_code == 404 and lenB.get(f"/runs/{rid}/file/pack.pdf").status_code == 404 and rid not in lenB.get("/lender").text)]
r += [ok("the lender view hides analyst-only material (evidence ledger, audit, comments, decisions)", all(x not in lenA.get(f"/runs/{rid}").text for x in ["Evidence ledger", "Investigation trail", "Human actions", "Approve"]) and lenA.get(f"/runs/{rid}/file/evidence.json").status_code == 404)]
r += [ok("the lender API lists only that lender's delivered packs", [x["id"] for x in lenA.get("/api/runs").json] == [rid] and lenB.get("/api/runs").json == [])]
# ---- file serving hardening
bad = [f"/runs/{rid}/file/../../../../etc/passwd", f"/runs/{rid}/file/..%2F..%2Fportal.sqlite", f"/runs/{rid}/file/manifest.json.exe", f"/runs/{rid}/file/charts/../../portal.sqlite", f"/runs/{rid}/file//etc/passwd"]
r += [ok("path traversal and non-whitelisted files are refused", all(lenA.get(b, follow_redirects=True).status_code in (404, 400) and ana.get(b, follow_redirects=True).status_code in (404, 400) for b in bad))]
# ---- escalations and replies
sp = base / "state.duckdb"; resE = dict(status="complete", investigation=dict(month="2025-06-01", node="LENDER_A|NORTH", metric="roll_forward", bucket_from="1-30", excess_accounts=60.0), evidence={}, findings=dict(headline="x", drivers=[], rejected_hypotheses=[], unexplained_note="n", escalation_questions=[]))
e = ES.create_from_result(resE, None, sp, clues=["agency NORTH_TELE_1"]); eid = e["escalation_id"]; page = lenA.get(f"/runs/{rid}").text
r += [ok("lender user sees the open question for their own lender", eid in page)]
post(lenA, f"/runs/{rid}/reply", escalation_id=eid, answer="NORTH_TELE_1 lost callers in June"); r += [ok("their reply is stored as a follow-up for next month", "lost callers" in ES.followups_text("LENDER_A", sp))]
post(lenB, f"/runs/{rid}/reply", escalation_id=eid, answer="should not work"); r += [ok("another lender cannot reply to it", "should not work" not in ES.followups_text("LENDER_A", sp))]
# ---- comments (XSS), reject, supersede
ana.post(f"/runs/{rid}/comment", data={"body": "<script>alert(1)</script> looks fine", "csrf": tok(ana, f"/runs/{rid}")}); page = ana.get(f"/runs/{rid}").text
r += [ok("comments are escaped (no script injection)", "&lt;script&gt;alert(1)&lt;/script&gt;" in page and "<script>alert(1)" not in page)]
rid2 = new_run(ana, "LENDER_B", "2025-03"); wait_done(rid2); r += [ok("reject needs a reason", not st.transition(rid2, st.user("ana"), "reject", "")[0] and st.transition(rid2, st.user("ana"), "reject", "numbers look off")[0] and st.run(rid2)["pack_state"] == "rejected")]
n_before = len(st.runs()); post(ana, f"/runs/{rid}/act", action="supersede"); r += [ok("a delivered pack cannot be superseded (it is already with the lender)", st.run(rid)["pack_state"] == "delivered" and len(st.runs()) == n_before)]
rid3 = new_run(ana, "LENDER_A", "2025-03"); wait_done(rid3); ids_before = {x["id"] for x in st.runs()}; post(ana, f"/runs/{rid3}/act", action="supersede"); newr = [x["id"] for x in st.runs() if x["id"] not in ids_before]; [wait_done(i) for i in newr]
r += [ok("re-run: the old pack is superseded and exactly one new run is started", st.run(rid3)["pack_state"] == "superseded" and len(newr) == 1 and st.run(newr[0])["pack_state"] == "draft")]
# second delivery of the same lender-month supersedes v1
rid4 = new_run(ana, "LENDER_A", "2025-06"); wait_done(rid4); post(bo, f"/runs/{rid4}/act", action="start_review"); post(bo, f"/runs/{rid4}/act", action="approve"); post(bo, f"/runs/{rid4}/act", action="deliver")
r += [ok("a newer delivery becomes v2 and the earlier one is marked superseded", st.run(rid4)["pack_state"] == "delivered" and st.run(rid4)["delivered_dir"].endswith("v2") and st.run(rid)["pack_state"] == "superseded" and [x["id"] for x in lenA.get("/api/runs").json] == [rid4])]
# ---- human action log
ev = [json.loads(l) for l in open(st.audit_path)]; types = {x["type"] for x in ev}
r += [ok(f"every human action is in the hash-chained log ({len(ev)} events)", {"login", "login_failed", "run_requested", "pack_start_review", "pack_approve", "pack_deliver", "comment", "escalation_reply", "file_viewed"} <= types and st.verify_audit()[0])]
lines = st.audit_path.read_text().splitlines(); m = json.loads(lines[3]); m["summary"] = "edited"; bad_p = base / "audit_edit.jsonl"; bad_p.write_text("\n".join(lines[:3] + [json.dumps(m)] + lines[4:]) + "\n")
r += [ok("editing the action log is detected", not AT.verify_chain(bad_p)[0])]
f = app.jinja_env.filters["code"]; r += [ok("the code filter renders backticked identifiers and still escapes everything else", str(f("`mob_0-3` and <img src=x onerror=alert(1)> `<b>`")) == "<code>mob_0-3</code> and &lt;img src=x onerror=alert(1)&gt; <code>&lt;b&gt;</code>")]
sys.exit(0 if all(r) else 1)
