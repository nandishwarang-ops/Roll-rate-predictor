import sys, pathlib, duckdb; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from detective import run_detective, ScriptedClient, validate, SQLTool
ok = lambda n, c: print(("PASS " if c else "FAIL ") + n) or c
root = pathlib.Path(__file__).resolve().parent.parent
con = duckdb.connect(str(root / "rollrate.duckdb"), read_only=True)
inv = dict(month="2025-05-01", level="lender_region", node="LENDER_A|WEST", metric="roll_forward", bucket_from="31-60", direction="up", diff_pp=2.9, z=3.8, via="shared", excess_accounts=80.0)
T = lambda name, **a: {"type": "tool_use", "name": name, "input": a}
good = dict(headline="Lender A West 31-60 roll-forward rose, concentrated in accounts allocated to AG_W_TELE_02.", rejected_hypotheses=[{"hypothesis": "festival", "why_rejected": "control region did not move", "evidence_ids": ["Q001"]}],
            escalation_questions=["Did AG_W_TELE_02 lose staff in March?"],
            drivers=[dict(what="tele agency AG_W_TELE_02 handled far fewer calls per account", where=dict(lender="LENDER_A", region="WEST", sub_slice="agency AG_W_TELE_02"), when=dict(start_month="2025-03", ongoing=True),
                          category="operational", evidence_ids=["Q001", "A001"], attribution_id="A001", control_group_note="accounts of AG_W_TELE_01 in the same region and months", confidence="high")])
bad = {**good, "drivers": [{**good["drivers"][0], "evidence_ids": ["Q099"]}]}
script = [[T("profile_drift", month="2025-05-01", bucket_from="31-60", metric="roll_forward", region="WEST", recent_months=3)],
          [T("run_sql", sql="select agency_id, count(*) n, avg(calls) from (select d.agency_id, d.account_id, count(*) filter (where e.channel='VOICE_CALL') calls from d1_account_monthly d left join d3_collection_events e using (account_id, month_date) where d.month_date=date '2025-05-01' and d.region='WEST' and d.bucket_prev='31-60' group by 1,2) group by 1", purpose="calls per account by agency"),
           T("run_sql", sql="drop table d1_account_monthly", purpose="should be blocked")],
          [T("attribute_change", month="2025-05-01", bucket_from="31-60", metric="roll_forward", region="WEST", recent_months=3, baseline_lag=3, causes={"agency": {"dimension": "agency_id", "values": ["AG_W_TELE_02"]}})],
          [T("submit_findings", **bad)],            # evidence id that does not exist -> bounced
          [T("submit_findings", **good)]]
res = run_detective(inv, ScriptedClient(script), con, run_id="test_detective", max_turns=12)
r = [ok("loop completes with valid findings after one bounce", res["status"] == "complete")]
tr = res["trace"]
r += [ok("blocked SQL surfaced as tool error, loop continued", any(t.get("tool") == "run_sql" and "ERROR" in t["output"] for t in tr))]
r += [ok("fabricated evidence id was rejected first", any(t.get("tool") == "submit_findings" and t["output"].startswith("REJECTED") for t in tr))]
d = res["findings"]["drivers"][0]; a = d["attribution"]
r += [ok(f"attribution numbers copied from the ledger by code (contribution {a['contribution_pp']}pp, 80% {a['contribution_pp_80']})", a["id"] == "A001" and a["contribution_pp"] is not None)]
r += [ok("evidence ledger returned for citation", "Q001" in res["evidence"] and "A001" in res["evidence"])]
# turn limit -> incomplete, never a guess
res2 = run_detective(inv, ScriptedClient([[T("run_sql", sql="select 1 x", purpose="loop")]]), con, run_id="test_detective2", max_turns=3)
r += [ok("turn limit gives 'incomplete', no invented findings", res2["status"] == "incomplete" and "findings" not in res2)]
# repeated invalid submissions -> incomplete
res3 = run_detective(inv, ScriptedClient([[T("submit_findings", **bad)]]), con, run_id="test_detective3", max_turns=8)
r += [ok("repeated invalid submissions end as incomplete", res3["status"] == "incomplete" and "validation" in res3["reason"])]
sys.exit(0 if all(r) else 1)
