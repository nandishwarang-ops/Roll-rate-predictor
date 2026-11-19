"""Section 29a: can a better combination of the existing models close the gap to the 30% bar? Leave-one-origin-out weight search on the bake-off forecasts
(no refitting): weights on (ets, sarimax, gbm, naive) on a 0.1 grid, chosen on 8 origins and scored on the held-out one, so the reported MAPE is out-of-origin."""
import duckdb, itertools, json, pathlib, numpy as np, pandas as pd
root = pathlib.Path(__file__).resolve().parent.parent; con = duckdb.connect(str(root / "rollrate.duckdb"), read_only=True)
K = ["lender_id", "product_type", "region", "bucket_from", "bucket_to", "month_date", "h", "origin"]; MODELS = ["ets", "sarimax", "gbm", "naive"]
bo = con.sql("select model, " + ",".join(K) + ", fc_rate from mart.bakeoff_forecasts").df(); bo["month_date"] = pd.to_datetime(bo.month_date); bo["origin"] = pd.to_datetime(bo.origin)
act = con.sql("select lender_id, product_type, region, bucket_from, bucket_to, month_date, rate_count, opening_accounts from mart.transitions_segment").df(); act["month_date"] = pd.to_datetime(act.month_date)
piv = bo.pivot_table(index=K, columns="model", values="fc_rate").reset_index(); d = piv.merge(act, on=K[:6]); d = d[(d.rate_count > 0) & (d.opening_accounts >= 30)].reset_index(drop=True)
y = d.rate_count.values; F = {m: d[m].values for m in MODELS + ["snaive"]}; org = d.origin.values; h = d.h.values
ape = lambda p: np.abs(p - y) / y
grid = [w for w in itertools.product(np.arange(0, 1.01, 0.1), repeat=4) if abs(sum(w) - 1) < 1e-9]
P = {w: sum(wi * F[m] for wi, m in zip(w, MODELS)) for w in grid}; A = {w: ape(P[w]) for w in grid}
eq = ape(sum(F[m] for m in MODELS[:3]) / 3); sn = ape(F["snaive"]); res = []
for o in np.unique(org):
    tr, te = org != o, org == o; best = min(grid, key=lambda w: A[w][tr].mean()); res.append(dict(origin=str(pd.Timestamp(o).date())[:7], weights=dict(zip(MODELS, np.round(best, 1))), tuned=A[best][te].mean(), equal=eq[te].mean(), snaive=sn[te].mean()))
r = pd.DataFrame(res); out = dict(tuned=float(r.tuned.mean()), equal=float(r.equal.mean()), snaive=float(r.snaive.mean()))
allbest = min(grid, key=lambda w: A[w].mean()); out["in_sample_best"] = dict(weights=dict(zip(MODELS, np.round(allbest, 1))), mape=float(A[allbest].mean()))
for k in ("tuned", "equal"): out[f"{k}_vs_snaive"] = 1 - out[k] / out["snaive"]
byh = {int(x): dict(tuned=float(A[allbest][h == x].mean()), equal=float(eq[h == x].mean()), snaive=float(sn[h == x].mean())) for x in (1, 2, 3)}; out["by_horizon_in_sample"] = byh
print(r.round(3).to_string(index=False)); print(json.dumps(out, indent=1)); (root / "src/ensemble_tuning.json").write_text(json.dumps(out, indent=1))
