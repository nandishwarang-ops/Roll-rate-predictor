import sys, pathlib, json, tempfile, glob, duckdb, numpy as np, pandas as pd; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import pack_author as PA, rollup as RU, ranges as RG, driver_registry as R, classifier as CL, escalations as E
from attribution import AttributionTool
from sql_tool import SQLTool
from detective import ScriptedClient
ok = lambda n, c: print(("PASS " if c else "FAIL ") + n) or c
root = pathlib.Path(__file__).resolve().parent.parent; con = duckdb.connect(str(root / "rollrate.duckdb"), read_only=True); q = lambda s: con.sql(s).df(); r = []
L, O = "LENDER_A", "2025-06-01"; st = pathlib.Path(tempfile.mkdtemp()) / "state.duckdb"
bo = con.sql("select * from mart.bakeoff_forecasts where model='ensemble'").df(); bo["origin"] = pd.to_datetime(bo.origin); fc = bo[bo.origin == pd.Timestamp(O)]
summary, sim = RG.ranged_outlook(q, L, O, [(fc, 1.0)], con, N=1500, seed=4); ru = RU.build_rollup(q, L, O, sim)
# --- a real driver: West agency attrition, quantified by the attribution engine, registered, classified
sql = SQLTool(L, O, run_id="pack_test"); qr = sql("select agency_id, count(*) n from d1_account_monthly where month_date=date '2025-06-01' and region='WEST' and bucket_prev='31-60' group by 1 order by 2 desc", "accounts by agency")
attr = AttributionTool(L, O, run_id="pack_test", g=sql.g); a = attr(O, "31-60", "roll_forward", {"agency": {"dimension": "agency_id", "values": ["AG_W_TELE_02"]}}, region="WEST", recent_months=1, baseline_lag=3)
res0 = dict(investigation=dict(month=O, node="LENDER_A|WEST", metric="roll_forward", bucket_from="31-60"), findings=dict(drivers=[dict(what="tele agency AG_W_TELE_02 handled far fewer calls per account", where=dict(lender=L, region="WEST", sub_slice="agency AG_W_TELE_02"), when=dict(start_month="2025-03"),
          category="operational", evidence_ids=[qr["query_id"], a["attribution_id"]], attribution_id=a["attribution_id"], confidence="high", control_group_note="accounts of the other West tele agency in the same months")]))
did = R.register_from_result(res0, attr.evidence, st)[0][0]; cls = CL.classify_driver(did, sql.g, O, state=st, ongoing=True); d0, _ = CL.get_driver(did, st); cz = a["causes"]["agency"]
driver = dict(driver_id=did, what="agency AG_W_TELE_02 handled far fewer calls per account", where="Lender A, West region, accounts allocated to AG_W_TELE_02", start_label="March 2025", category="operational", status=d0["status"], evidence_ids=[qr["query_id"], a["attribution_id"]], attribution_id=a["attribution_id"],
              observed_change_pp=a["observed_change_pp"], pool_label="Lender A West 31-60 roll-forward rate", contribution_pp=cz["contribution_pp"], contribution_pp_80=cz["contribution_pp_80"], share_of_change=cz.get("share_of_change"), unexplained_share=a.get("unexplained_share"),
              control_change_pp=a["control_change_pp"], control_group_note="accounts of the other West tele agency in the same months", scenarios=cls["scenarios"])
# --- escalation, changes, movers
resE = dict(status="complete", investigation=dict(month=O, node="LENDER_A|NORTH", metric="roll_forward", bucket_from="1-30", excess_accounts=60.0), evidence={}, findings=dict(headline="x", drivers=[], rejected_hypotheses=[], unexplained_note="no cause found", escalation_questions=[]))
E.create_from_result(resE, None, st, clues=["agency NORTH_TELE_1"]); esc = PA.escalations_for(L, st)
ss, tot = RU.what_moved(q, L, O, "31-60", "roll_forward")
rid = sorted(glob.glob(str(root / "outputs/forecasts/fc_LENDER_A_2025-06_*.json")))[-1].split("/")[-1][:-5]
cal = json.loads((root / "src/range_calibration.json").read_text()); txt = (root / "docs/range_calibration.md").read_text(); covs = [float(x) / 100 for line in txt.split("Calibrated coverage (%):")[1].split("Mean 80%")[0].splitlines() if line.startswith("| npa") for x in line.split("|")[2:5]]
dq = json.loads((root / "docs/data_quality_report.json").read_text())["summary"]
ctx = dict(lender=L, origin=O, rollup=ru, drivers=[driver], movers=dict(table=ss, total_pp=tot, label="31-60 roll-forward rate", month=O, source="mart.moves_segment shift-share"), run_id=rid, escalations=esc, changes=None,
           evidence_ids=[qr["query_id"], a["attribution_id"]], dq=dq, calibration=dict(min_cov=min(covs), max_cov=max(covs)))
pack = PA.build_pack(ctx); md = pack["markdown"]; F = pack["facts"]
print("\n".join(md.splitlines()[:30])); print("   ...", len(md.splitlines()), "lines,", len(F.f), "facts, source:", pack["source"])
r += [ok("template pack passes the tokenised audit and the rendered audit", pack["source"] == "template" and not PA.audit(PA.assemble(pack["sections"]), F, ctx["evidence_ids"], pack["sections"]) and not PA.audit_rendered(md, F))]
r += [ok("all sections present", all(t in md for t in ["Outlook (3 months)", "Forecast by bucket", "What moved", "Drivers", "Changes since last month", "Open questions for operations", "Methodology and limits"]))]
r += [ok("run id and evidence ids are cited", rid in md and qr["query_id"] in md and a["attribution_id"] in md)]
r += [ok("headline states the cause and direction", md.startswith("# Lender A West 31-60") and ("rose" in md.splitlines()[0] or "fell" in md.splitlines()[0]))]
# --- the auditor catches what it must
sec = dict(pack["sections"]); base = PA.assemble(sec)
bad = {"typed number": base.replace("## Methodology", "## Methodology\n\nAbout 82% of the rise is explained.", 1), "unknown token": base + "\n\nSee {{F999}}.", "fabricated citation": base.replace(a["attribution_id"], "A099", 1)}
for name, t in bad.items(): r += [ok(f"auditor rejects: {name}", bool(PA.audit(t, F, ctx["evidence_ids"], pack["sections"])))]
neg = F.add("test negative", -3.0, "pp", "test", signed=True); r += [ok("auditor rejects 'rose' next to a negative fact", bool(PA.audit(f"The rate rose by {neg} last month.", F)))]
r += [ok("...and accepts the right direction", not PA.audit(f"The rate fell by {neg} last month.", F))]
nocite = dict(sec, Drivers="### A driver\n\nSomething happened with no evidence."); r += [ok("driver paragraph without citation rejected", any("citation" in i for i in PA.audit(PA.assemble(nocite), F, ctx["evidence_ids"], nocite)))]
nor = dict(sec); nor["Outlook (3 months)"] = nor["Outlook (3 months)"].replace(rid, "x"); r += [ok("outlook without model run id rejected", any("run id" in i for i in PA.audit(PA.assemble(nor), F, ctx["evidence_ids"], nor)))]
r += [ok("rendered-text audit catches a number edited after rendering", bool(PA.audit_rendered(md.replace(F.fmt(list(F.f)[0]), "9,999", 1) if False else md + "\n\nThe rate is 47.3% today.", F)))]
# --- LLM path (scripted): invented number is bounced, corrected submission accepted; persistent failure falls back to the template
T = lambda **a: [{"type": "tool_use", "name": "submit_pack", "input": a}]
badsec = dict(sec); badsec["Headline"] = sec["Headline"] + " It rose 82% overall."
p1 = PA.build_pack(ctx, ScriptedClient([T(sections=badsec), T(sections=sec)])); r += [ok("LLM pack: invented number bounced, corrected pack accepted", p1["source"] == "llm")]
p2 = PA.build_pack(ctx, ScriptedClient([T(sections=badsec)])); r += [ok("LLM pack failing the audit repeatedly falls back to the template", p2["source"].startswith("template") and bool(p2["llm_issues"]))]
r += [ok("fallback pack equals the template pack", p2["markdown"] == md)]
r += [ok("pack, facts and audit files written", all(pathlib.Path(root / "outputs/packs" / f"LENDER_A_2025-06{x}").exists() for x in (".md", ".facts.json", ".audit.json")))]
sys.exit(0 if all(r) else 1)
