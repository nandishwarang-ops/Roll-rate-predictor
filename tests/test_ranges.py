import sys, pathlib, json, duckdb, numpy as np, pandas as pd; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import ranges as RG, chaining as C
ok = lambda n, c: print(("PASS " if c else "FAIL ") + n) or c
root = pathlib.Path(__file__).resolve().parent.parent; con = duckdb.connect(str(root / "rollrate.duckdb"), read_only=True); q = lambda s: con.sql(s).df(); r = []
bo = con.sql("select * from mart.bakeoff_forecasts where model='ensemble'").df(); bo["origin"] = pd.to_datetime(bo.origin); fc = bo[bo.origin == pd.Timestamp("2025-06-01")]
s1, sim = RG.ranged_outlook(q, "LENDER_A", "2025-06-01", [(fc, 1.0)], con, N=1500, seed=3); s2, _ = RG.ranged_outlook(q, "LENDER_A", "2025-06-01", [(fc, 1.0)], con, N=1500, seed=3)
r += [ok("same seed gives identical ranges (reproducible)", s1.equals(s2))]
g = s1[(s1.group == "lender") & (s1.metric == "npa_accounts")].set_index("h"); w = (g.p90 - g.p10) / g.p50
r += [ok(f"range widens with horizon (width % of median: {', '.join(f'{100*x:.1f}' for x in w)})", w[1] < w[2] < w[3])]
r += [ok("P10 <= P50 <= P90 everywhere", bool(((s1.p10 <= s1.p50 + 1e-9) & (s1.p50 <= s1.p90 + 1e-9)).all()))]
agg = RG.aggregates(sim); segs = C.segments(); tot = sum(RG.aggregates(sim, np.array([s[0] == p for s in segs]))["npa_accounts"] for p in ["BUSINESS_LOAN", "PERSONAL_LOAN", "TWO_WHEELER"])
r += [ok("roll-ups reconcile draw by draw: sum of products == lender total", np.allclose(tot, agg["npa_accounts"]))]
tot_r = sum(RG.aggregates(sim, np.array([s[1] == x for s in segs]))["npa_principal"] for x in ["EAST", "NORTH", "SOUTH", "WEST"]); r += [ok("regions sum to the lender total (principal)", np.allclose(tot_r, agg["npa_principal"]))]
# point forecast sits inside its own range
state, ap = C.get_state(q, "LENDER_A", "2025-06-01"); infl, _ = C.get_inflow(q, "LENDER_A", "2025-06-01"); st, fl = C.chain(state, C.matrices(fc, "LENDER_A"), infl)
r += [ok("deterministic chained NPA stock lies inside the simulated 80% range", all(g.p10[h] <= st[h][:, 4].sum() <= g.p90[h] for h in (1, 2, 3)))]
# scenario mixture widens the range
bump = fc.copy(); m = (bump.bucket_from == "31-60") & (bump.bucket_to == "61-90"); bump.loc[m, "fc_rate"] *= 1.15
mixed, _ = RG.ranged_outlook(q, "LENDER_A", "2025-06-01", [(fc, 0.5), (bump, 0.5)], con, N=1500, seed=3); gm = mixed[(mixed.group == "lender") & (mixed.metric == "npa_accounts")].set_index("h")
r += [ok("scenario uncertainty (blip vs lasting) widens the 3-month range", (gm.p90[3] - gm.p10[3]) > (g.p90[3] - g.p10[3]))]
# calibration evidence on file and in a sane band
cal = json.loads((root / "src/range_calibration.json").read_text()); txt = (root / "docs/range_calibration.md").read_text()
r += [ok(f"calibration saved (lambda {cal['lambda']}, phi {cal['phi']}) with the coverage table", len(cal["lambda"]) == 3 and "Calibrated coverage" in txt)]
cov = [float(x) for line in txt.split("Calibrated coverage (%):")[1].split("Mean 80%")[0].splitlines() if line.startswith("| npa") for x in line.split("|")[2:5]]
r += [ok(f"leave-one-origin-out coverage of the 80% range is within 65-95% everywhere ({cov})", all(65 <= c <= 95 for c in cov))]
sys.exit(0 if all(r) else 1)
