import sys, pathlib, duckdb, numpy as np, pandas as pd; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import planted as P
ok = lambda n, c: print(("PASS " if c else "FAIL ") + n) or c
r = []; root = pathlib.Path(__file__).resolve().parent.parent
spec = dict(name="unit_a1", lender="LENDER_A", bucket="31-60", pool={"region": "WEST"}, slice_sql="agency_id='AG_W_TELE_01'", months={"2025-07-01": 1.0}, delta=0.10, d3=dict(kind="calls", frac=0.6))
path, truth = P.scenario_db(spec); t = truth[0]; c = duckdb.connect(str(path), read_only=True); o = duckdb.connect(str(root / "rollrate.duckdb"), read_only=True)
q = lambda con, s: con.sql(s).fetchone()
W = "lender_id='LENDER_A' and month_date=date '2025-07-01' and bucket_prev='31-60' and region='WEST'"
rf = lambda con, extra="": q(con, f"select count(*) filter (where ({P.SEV('bucket_curr')}) > ({P.SEV('bucket_prev')}) and bucket_curr in ('CURRENT','1-30','31-60','61-90','90+')) from main.d1_account_monthly where {W} {extra}")[0]
d_slice = rf(c, "and agency_id='AG_W_TELE_01'") - rf(o, "and agency_id='AG_W_TELE_01'"); d_rest = rf(c, "and agency_id<>'AG_W_TELE_01'") - rf(o, "and agency_id<>'AG_W_TELE_01'")
r += [ok(f"planted roll-forwards equal the requested number exactly ({d_slice} vs {t['flips']}; slice {t['n_slice']} accounts, +{t['slice_effect_pp']:.1f}pp)", d_slice == t["flips"] and abs(t["slice_effect_pp"] - 10.0) < 0.5)]
r += [ok("accounts outside the slice are untouched (the control group is clean)", d_rest == 0)]
r += [ok("rows stay consistent: every flipped account's dpd lies inside its new bucket", q(c, "select count(*) from main.d1_account_monthly where bucket_curr='61-90' and (dpd_curr<61 or dpd_curr>90)")[0] == q(o, "select count(*) from main.d1_account_monthly where lender_id='LENDER_A' and bucket_curr='61-90' and (dpd_curr<61 or dpd_curr>90) and month_date >= date '2024-04-01'")[0])]
calls = lambda con: q(con, "select count(*) from main.d3_collection_events where lender_id='LENDER_A' and month_date=date '2025-07-01' and channel='VOICE_CALL' and account_id in (select account_id from main.d1_account_monthly where " + W + " and agency_id='AG_W_TELE_01')")[0]
r += [ok(f"D3 footprint planted: about 60% of the slice's voice calls removed ({calls(c)} vs {calls(o)})", 0.35 < 1 - calls(c) / calls(o) < 0.65 and t["d3_removed"] > 0)]
bf = q(c, "select count(*) from (select lender_id,month_date,product_type,region,bucket_prev,bucket_curr,count(*) n from main.d1_account_monthly where bucket_prev<>'NEW' group by all) a full join main.bucket_flow_history b on a.lender_id=b.lender_id and a.month_date=b.month_date and a.product_type=b.product_type and a.region=b.region and a.bucket_prev=b.bucket_from and a.bucket_curr=b.bucket_to where a.n is distinct from b.account_count")[0]
r += [ok("bucket_flow_history rebuilt from the modified D1 reconciles exactly", bf == 0)]
r += [ok("transition matrices rebuilt in the scratch DB", q(c, "select count(*) from mart.moves_segment")[0] > 0)]
c.close()
inv = P.detect(path, spec, o); m = P.match(inv, spec, "2025-07-01")
print("    investigations in the planted month matching the pool:", m[["level", "node", "diff_pp", "z", "priority"]].round(2).to_dict("records")[:4])
r += [ok("the planted shift is detected at the planted month", len(m) >= 1)]
spec2 = dict(spec, name="unit_a1b"); path2, truth2 = P.scenario_db(spec2); chk = lambda pp: (lambda cc: (cc.sql("select sum(hash(account_id || month_date::varchar || bucket_curr)::HUGEINT) from main.d1_account_monthly").fetchone()[0], cc.close())[0])(duckdb.connect(str(pp), read_only=True))
r += [ok("ground truth is deterministic: planting twice gives byte-identical D1 outcomes", truth2[0]["flips"] == t["flips"] and chk(path) == chk(path2))]
sys.exit(0 if all(r) else 1)
