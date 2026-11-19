import sys, pathlib, tempfile, json; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import driver_registry as R
from attribution import AttributionTool
ok = lambda n, c: print(("PASS " if c else "FAIL ") + n) or c
r = []; st = pathlib.Path(tempfile.mkdtemp()) / "state.duckdb"
# ---- pure state machine
cl = R.classify
r += [ok("open + persists -> persistent (STEP)", cl(3.0, [], 3.3, 2.9, "open", 0)[0] == "persistent")]
r += [ok("open + gone -> closed_transient (blip)", cl(3.0, [], 0.2, 0.3, "open", 0)[0] == "closed_transient")]
r += [ok("open + half-size but still significant -> fading", cl(3.0, [], 3.0, 1.2, "open", 0)[0] == "fading")]
s1 = cl(3.0, [3.0], 0.1, 0.2, "persistent", 0); r += [ok("persistent + one missing month -> stays, one strike", s1[0] == "persistent" and s1[1] == 1)]
r += [ok("persistent + two missing months -> closed_reverted", cl(3.0, [3.0], 0.1, 0.2, "persistent", 1)[0] == "closed_reverted")]
r += [ok("sign flip counts as gone", cl(3.0, [], 3.0, -2.0, "open", 0)[0] == "closed_transient")]
r += [ok("fading + recovery -> persistent", cl(3.0, [1.2], 2.8, 2.9, "fading", 0)[0] == "persistent")]
r += [ok("large effect but borderline z is inconclusive, not fading", cl(3.0, [3.0], 1.8, 5.0, "persistent", 0)[0] == "persistent" and cl(3.0, [], 1.8, 5.0, "open", 0)[0] == "open")]
def Q(sql, params=None):
    c = R._con(st); out = c.sql(sql, params=params).fetchall(); c.close(); return out
# ---- real data: register a driver from a (fake) Detective result using real attribution, then recheck against later months
inv = dict(month="2025-03-01", node="LENDER_A|WEST", metric="roll_forward", bucket_from="31-60")
tA = AttributionTool("LENDER_A", "2025-05-01", run_id="reg_test")
a = tA("2025-05-01", "31-60", "roll_forward", {"agency": {"dimension": "agency_id", "values": ["AG_W_TELE_02"]}}, region="WEST", recent_months=1, baseline_lag=2)
res = dict(investigation=dict(inv, month="2025-05-01"), findings=dict(drivers=[dict(what="tele agency AG_W_TELE_02 staff loss, far fewer calls per account", where=dict(lender="LENDER_A", region="WEST", sub_slice="agency AG_W_TELE_02"),
           when=dict(start_month="2025-03"), category="operational", evidence_ids=["Q001", a["attribution_id"]], attribution_id=a["attribution_id"], confidence="high", control_group_note="AG_W_TELE_01")]))
reg = R.register_from_result(res, tA.evidence, st, run_id="reg_test"); did = reg[0][0]
r += [ok(f"driver registered as new ({reg})", reg[0][1] == "new")]
again = R.register_from_result(res, tA.evidence, st, run_id="reg_test2")
r += [ok("same driver seen again is matched, not duplicated", again[0] == (did, "seen_again"))]
tB = AttributionTool("LENDER_A", "2025-09-01", run_id="reg_test_b", g=tA.g.__class__("LENDER_A", "2025-09-01"))
for m in ["2025-06-01", "2025-07-01"]:                       # recheck uses data available at each month; sandbox cutoff is 2025-09, months <= that
    out = R.recheck_all("LENDER_A", m, tB, st, run_id="recheck"); print("   ", m, out)
o, e = R.history(did, st); r += [ok("observations and transitions recorded", len(o) >= 3 and len(e) >= 1)]
status = Q("select status, label_hint from drivers where driver_id=?", [did])[0]; print("    final status:", status)
r += [ok("real persistent agency effect is NOT closed as a blip", status[0] in ("persistent",))]
r += [ok("active drivers listed for the Detective brief", did in R.active_text("LENDER_A", st))]
# ---- real data: a genuinely transient driver (Surat cash crunch Aug-Nov 2024) should close
tS = AttributionTool("LENDER_A", "2025-03-01", run_id="reg_surat")
a2 = tS("2024-09-01", "CURRENT", "roll_forward", {"surat": {"dimension": "city", "values": ["Surat"]}}, product_type="BUSINESS_LOAN", region="WEST", baseline_lag=1)
res2 = dict(investigation=dict(inv, month="2024-09-01", node="LENDER_A|WEST|BUSINESS_LOAN", bucket_from="CURRENT"), findings=dict(drivers=[dict(what="Surat business-borrower cash crunch", where=dict(lender="LENDER_A", product_type="BUSINESS_LOAN", region="WEST", sub_slice="city Surat"),
            when=dict(start_month="2024-08"), category="macro_shock", evidence_ids=[a2["attribution_id"]], attribution_id=a2["attribution_id"], confidence="medium", control_group_note="other WEST cities")]))
sid = R.register_from_result(res2, tS.evidence, st, run_id="surat")[0][0]
for m in ["2024-10-01", "2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"]:
    print("   ", m, R.recheck_all("LENDER_A", m, tS, st, run_id="recheck_surat"))
sstat = Q("select status, label_hint from drivers where driver_id=?", [sid])[0]; print("    Surat final status:", sstat)
r += [ok("Surat shock ends in a closed state once it stops", sstat[0].startswith("closed") or sstat[0] == "fading")]
sys.exit(0 if all(r) else 1)
