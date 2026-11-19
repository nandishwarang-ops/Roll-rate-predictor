"""Section 9: model bake-off and selection (rolling-origin backtest on the PUBLIC data).
Origins 2024-10..2025-06, each forecasting 3 months ahead, for: snaive, naive, ets, sarimax, gbm and an equal-weight
ensemble of the three real models. Scored on (a) every transition cell (MAPE, WAPE) and (b) the business-facing
roll-forward rate per bucket. Winner = lowest cell MAPE, required to beat seasonal-naive by >= 30%."""
import duckdb, pandas as pd, numpy as np, json, pathlib, time, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from forecast_models import forecast, KEYS
root = pathlib.Path(__file__).resolve().parent.parent
ORIGINS = pd.date_range("2024-10-01", "2025-06-01", freq="MS")
REAL = ["ets", "sarimax", "gbm"]; ALL = ["snaive", "naive"] + REAL + ["ensemble"]
SEV = {"CURRENT": 0, "1-30": 1, "31-60": 2, "61-90": 3, "90+": 4}
def run(con):
    parts = []
    for o in ORIGINS:
        t = time.time(); fcs = {m: forecast(m, con, str(o.date())) for m in ["snaive", "naive"] + REAL}
        ens = pd.concat([fcs[m] for m in REAL]).groupby(KEYS + ["month_date", "h"], as_index=False)["fc_rate"].mean()
        fcs["ensemble"] = ens
        for m, f in fcs.items(): parts.append(f.assign(model=m, origin=o))
        print(f"origin {o.date()} done in {time.time()-t:.0f}s", flush=True)
    return pd.concat(parts, ignore_index=True)
def evaluate(con, fc, min_open=30):
    act = con.sql("select lender_id, product_type, region, month_date, bucket_from, bucket_to, rate_count, opening_accounts from mart.transitions_segment").df()
    act["month_date"] = pd.to_datetime(act.month_date)
    m = fc.merge(act, on=KEYS[:3] + ["month_date", "bucket_from", "bucket_to"])
    m["ape"] = np.where((m.rate_count > 0) & (m.opening_accounts >= min_open), abs(m.fc_rate - m.rate_count) / m.rate_count.replace(0, np.nan), np.nan)
    m["abs_w"] = abs(m.fc_rate - m.rate_count) * m.opening_accounts; m["act_w"] = m.rate_count * m.opening_accounts
    cell = m.groupby(["model"]).agg(mape=("ape", "mean"), wape=("abs_w", "sum"), act=("act_w", "sum"), n=("ape", "count"))
    cell["wape"] = cell.wape / cell.act
    byh = m.groupby(["model", "h"]).ape.mean().unstack()
    # roll-forward rate per (segment, bucket_from, month): sum of forecast rate over strictly-worse non-terminal buckets
    m["sev_to"] = m.bucket_to.map(SEV); m["sev_from"] = m.bucket_from.map(SEV)
    fw = m[(m.sev_to > m.sev_from) & m.bucket_from.isin(["CURRENT", "1-30", "31-60", "61-90"])]
    g = fw.groupby(["model", "origin", "h", "lender_id", "product_type", "region", "bucket_from", "month_date"]).agg(
        fc=("fc_rate", "sum"), act=("rate_count", "sum"), op=("opening_accounts", "max")).reset_index()
    g = g[(g.act > 0) & (g.op >= min_open)]; g["ape"] = abs(g.fc - g.act) / g.act
    rf = g.groupby("model").ape.mean(); rfb = g.groupby(["model", "bucket_from"]).ape.mean().unstack()
    return cell, byh, rf, rfb
if __name__ == "__main__":
    con = duckdb.connect(str(root / "rollrate.duckdb"))
    fc = run(con)
    con.register("fc", fc); con.sql("create or replace table mart.bakeoff_forecasts as select * from fc")
    cell, byh, rf, rfb = evaluate(con, fc)
    base = cell.loc["snaive", "mape"]; cell["vs_snaive"] = 1 - cell.mape / base; cell["roll_fwd_mape"] = rf
    cell["rf_vs_snaive"] = 1 - rf / rf["snaive"]
    cell = cell.loc[ALL]; ok = cell[(cell.index != "snaive") & (cell.index != "naive")]
    winner = ok.mape.idxmin()
    md = ["# Model bake-off (rolling origin, public data)\n",
          f"Origins {ORIGINS[0].date()} … {ORIGINS[-1].date()} ({len(ORIGINS)} origins x 3 horizons). Lower MAPE is better; target >= 30% below seasonal-naive.\n",
          "## Overall\n", "| model | cells | cell MAPE | vs snaive | WAPE | roll-forward MAPE | vs snaive |", "|---|---|---|---|---|---|---|"]
    md += [f"| {m} | {int(r.n):,} | {r.mape:.1%} | {r.vs_snaive:+.1%} | {r.wape:.1%} | {r.roll_fwd_mape:.1%} | {r.rf_vs_snaive:+.1%} |" for m, r in cell.iterrows()]
    md += ["", "## Cell MAPE by horizon (months ahead)\n", "| model | h=1 | h=2 | h=3 |", "|---|---|---|---|"]
    md += [f"| {m} | " + " | ".join(f"{byh.loc[m, h]:.1%}" for h in [1, 2, 3]) + " |" for m in ALL]
    md += ["", "## Roll-forward MAPE by starting bucket\n", "| model | " + " | ".join(rfb.columns) + " |", "|---|" + "---|" * len(rfb.columns)]
    md += [f"| {m} | " + " | ".join(f"{rfb.loc[m, c]:.1%}" for c in rfb.columns) + " |" for m in ALL]
    md += ["", f"**Selected: `{winner}`** (cell MAPE {cell.loc[winner,'mape']:.1%}, {cell.loc[winner,'vs_snaive']:.0%} better than seasonal-naive)."]
    (root / "docs/model_bakeoff.md").write_text("\n".join(md))
    (root / "src/selected_model.json").write_text(json.dumps({"model": winner, "cell_mape": float(cell.loc[winner, "mape"]),
        "improvement_vs_snaive": float(cell.loc[winner, "vs_snaive"]), "components": REAL if winner == "ensemble" else [winner]}, indent=1))
    print("\n".join(md))
