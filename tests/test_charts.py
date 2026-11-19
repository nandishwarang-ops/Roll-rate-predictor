import sys, pathlib, duckdb, numpy as np, pandas as pd; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import charts as CH, rollup as RU, ranges as RG, chaining as C
ok = lambda n, c: print(("PASS " if c else "FAIL ") + n) or c
root = pathlib.Path(__file__).resolve().parent.parent; con = duckdb.connect(str(root / "rollrate.duckdb"), read_only=True); q = lambda s: con.sql(s).df(); r = []; out = root / "outputs/charts/test"
L, O = "LENDER_A", "2025-06-01"; bo = con.sql("select * from mart.bakeoff_forecasts where model='ensemble'").df(); bo["origin"] = pd.to_datetime(bo.origin); fc = bo[bo.origin == pd.Timestamp(O)]
summary, sim = RG.ranged_outlook(q, L, O, [(fc, 1.0)], con, N=1500, seed=2); ru = RU.build_rollup(q, L, O, sim)
def hist_rate(bucket, metric="roll_forward"):
    d = q(f"select month_date, sum({metric}*opening_accounts)/sum(opening_accounts) v from mart.moves_segment where lender_id='{L}' and bucket_from='{bucket}' and month_date <= date '{O}' group by 1 order by 1"); d["month_date"] = pd.to_datetime(d.month_date); return d.set_index("month_date").v
def fc_rate(bucket, metric="roll_forward"):
    x = ru[(ru.level == "lender") & (ru.metric == f"{metric}_{bucket}")].copy(); x["m"] = pd.Timestamp(O) + x.h.map(lambda h: pd.DateOffset(months=int(h))); return x.set_index("m")
h31, f31 = hist_rate("31-60"), fc_rate("31-60"); ev = q("select event_start_date d, event_name n from event_calendar where lender_id is null or lender_id='LENDER_A' order by 1").values.tolist()
p1 = CH.rate_forecast(h31.tail(18), f31["mean"] * 0.99, f31["p50"], f31[["p10", "p90"]], out / "rate_forecast.png", "Lender A, all products", "31-60 roll-forward rate", ev)
npa_h = q(f"select month_date, count(*) n from d1_account_monthly where lender_id='{L}' and bucket_curr='90+' and month_date <= date '{O}' group by 1 order by 1"); npa_h["month_date"] = pd.to_datetime(npa_h.month_date); npa_h = npa_h.set_index("month_date").n.tail(18)
nf = ru[(ru.level == "lender") & (ru.metric == "npa_accounts")].copy(); nf["m"] = pd.Timestamp(O) + nf.h.map(lambda h: pd.DateOffset(months=int(h))); nf = nf.set_index("m")
p2 = CH.npa_outlook(npa_h, nf["p50"], nf[["p10", "p90"]], out / "npa_outlook.png", "Lender A", {"blip": nf["p50"] * 0.99, "lasting": nf["p50"] * 1.01})
ss, tot = RU.what_moved(q, "LENDER_B", "2025-03-01", "1-30", "cure"); p3 = CH.what_moved(ss, tot, out / "what_moved.png", "Lender B", "1-30 cure rate", pd.Timestamp("2025-03-01"))
bk = ["CURRENT", "1-30", "31-60", "61-90"]; p4 = CH.bucket_panels({b: hist_rate(b).tail(18) for b in bk}, {b: fc_rate(b)["p50"] for b in bk}, {b: fc_rate(b)[["p10", "p90"]] for b in bk}, out / "bucket_panels.png", "Lender A", "roll-forward rate")
for p in (p1, p2, p3, p4):
    P = pathlib.Path(p); r += [ok(f"{P.name}: image, table view (CSV) and alt text written", P.exists() and P.stat().st_size > 20000 and P.with_suffix(".csv").exists() and P.with_suffix(".alt.txt").exists())]
t = pd.read_csv(pathlib.Path(p1).with_suffix(".csv")); adj = t[(t.series == "adjusted")].value_pct.iloc[-1]; src = 100 * f31["p50"].iloc[-1]
r += [ok(f"number on the chart equals the source table ({adj:.2f} vs {src:.2f})", abs(adj - src) < 1e-9)]
alt = pathlib.Path(p1).with_suffix(".alt.txt").read_text(); r += [ok("title/alt text carry the computed forecast and range", f"{src:.1f}%" in alt and "80% range" in alt)]
t3 = pd.read_csv(pathlib.Path(p3).with_suffix(".csv")); r += [ok("what-moved chart table sums to the displayed top contributions", abs(t3.total_pp.sum() - ss.head(8).total_pp.sum()) < 1e-9)]
sys.exit(0 if all(r) else 1)
