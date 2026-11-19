import sys, pathlib, time, tempfile, datetime, json; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import escalations as E
ok = lambda n, c: print(("PASS " if c else "FAIL ") + n) or c
tmp = pathlib.Path(tempfile.mkdtemp()); st = tmp / "state.duckdb"; r = []
def Q(sql, params=None):
    c = E._con(st); out = c.sql(sql, params=params).fetchall(); c.close(); return out
ev = {"Q001": {"result": {"rows": [["AG_W_TELE_02", 3.1], ["AG_W_TELE_01", 5.9]]}}}
inv = dict(month="2025-05-01", node="LENDER_A|WEST", metric="roll_forward", bucket_from="31-60", excess_accounts=140.0)
ents = E.entities(inv, ev)
r += [ok("specific question passes", E.check_question("Did AG_W_TELE_02 lose staff or change its allocation in March 2025?", ents) is None)]
r += [ok("generic question fails", E.check_question("Did anything change recently in collections?", ents) is not None)]
r += [ok("question naming no entity fails", E.check_question("Has the process been modified by the team lately at all?", ents) is not None)]
r += [ok("non-question fails", E.check_question("Please look into AG_W_TELE_02 staffing.", ents) is not None)]
bad_q = dict(status="complete", investigation=inv, evidence=ev, findings=dict(headline="x", drivers=[], rejected_hypotheses=[], unexplained_note="cause not found", escalation_questions=["Did anything change?"]))
box = tmp / "outbox"; disp = E.Dispatcher(E.FileOutbox(box), state=st)
e = E.create_from_result(bad_q, disp, st, clues=["agency AG_W_TELE_02"]); disp.wait()
r += [ok("bad model questions replaced by deterministic fallback", e and len(e["questions"]) >= 1 and E.check_question(e["questions"][0], E.entities(inv, ev) | {"agency ag_w_tele_02"}) in (None,) or "AG_W_TELE_02" in e["questions"][0])]
r += [ok("high priority from 140 excess accounts", e["priority"] == "high")]
r += [ok("notification written to outbox and marked sent", (box / f"{e['escalation_id']}.md").exists() and Q("select notify_status from escalations")[0][0] == "sent")]
# non-blocking with a slow channel and a failing channel
class Slow:
    def send(self, esc): time.sleep(2)
class Boom:
    def send(self, esc): raise RuntimeError("smtp down")
good = dict(bad_q, findings=dict(bad_q["findings"], escalation_questions=["Did AG_W_TELE_02 lose staff in March 2025?"]), investigation=dict(inv, node="LENDER_C|WEST|"))
t0 = time.time(); d2 = E.Dispatcher(Slow(), state=st, timeout=5); e2 = E.create_from_result(dict(good, investigation=dict(inv, node="LENDER_B|SOUTH")), d2, st); dt = time.time() - t0
r += [ok(f"slow channel does not block the run ({dt:.2f}s)", dt < 1.0)]; d2.wait()
d3 = E.Dispatcher(Boom(), state=st, retries=1); e3 = E.create_from_result(dict(good, investigation=dict(inv, node="LENDER_B|NORTH")), d3, st); d3.wait()
row = Q("select notify_status, notify_error from escalations where escalation_id=?", [e3["escalation_id"]])[0]
r += [ok(f"failing channel never raises; recorded as failed ({row[1]})", row[0] == "failed" and "smtp down" in row[1])]
# dedupe
again = E.create_from_result(bad_q, disp, st, clues=["agency AG_W_TELE_02"]); disp.wait()
r += [ok("same unresolved question is re-asked, not duplicated", again.get("deduplicated") and Q("select reask_count from escalations where escalation_id=?", [e["escalation_id"]])[0][0] == 1)]
# no escalation when a confident driver explains it
conf = dict(bad_q, findings=dict(headline="h", drivers=[dict(confidence="high")], rejected_hypotheses=[], escalation_questions=[]))
r += [ok("no escalation when a confident driver exists and nothing is unexplained", E.create_from_result(conf, disp, st) is None)]
incomplete = {"status": "incomplete", "reason": "turn limit"}
r += [ok("incomplete investigations are not escalated as questions", E.create_from_result(incomplete, disp, st) is None)]
# answers -> follow-ups
E.record_answer(e["escalation_id"], "AG_W_TELE_02 lost 20 callers in March after attrition.", "ops.lenderA", st)
ft = E.followups_text("LENDER_A", st)
r += [ok("answer becomes a follow-up hypothesis for next month's brief", "lost 20 callers" in ft and "hypotheses to test" in ft)]
E.close(e["escalation_id"], "confirmed by agency comparison", st)
r += [ok("closed escalation no longer injected", E.followups_text("LENDER_A", st) == "")]
r += [ok("overdue detection", len(E.overdue(st, now=datetime.datetime.now() + datetime.timedelta(days=30))) >= 2)]
sec = E.open_section("LENDER_B", st); r += [ok("pack section lists open questions with priority and due date", "Open questions for operations" in sec and "reply by" in sec)]
sys.exit(0 if all(r) else 1)
