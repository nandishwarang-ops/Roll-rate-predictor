"""shared real-data fixture: Lender A, June 2025 pack inputs (used by section 25+ tests)."""
import sys, pathlib, json, tempfile, glob, duckdb, numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import pack_author as PA, rollup as RU, ranges as RG, driver_registry as R, classifier as CL, escalations as E, charts as CH
from attribution import AttributionTool
from sql_tool import SQLTool
root = pathlib.Path(__file__).resolve().parent.parent
def lender_a_inputs(N=1500, charts_dir=root / "outputs/charts/fixture"):
    con = duckdb.connect(str(root / "rollrate.duckdb"), read_only=True); q = lambda s: con.sql(s).df(); L, O = "LENDER_A", "2025-06-01"; st = pathlib.Path(tempfile.mkdtemp()) / "state.duckdb"
    bo = con.sql("select * from mart.bakeoff_forecasts where model='ensemble'").df(); bo["origin"] = pd.to_datetime(bo.origin); fc = bo[bo.origin == pd.Timestamp(O)]
    summary, sim = RG.ranged_outlook(q, L, O, [(fc, 1.0)], con, N=N, seed=4); ru = RU.build_rollup(q, L, O, sim)
    sql = SQLTool(L, O, run_id="fixture"); qr = sql("select agency_id, count(*) n from d1_account_monthly where month_date=date '2025-06-01' and region='WEST' and bucket_prev='31-60' group by 1 order by 2 desc", "accounts opening the month in 31-60 by agency, West region")
    attr = AttributionTool(L, O, run_id="fixture", g=sql.g); a = attr(O, "31-60", "roll_forward", {"agency": {"dimension": "agency_id", "values": ["AG_W_TELE_02"]}}, region="WEST", recent_months=1, baseline_lag=3)
    res0 = dict(investigation=dict(month=O, node="LENDER_A|WEST", metric="roll_forward", bucket_from="31-60"), findings=dict(drivers=[dict(what="x", where=dict(lender=L, region="WEST", sub_slice="agency AG_W_TELE_02"), when=dict(start_month="2025-03"), category="operational", evidence_ids=[qr["query_id"], a["attribution_id"]], attribution_id=a["attribution_id"], confidence="high", control_group_note="c")]))
    did = R.register_from_result(res0, attr.evidence, st)[0][0]; cls = CL.classify_driver(did, sql.g, O, state=st, ongoing=True); d0, _ = CL.get_driver(did, st); cz = a["causes"]["agency"]
    driver = dict(driver_id=did, what="agency AG_W_TELE_02 handled far fewer calls per account", where="Lender A, West region, accounts allocated to AG_W_TELE_02", start_label="March 2025", category="operational", status=d0["status"], evidence_ids=[qr["query_id"], a["attribution_id"]], attribution_id=a["attribution_id"],
                  observed_change_pp=a["observed_change_pp"], pool_label="Lender A West 31-60 roll-forward rate", contribution_pp=cz["contribution_pp"], contribution_pp_80=cz["contribution_pp_80"], share_of_change=cz.get("share_of_change"), unexplained_share=a.get("unexplained_share"),
                  control_change_pp=a["control_change_pp"], control_group_note="accounts of the other West tele agency in the same months", scenarios=cls["scenarios"])
    resE = dict(status="complete", investigation=dict(month=O, node="LENDER_A|NORTH", metric="roll_forward", bucket_from="1-30", excess_accounts=60.0), evidence={}, findings=dict(headline="x", drivers=[], rejected_hypotheses=[], unexplained_note="no cause found", escalation_questions=[]))
    E.create_from_result(resE, None, st, clues=["agency NORTH_TELE_1"]); esc = PA.escalations_for(L, st); ss, tot = RU.what_moved(q, L, O, "31-60", "roll_forward")
    rid = sorted(glob.glob(str(root / "outputs/forecasts/fc_LENDER_A_2025-06_*.json")))[-1].split("/")[-1][:-5]
    txt = (root / "docs/range_calibration.md").read_text(); covs = [float(x) / 100 for line in txt.split("Calibrated coverage (%):")[1].split("Mean 80%")[0].splitlines() if line.startswith("| npa") for x in line.split("|")[2:5]]
    dq = json.loads((root / "docs/data_quality_report.json").read_text())["summary"]
    ctx = dict(lender=L, origin=O, rollup=ru, drivers=[driver], movers=dict(table=ss, total_pp=tot, label="31-60 roll-forward rate", month=O, source="mart.moves_segment shift-share"), run_id=rid, escalations=esc, changes=None, evidence_ids=[qr["query_id"], a["attribution_id"]], dq=dq, calibration=dict(min_cov=min(covs), max_cov=max(covs)))
    # charts
    mk = lambda b, m="roll_forward": (lambda d: d.assign(month_date=pd.to_datetime(d.month_date)).set_index("month_date").v)(q(f"select month_date, sum({m}*opening_accounts)/sum(opening_accounts) v from mart.moves_segment where lender_id='{L}' and bucket_from='{b}' and month_date <= date '{O}' group by 1 order by 1"))
    def fcr(b, m="roll_forward"): x = ru[(ru.level == "lender") & (ru.metric == f"{m}_{b}")].copy(); x["m"] = pd.Timestamp(O) + x.h.map(lambda h: pd.DateOffset(months=int(h))); return x.set_index("m")
    ev = q("select event_start_date d, event_name n from event_calendar where lender_id is null or lender_id='LENDER_A' order by 1").values.tolist(); f31 = fcr("31-60")
    npa_h = q(f"select month_date, count(*) n from d1_account_monthly where lender_id='{L}' and bucket_curr='90+' and month_date <= date '{O}' group by 1 order by 1"); npa_h["month_date"] = pd.to_datetime(npa_h.month_date); npa_h = npa_h.set_index("month_date").n.tail(18)
    nf = ru[(ru.level == "lender") & (ru.metric == "npa_accounts")].copy(); nf["m"] = pd.Timestamp(O) + nf.h.map(lambda h: pd.DateOffset(months=int(h))); nf = nf.set_index("m"); bk = ["CURRENT", "1-30", "31-60", "61-90"]
    charts = {"rate_forecast": CH.rate_forecast(mk("31-60").tail(18), f31["mean"], f31["p50"], f31[["p10", "p90"]], charts_dir / "rate_forecast.png", "Lender A, all products", "31-60 roll-forward rate", ev),
              "npa_outlook": CH.npa_outlook(npa_h, nf["p50"], nf[["p10", "p90"]], charts_dir / "npa_outlook.png", "Lender A"), "what_moved": CH.what_moved(ss, tot, charts_dir / "what_moved.png", "Lender A", "31-60 roll-forward rate", pd.Timestamp(O)),
              "bucket_panels": CH.bucket_panels({b: mk(b).tail(18) for b in bk}, {b: fcr(b)["p50"] for b in bk}, {b: fcr(b)[["p10", "p90"]] for b in bk}, charts_dir / "bucket_panels.png", "Lender A", "roll-forward rate")}
    evidence = {**sql.evidence, **{k: v for k, v in attr.evidence.items()}}
    return ctx, charts, {k: evidence[k] for k in ctx["evidence_ids"]}, dict(lender=L, origin=O, run_id=rid)
