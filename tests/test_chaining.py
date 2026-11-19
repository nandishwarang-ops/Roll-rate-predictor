import sys, pathlib, duckdb, numpy as np, pandas as pd; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import chaining as C
ok = lambda n, c: print(("PASS " if c else "FAIL ") + n) or c
root = pathlib.Path(__file__).resolve().parent.parent; con = duckdb.connect(str(root / "rollrate.duckdb"), read_only=True); q = lambda s: con.sql(s).df(); r = []
# ---- toy: conservation and a hand-computable chain
S = np.zeros((12, 5)); S[0] = [1000, 100, 50, 20, 10]; M = np.zeros((3, 12, 5, 7))
for h in range(3):
    for s in range(12):
        M[h, s, 0] = [.95, .04, 0, 0, 0, .01, 0]; M[h, s, 1] = [.5, .15, .35, 0, 0, 0, 0]; M[h, s, 2] = [.1, .2, .2, .5, 0, 0, 0]; M[h, s, 3] = [.1, 0, .2, .2, .5, 0, 0]; M[h, s, 4] = [.02, 0, 0, .02, .85, .01, .10]
inflow = np.zeros(12); inflow[0] = 30
stock, flows = C.chain(S, M, inflow)
r += [ok("hand-computed first step: 1-30 bucket = 1000*.04 + 100*.15 + 50*.2 = 65", abs(stock[1][0, 1] - 65) < 1e-9)]
r += [ok("NPA additions month 1 = 20*.5 = 10 loans entering 90+", abs(C.outlook(stock, flows, np.ones((12, 5)))["npa_additions"][0] - 10) < 1e-9)]
tot_in = S[0].sum() + 30; step1 = stock[1][0].sum() + flows[0][0, :, 5].sum() + flows[0][0, :, 6].sum()
r += [ok("accounts conserved: live + closed + written off = start + new loans", abs(step1 - tot_in) < 1e-9)]
# ---- real data identity: chaining the ACTUAL rates and actual inflow must reproduce the actual stock (validates the plumbing)
mart = con.sql("select * from mart.transitions_segment").df(); mart["month_date"] = pd.to_datetime(mart.month_date); origin = "2025-06-01"
for lender in ["LENDER_A", "LENDER_B", "LENDER_C"]:
    state, avg = C.get_state(q, lender, origin); fc = mart[(mart.lender_id == lender) & (mart.month_date > pd.Timestamp(origin))].copy()
    fc["h"] = fc.month_date.dt.month - 6; fc = fc.rename(columns={"rate_count": "fc_rate"})
    act_new = q(f"select month_date, product_type, region, count(*) n from d1_account_monthly where lender_id='{lender}' and bucket_prev='NEW' and month_date > date '{origin}' group by all"); act_new["month_date"] = pd.to_datetime(act_new.month_date)
    Mx = C.matrices(fc, lender); stock = np.zeros((4, 12, 5)); stock[0] = state; idx = {s: i for i, s in enumerate(C.segments())}
    for h in range(3):
        fl = stock[h][:, :, None] * Mx[h]; stock[h + 1] = fl[:, :, :5].sum(1); m = pd.Timestamp(origin) + pd.DateOffset(months=h + 1)
        for x in act_new[act_new.month_date == m].itertuples(): stock[h + 1][idx[(x.product_type, x.region)], 0] += x.n
    actual = q(f"select month_date, count(*) filter (where bucket_curr='90+') npa, count(*) filter (where bucket_curr='CURRENT') cur from d1_account_monthly where lender_id='{lender}' and month_date > date '{origin}' group by 1 order by 1")
    npa_err = np.abs(stock[1:, :, 4].sum(1) - actual.npa.values).max(); cur_err = np.abs(stock[1:, :, 0].sum(1) - actual.cur.values).max()
    r += [ok(f"{lender}: chaining actual rates reproduces actual 90+ and CURRENT stock (max error {npa_err:.2f} / {cur_err:.2f} accounts)", npa_err < 1.0 and cur_err < 1.0)]
# ---- real backtest: forecast matrices (bake-off ensemble) chained from every origin, vs holding the stock flat
bo = con.sql("select * from mart.bakeoff_forecasts where model='ensemble'").df(); bo["origin"] = pd.to_datetime(bo.origin); rows = []
for o in sorted(bo.origin.unique()):
    o = pd.Timestamp(o)
    for lender in ["LENDER_A", "LENDER_B", "LENDER_C"]:
        out, (stock, flows) = C.run(q, lender, str(o.date()), bo[bo.origin == o], rate_col="fc_rate")
        flat = C.get_state(q, lender, str(o.date()))[0][:, 4].sum()
        for h in (1, 2, 3):
            m = o + pd.DateOffset(months=h)
            if m > pd.Timestamp("2025-09-01"): continue
            a = q(f"select count(*) filter (where bucket_curr='90+') npa, count(*) filter (where bucket_prev in ('CURRENT','1-30','31-60','61-90') and bucket_curr='90+') adds from d1_account_monthly where lender_id='{lender}' and month_date=date '{m.date()}'").iloc[0]
            rows.append(dict(origin=str(o.date())[:7], lender=lender, h=h, actual_npa=a.npa, chain_npa=out.npa_accounts[h - 1], flat_npa=flat, actual_adds=a.adds, chain_adds=out.npa_additions[h - 1]))
bt = pd.DataFrame(rows); bt["chain_err"] = (bt.chain_npa - bt.actual_npa).abs() / bt.actual_npa; bt["flat_err"] = (bt.flat_npa - bt.actual_npa).abs() / bt.actual_npa; bt["adds_err"] = (bt.chain_adds - bt.actual_adds).abs() / bt.actual_adds
s = bt.groupby("h")[["chain_err", "flat_err", "adds_err"]].mean(); print((100 * s).round(2).rename(columns={"chain_err": "NPA stock error % (chain)", "flat_err": "NPA stock error % (hold flat)", "adds_err": "NPA additions error %"}).to_string())
bias_adds = (bt.chain_adds.sum() - bt.actual_adds.sum()) / bt.actual_adds.sum(); print(f"    NPA additions bias over {len(bt)} lender-origin-horizon points: {bias_adds:+.1%}")
r += [ok(f"chained NPA stock is closer to actuals than holding the stock flat at every horizon", all(s.chain_err[h] < s.flat_err[h] for h in (1, 2, 3)))]
r += [ok("one-month NPA additions within 10% on average", s.adds_err[1] < 0.10)]
(root / "docs/chaining_backtest.md").write_text("# Chaining backtest (bake-off ensemble matrices, Oct 2024 - Jun 2025 origins)\n\n" + (100 * s).round(2).to_markdown() + f"\n\nNPA additions bias: {bias_adds:+.1%} over {len(bt)} points.\n\n" + bt.round(3).to_markdown(index=False))
# ---- scenarios move the outlook in the right direction
Mh = M.copy(); Mh[:, :, 3, 4] += 0.1; Mh[:, :, 3, 3] -= 0.1; s2, f2 = C.chain(S, Mh, inflow); a0 = C.outlook(stock=C.chain(S, M, inflow)[0], flows=C.chain(S, M, inflow)[1], avg_pos=np.ones((12, 5))); a1 = C.outlook(s2, f2, np.ones((12, 5)))
r += [ok("higher 61-90 roll-forward raises NPA additions and NPA stock", a1.npa_additions[0] > a0.npa_additions[0] and a1.npa_accounts[2] > a0.npa_accounts[2])]
sys.exit(0 if all(r) else 1)
