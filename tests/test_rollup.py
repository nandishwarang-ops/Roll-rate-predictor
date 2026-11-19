import sys, pathlib, duckdb, numpy as np, pandas as pd; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import rollup as RU, ranges as RG, chaining as C
ok = lambda n, c: print(("PASS " if c else "FAIL ") + n) or c
root = pathlib.Path(__file__).resolve().parent.parent; con = duckdb.connect(str(root / "rollrate.duckdb"), read_only=True); q = lambda s: con.sql(s).df(); r = []
bo = con.sql("select * from mart.bakeoff_forecasts where model='ensemble'").df(); bo["origin"] = pd.to_datetime(bo.origin); fc = bo[bo.origin == pd.Timestamp("2025-06-01")]
summary, sim = RG.ranged_outlook(q, "LENDER_B", "2025-06-01", [(fc, 1.0)], con, N=1500, seed=5)
ru = RU.build_rollup(q, "LENDER_B", "2025-06-01", sim); print("    rollup rows:", len(ru), "| nodes:", ru.groupby("level").node.nunique().to_dict(), "| metrics:", ru.metric.nunique())
r += [ok("20 nodes (1 lender + 3 products + 4 regions + 12 segments)", ru.node.nunique() == 20 and set(ru.level) == {"lender", "product", "region", "segment"})]
rc = RU.reconcile(ru); r += [ok(f"additive metrics reconcile at every level and horizon ({len(rc)} checks)", bool(rc.ok.all()))]
# rates recomputed from sums, not averaged: lender roll-forward rate == opening-weighted mean of segment rates in the same draws
a = RU.draws(sim, np.ones(12, bool))["roll_forward_31-60"]; num = sum(RU.draws(sim, m)["roll_forward_31-60"] * sim["stock"][:, :-1][:, :, m, 2].sum(-1) for _, _, m in [n for n in RU.nodes() if n[0] == "segment"])
den = sim["stock"][:, :-1, :, 2].sum(-1); r += [ok("lender rate equals the weighted sum of its segments' rates draw by draw", np.allclose(np.nan_to_num(num / den), np.nan_to_num(a), atol=1e-9))]
r += [ok("P10 <= P50 <= P90 for every node and metric", bool(((ru.p10 <= ru.p50 + 1e-9) & (ru.p50 <= ru.p90 + 1e-9)).all()))]
# actuals at the origin agree with the source data
act = ru[(ru.level == "lender") & (ru.metric == "npa_accounts") & (ru.h == 1)].actual_origin.iloc[0]; src = q("select count(*) n from d1_account_monthly where lender_id='LENDER_B' and month_date=date '2025-06-01' and bucket_curr='90+'").n[0]
r += [ok(f"actual NPA stock at origin equals D1 ({act:.0f} vs {src})", abs(act - src) < 1e-6)]
rf = ru[(ru.level == "lender") & (ru.metric == "roll_forward_31-60") & (ru.h == 1)].actual_origin.iloc[0]; src = q("select roll_forward from mart.moves_lender where lender_id='LENDER_B' and month_date=date '2025-06-01' and bucket_from='31-60'").roll_forward[0]
r += [ok(f"actual 31-60 roll-forward at origin equals the lender-level matrix ({rf:.4f} vs {src:.4f})", abs(rf - src) < 1e-9)]
# the same simulation as section 21: P50 for the lender NPA stock matches
s21 = summary[(summary.group == "lender") & (summary.metric == "npa_accounts")].set_index("h").p50; me = ru[(ru.level == "lender") & (ru.metric == "npa_accounts")].set_index("h").p50
r += [ok("lender-level numbers equal section 21's output (one source of truth)", np.allclose(s21.values, me.values))]
# shift-share is exact
ss, tot = RU.what_moved(q, "LENDER_B", "2025-03-01", "1-30", "cure"); r += [ok(f"shift-share: segment contributions add up exactly to the lender change ({ss.total_pp.sum():.3f} vs {tot:.3f}pp); mix {ss.mix_pp.sum():.2f} + rate {ss.rate_pp.sum():.2f}", abs(ss.total_pp.sum() - tot) < 1e-9)]
actual_chg = 100 * (q("select sum(cure*opening_accounts)/sum(opening_accounts) v from mart.moves_segment where lender_id='LENDER_B' and month_date=date '2025-03-01' and bucket_from='1-30'").v[0] - q("select sum(cure*opening_accounts)/sum(opening_accounts) v from mart.moves_segment where lender_id='LENDER_B' and month_date=date '2025-02-01' and bucket_from='1-30'").v[0])
r += [ok(f"and equal the independently computed change ({actual_chg:.3f}pp)", abs(actual_chg - tot) < 1e-9)]
print("    top movers, Lender B 1-30 cure Feb->Mar 2025:", ss.head(3).total_pp.round(2).to_dict())
p = RU.save(ru, "LENDER_B", "2025-06-01"); r += [ok("roll-up saved for the pack", p.exists())]
sys.exit(0 if all(r) else 1)
