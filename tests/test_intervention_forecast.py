import sys, pathlib, tempfile, duckdb, numpy as np, pandas as pd; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import intervention_forecast as F, driver_registry as R, classifier as C
from guarded_sql import GuardedSQL
from attribution import AttributionTool
ok = lambda n, c: print(("PASS " if c else "FAIL ") + n) or c
r = []; root = pathlib.Path(__file__).resolve().parent.parent
# ---- matrix surgery on a toy row set
rows = []
for b, to, p in [("31-60", "1-30", .2), ("31-60", "31-60", .2), ("31-60", "61-90", .5), ("31-60", "CURRENT", .1)]:
    rows.append(dict(lender_id="L", product_type="P", region="W", bucket_from=b, bucket_to=to, month_date=pd.Timestamp("2025-07-01"), h=1, fc_rate=p))
df = pd.DataFrame(rows); pool = dict(lender="L", bucket_from="31-60", product_type="P", region="W")
up = F.shift_rows(df, "fc_rate", pool, "roll_forward", 0.10); rf = up[up.bucket_to == "61-90"].fc_rate.sum()
r += [ok(f"+10pp roll-forward applied exactly (0.50 -> {rf:.2f}) and row still sums to 1", abs(rf - 0.60) < 1e-9 and abs(up.fc_rate.sum() - 1) < 1e-9)]
dn = F.shift_rows(df, "fc_rate", pool, "roll_forward", -0.80); r += [ok("shift cannot push a rate below 0; row still sums to 1", dn[dn.bucket_to == "61-90"].fc_rate.sum() >= 0 and abs(dn.fc_rate.sum() - 1) < 1e-9)]
cu = F.shift_rows(df, "fc_rate", pool, "cure", 0.05); r += [ok("cure shift raises cure cells and keeps the row at 1", abs(cu[cu.bucket_to.isin(["1-30", "CURRENT"])].fc_rate.sum() - 0.35) < 1e-9 and abs(cu.fc_rate.sum() - 1) < 1e-9)]
# ---- profiles
T = "2025-06-01"; step = dict(shape="STEP", start_month="2025-03-01", lag_months=0); 
r += [ok("STEP holds the level", [round(e, 4) for _, e in F.profile(step, 0.02, T)] == [0.02] * 3)]
r += [ok("DOT is gone after the origin", [e for _, e in F.profile(dict(shape="DOT", start_month="2025-06-01"), 0.02, T)] == [0.0] * 3)]
tr = [e for _, e in F.profile(dict(shape="TRANSIENT", half_life_months=1.0, start_month="2025-06-01"), 0.02, T)]; r += [ok(f"TRANSIENT halves every half-life {[round(x,4) for x in tr]}", abs(tr[0] - 0.01) < 1e-9 and abs(tr[1] - 0.005) < 1e-9)]
te = [e for _, e in F.profile(dict(shape="TRANSIENT", end_month="2025-07-01", start_month="2025-05-01"), 0.02, T)]; r += [ok("TRANSIENT with known end stops after that month", te == [0.02, 0.0, 0.0])]
lagp = [e for _, e in F.profile(dict(shape="STEP", start_month="2025-05-01", lag_months=3), 0.01, T)]; r += [ok(f"lagged STEP keeps ramping to the full effect {[round(x,4) for x in lagp]}", lagp[0] > 0.01 and lagp[-1] > lagp[0])]
# ---- real data backtest: Lender A WEST 31-60 agency attrition (started Mar 2025), forecast from June, score on Jul-Sep actuals
con = duckdb.connect(str(root / "rollrate.duckdb"), read_only=True); st = pathlib.Path(tempfile.mkdtemp()) / "state.duckdb"
g = GuardedSQL("LENDER_A", "2025-06-01"); attr = AttributionTool("LENDER_A", "2025-06-01", run_id="fc_test", g=g)
a = attr("2025-05-01", "31-60", "roll_forward", {"agency": {"dimension": "agency_id", "values": ["AG_W_TELE_02"]}}, region="WEST", recent_months=1, baseline_lag=2)
res0 = dict(investigation=dict(month="2025-05-01", node="LENDER_A|WEST", metric="roll_forward", bucket_from="31-60"), findings=dict(drivers=[dict(what="tele agency AG_W_TELE_02 staff loss", where=dict(lender="LENDER_A", region="WEST", sub_slice="agency AG_W_TELE_02"),
            when=dict(start_month="2025-03"), category="operational", evidence_ids=[a["attribution_id"]], attribution_id=a["attribution_id"], confidence="high")]))
did = R.register_from_result(res0, attr.evidence, st)[0][0]; R.recheck_all("LENDER_A", "2025-06-01", attr, st)
out = F.forecast_with_interventions("LENDER_A", "2025-06-01", [did], con, g, attr, state=st)
pool = out["drivers"][0]["pool"]; metric = pool["metric"]; act = F.pool_actual(con, pool, metric)
print("    driver status:", out["drivers"][0]["status"], "| scenarios:", [(s["name"], s["weight"]) for s in out["drivers"][0]["scenarios"]], "| measured effect (pp):", out["drivers"][0]["measured_effect_pp"])
tab = pd.DataFrame({"actual": act.reindex(pd.to_datetime(["2025-07-01", "2025-08-01", "2025-09-01"]))}).copy()
for k in ("unadjusted", "counterfactual", "blip", "adjusted", "lasting"): tab[k] = F.pool_metric(out[k], con, pool, metric, "2025-06-01")
print((100 * tab).round(2).to_string())
err = lambda k: float((tab[k] - tab.actual).abs().mean())
print("    mean abs error on the pool (pp):", {k: round(100 * err(k), 2) for k in ("unadjusted", "counterfactual", "blip", "adjusted", "lasting")})
r += [ok("rows of every variant sum to 1", all(abs(out[k].groupby(["lender_id", "product_type", "region", "bucket_from", "month_date"]).fc_rate.sum() - 1).max() < 1e-6 for k in ("unadjusted", "adjusted", "lasting", "blip")))]
r += [ok("weighted forecast lies between the blip and lasting cases", all(min(tab.blip[i], tab.lasting[i]) - 1e-9 <= tab.adjusted[i] <= max(tab.blip[i], tab.lasting[i]) + 1e-9 for i in range(3)))]
bias = lambda k: float((tab[k] - tab.actual).mean())
r += [ok("driver is real: removing it (counterfactual) makes the forecast worse than the unadjusted baseline", err("counterfactual") > err("unadjusted"))]
r += [ok(f"adding the measured effect back reduces the baseline's systematic under-forecast ({100*bias('unadjusted'):.2f} -> {100*bias('adjusted'):.2f}pp)", abs(bias("adjusted")) < abs(bias("unadjusted")))]
r += [ok("run id, parquet and json saved for citation", (root / "outputs/forecasts" / f"{out['run_id']}.parquet").exists() and out["run_id"].startswith("fc_LENDER_A_2025-06_"))]
sys.exit(0 if all(r) else 1)
