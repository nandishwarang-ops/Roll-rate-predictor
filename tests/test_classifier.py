import sys, pathlib, tempfile, json, datetime; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import classifier as C, driver_registry as R
from guarded_sql import GuardedSQL
from attribution import AttributionTool
from detective import ScriptedClient
ok = lambda n, c: print(("PASS " if c else "FAIL ") + n) or c
r = []; st = pathlib.Path(tempfile.mkdtemp()) / "state.duckdb"
def drv(cat, status="open", what="x", start="2025-05-01", n=1, first=3.0):
    return dict(driver_id="D-T-001", lender_id="LENDER_A", category=cat, what=what, where_json="{}", slice_spec="{}", first_seen=start, start_month=start, last_seen=start, status=status, n_obs=n, excess_first=first)
empty = __import__("pandas").DataFrame({"month_date": [], "excess_pp": [], "z": []})
w = lambda s: {x["name"]: x["weight"] for x in s["scenarios"]}
p = C.prior(drv("festival"), empty); r += [ok("festival seen once: mostly blip", w(p)["blip"] > 0.9)]
p = C.prior(drv("lender_process"), empty, calendar=dict(event_name="Policy", end=None, permanent=True)); r += [ok("policy with no end date: mostly lasting", w(p)["lasting"] >= 0.85)]
p = C.prior(drv("lender_process"), empty, calendar=dict(event_name="Pilot", end=datetime.date(2025, 8, 1), permanent=False)); r += [ok("calendar event with known end: transient until then", p["scenarios"][0]["shape"] == "TRANSIENT" and p["scenarios"][0]["end_month"] == "2025-08-01")]
p = C.prior(drv("technical_failure"), empty, ongoing=False); r += [ok("outage that had stopped: strong blip", w(p)["blip"] >= 0.7)]
p = C.prior(drv("cohort"), empty); r += [ok("cohort driver is lagged (3 months)", p["scenarios"][0]["lag_months"] == 3)]
p = C.prior(drv("unexplained"), empty); r += [ok("unexplained: cautious lasting default, ranges widened, low confidence", p["widen_ranges"] and p["confidence"] == "low")]
r += [ok("recovery within the month lowers lasting weight", w(C.prior(drv("operational"), empty, recovery=dict(trend="recovering")))["lasting"] < w(C.prior(drv("operational"), empty, recovery=dict(trend="no_recovery")))["lasting"])]
for s in ["persistent", "closed_transient", "closed_reverted"]:
    p = C.prior(drv("operational", s, n=3), empty); r += [ok(f"registry status {s}: single scenario, weight 1", len(p["scenarios"]) == 1 and p["scenarios"][0]["weight"] == 1.0)]
import pandas as pd
obs = pd.DataFrame({"month_date": [datetime.date(2024, 9, 1), datetime.date(2024, 10, 1)], "excess_pp": [3.0, 1.2], "z": [4, 3]})
p = C.prior(drv("macro_shock", "fading", first=3.0), obs); hl = p["scenarios"][0]["half_life_months"]
r += [ok(f"fading driver: half-life from observed retention ({hl} months for 40% retained in 1 month)", p["scenarios"][0]["shape"] == "TRANSIENT" and 0.5 <= hl <= 1.2)]
r += [ok("all priors pass validation", all(not C.validate(C.prior(drv(c), empty)) for c in C.PRIOR_LASTING))]
# ---- real data: registry driver + calendar + recovery check
inv = dict(month="2025-05-01", node="LENDER_A|WEST", metric="roll_forward", bucket_from="31-60")
tA = AttributionTool("LENDER_A", "2025-05-01", run_id="cls_test")
a = tA("2025-05-01", "31-60", "roll_forward", {"agency": {"dimension": "agency_id", "values": ["AG_W_TELE_02"]}}, region="WEST", recent_months=1, baseline_lag=2)
res = dict(investigation=inv, findings=dict(drivers=[dict(what="tele agency AG_W_TELE_02 staff loss", where=dict(lender="LENDER_A", region="WEST", sub_slice="agency AG_W_TELE_02"), when=dict(start_month="2025-03"),
           category="operational", evidence_ids=[a["attribution_id"]], attribution_id=a["attribution_id"], confidence="high")]))
did = R.register_from_result(res, tA.evidence, st)[0][0]
out = C.classify_driver(did, tA.g, "2025-05-01", state=st, ongoing=True)
print("    open operational driver ->", [(s["name"], s["weight"]) for s in out["scenarios"]], "| recovery:", out["recovery_check"])
r += [ok("real open driver gets two weighted scenarios and a recovery check", len(out["scenarios"]) == 2 and out["recovery_check"]["trend"] in ("recovering", "no_recovery", "insufficient_data"))]
# ---- LLM path (scripted): accepted, bounced when invalid, prior used when LLM keeps failing
T = lambda name, **a: {"type": "tool_use", "name": name, "input": a}
sc_ok = dict(scenarios=[dict(name="lasting", shape="STEP", weight=0.7, start_month="2025-03-01", lag_months=0), dict(name="blip", shape="DOT", weight=0.3, start_month="2025-03-01")], rationale="agency attrition persists", confidence="medium")
o1 = C.classify_driver(did, tA.g, "2025-05-01", client=ScriptedClient([[T("submit_classification", **sc_ok)]]), state=st, ongoing=True)
r += [ok("valid LLM classification accepted", o1["source"] == "llm" and o1["agrees_with_prior"])]
sc_bad = dict(sc_ok, scenarios=[dict(name="lasting", shape="STEP", weight=0.9, start_month="2025-03-01"), dict(name="blip", shape="DOT", weight=0.3, start_month="2025-03-01")])
o2 = C.classify_driver(did, tA.g, "2025-05-01", client=ScriptedClient([[T("submit_classification", **sc_bad)], [T("submit_classification", **sc_ok)]]), state=st, ongoing=True)
r += [ok("weights not summing to 1 are bounced, corrected answer accepted", o2["source"] == "llm")]
sc_dev = dict(sc_ok, scenarios=[dict(name="blip", shape="DOT", weight=0.9, start_month="2025-03-01"), dict(name="lasting", shape="STEP", weight=0.1, start_month="2025-03-01")])
o3 = C.classify_driver(did, tA.g, "2025-05-01", client=ScriptedClient([[T("submit_classification", **sc_dev)]]), state=st, ongoing=True)
r += [ok("deviation from the prior without a reason is refused; prior is used", o3["source"] == "prior" and any("deviation_reason" in e for e in o3["llm_rejected"]))]
sc_dev2 = dict(sc_dev, deviation_reason="reply from ops says staff were restored; see Q001", evidence_ids=["Q001"])
o4 = C.classify_driver(did, tA.g, "2025-05-01", client=ScriptedClient([[T("submit_classification", **sc_dev2)]]), state=st, ongoing=True)
r += [ok("justified deviation accepted and flagged as disagreeing with the prior", o4["source"] == "llm" and o4["agrees_with_prior"] is False)]
sys.exit(0 if all(r) else 1)
