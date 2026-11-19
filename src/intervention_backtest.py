"""Honest check of section 19 on real data: Lender A WEST 31-60 agency attrition (STEP from Mar 2025).
For origins Apr/May/Jun 2025 the driver is registered as a NEW (open) driver at the origin, classified, and forecast 3 months ahead;
errors are compared with the unadjusted ensemble on the affected pool. Pool months have only ~600 accounts, so each point carries ~2pp of sampling noise."""
import sys, pathlib, tempfile, duckdb, pandas as pd, numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import intervention_forecast as F, driver_registry as R, classifier as C
from guarded_sql import GuardedSQL
from attribution import AttributionTool
root = pathlib.Path(__file__).resolve().parent.parent; con = duckdb.connect(str(root / "rollrate.duckdb"), read_only=True); rows = []
for origin in ["2025-04-01", "2025-05-01", "2025-06-01"]:
    st = pathlib.Path(tempfile.mkdtemp()) / "state.duckdb"; g = GuardedSQL("LENDER_A", origin); attr = AttributionTool("LENDER_A", origin, run_id="bt", g=g)
    a = attr(origin, "31-60", "roll_forward", {"agency": {"dimension": "agency_id", "values": ["AG_W_TELE_02"]}}, region="WEST", recent_months=1, baseline_lag=R.months_between("2025-03-01", origin))
    res0 = dict(investigation=dict(month=origin, node="LENDER_A|WEST", metric="roll_forward", bucket_from="31-60"), findings=dict(drivers=[dict(what="tele agency AG_W_TELE_02 staff loss", where=dict(lender="LENDER_A", region="WEST", sub_slice="agency AG_W_TELE_02"),
        when=dict(start_month="2025-03"), category="operational", evidence_ids=[a["attribution_id"]], attribution_id=a["attribution_id"], confidence="high")]))
    did = R.register_from_result(res0, attr.evidence, st)[0][0]; cls = C.classify_driver(did, g, origin, state=st, ongoing=True)
    out = F.forecast_with_interventions("LENDER_A", origin, [did], con, g, attr, classifications={did: cls}, state=st)
    pool = out["drivers"][0]["pool"]; act = F.pool_actual(con, pool, "roll_forward"); fut = [pd.Timestamp(origin) + pd.DateOffset(months=h) for h in (1, 2, 3)]
    for h, m in enumerate(fut, 1):
        if m not in act.index: continue
        row = dict(origin=origin[:7], h=h, month=str(m)[:7], actual=100 * act[m])
        for k in ("unadjusted", "counterfactual", "blip", "adjusted", "lasting"): row[k] = 100 * F.pool_metric(out[k], con, pool, "roll_forward", origin)[m]
        rows.append(row); print(origin[:7], h, {k: round(v, 2) for k, v in row.items() if k not in ("origin", "month")}, flush=True)
d = pd.DataFrame(rows); cols = ["unadjusted", "counterfactual", "blip", "adjusted", "lasting"]
mae = {k: round(float((d[k] - d.actual).abs().mean()), 2) for k in cols}; bias = {k: round(float((d[k] - d.actual).mean()), 2) for k in cols}
by_h = {h: {k: round(float((g_[k] - g_.actual).abs().mean()), 2) for k in ("unadjusted", "adjusted")} for h, g_ in d.groupby("h")}
print("\nMAE (pp):", mae, "\nbias (pp, forecast - actual):", bias, "\nMAE by horizon, unadjusted vs adjusted:", by_h)
md = ["# Intervention forecast backtest (Lender A WEST 31-60 agency attrition)\n", f"Origins Apr/May/Jun 2025, horizon 1-3, {len(d)} forecast points. Pool months hold ~600 accounts, so each actual carries ~2pp sampling noise: treat differences below ~1pp as inconclusive.\n",
      d.round(2).to_markdown(index=False), "", f"MAE (pp): {mae}", "", f"Bias (pp): {bias}", "", f"MAE by horizon (unadjusted vs adjusted): {by_h}"]
(root / "docs/intervention_backtest.md").write_text("\n".join(md))
