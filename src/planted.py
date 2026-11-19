"""Section 28: backtest harness with PLANTED shifts.
Real data has known seeded events, but to measure the system honestly (detection power, false flags, naming, size accuracy, shape classification) we need shifts whose
truth we control. For one lender we copy the data to a scratch DuckDB file and plant a shift in D1 (flip a chosen number of non-rolling accounts in a chosen slice to roll forward,
keeping dpd consistent) and, where the story needs it, in D3 (remove calls or field visits). bucket_flow_history and the transition matrices are then rebuilt from the modified D1,
so every downstream table agrees. The ground truth (slice, size, months) is kept in the spec and never given to the system.
Detection reuses section 10 with the ORIGINAL one-step forecasts (they only use history before the planted month, so they are unaffected by the planting)."""
import duckdb, shutil, pathlib, sys, json, time, itertools
import numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import detection, transition_matrix
root = pathlib.Path(__file__).resolve().parent.parent
DB = root / "rollrate.duckdb"; DIR = root / "outputs/planted"
NEXT = "case bucket_prev when 'CURRENT' then '1-30' when '1-30' then '31-60' when '31-60' then '61-90' when '61-90' then '90+' end"
NEXT_DPD = "case bucket_prev when 'CURRENT' then 5 when '1-30' then 35 when '31-60' then 65 when '61-90' then 95 end"
SEV = lambda c: f"case {c} when 'CURRENT' then 0 when '1-30' then 1 when '31-60' then 2 when '61-90' then 3 when '90+' then 4 end"
def build_base(lender, since="2024-04-01"):
    DIR.mkdir(parents=True, exist_ok=True); path = DIR / f"base_{lender}.duckdb"
    if path.exists(): return path
    c = duckdb.connect(str(path)); c.sql(f"attach '{DB}' as src (read_only)")
    for t in ["d1_account_monthly", "d3_collection_events", "bucket_flow_history"]: c.sql(f"create table main.{t} as select * from src.main.{t} where lender_id='{lender}' and month_date >= date '{since}'")
    for t in ["event_calendar", "dim_lender", "dim_product", "dim_bucket", "dim_geography", "dim_agency"]: c.sql(f"create table main.{t} as select * from src.main.{t}")
    c.sql("detach src"); c.close(); return path
def _pool(spec):
    w = f"bucket_prev='{spec['bucket']}'"
    for k in ("product_type", "region"):
        if spec.get("pool", {}).get(k): w += f" and {k}='{spec['pool'][k]}'"
    return w
def plant(path, spec, seed=1):
    """modify the scratch DB in place; returns per-month truth records."""
    c = duckdb.connect(str(path)); truth = []
    for month, mult in spec["months"].items():
        base = f"lender_id='{spec['lender']}' and month_date=date '{month}' and {_pool(spec)}"
        n_pool = c.sql(f"select count(*) from main.d1_account_monthly where {base}").fetchone()[0]; n_slice = c.sql(f"select count(*) from main.d1_account_monthly where {base} and ({spec['slice_sql']})").fetchone()[0]
        flips = int(round(spec["delta"] * mult * n_slice))
        if flips:
            c.sql(f"""update main.d1_account_monthly set bucket_curr = {NEXT}, dpd_curr = {NEXT_DPD}
                      where rowid in (select rowid from (select rowid, row_number() over (order by hash(account_id || '{seed}')) rn from main.d1_account_monthly
                                      where {base} and ({spec['slice_sql']}) and bucket_curr in ('CURRENT','1-30','31-60','61-90') and ({SEV('bucket_curr')}) <= ({SEV('bucket_prev')})) where rn <= {flips})""")
        removed = 0
        if spec.get("d3"):
            ch = "('VOICE_CALL')" if spec["d3"]["kind"] == "calls" else "('FIELD_VISIT','FIELD_COLLECTION')"; frac = int(100 * spec["d3"]["frac"] * (1 if spec["d3"]["kind"] == "field" else mult))
            before = c.sql("select count(*) from main.d3_collection_events").fetchone()[0]
            c.sql(f"""delete from main.d3_collection_events where month_date=date '{month}' and channel in {ch} and (hash(event_id) % 100) < {frac}
                      and account_id in (select account_id from main.d1_account_monthly where {base} and ({spec['slice_sql']}))""")
            removed = before - c.sql("select count(*) from main.d3_collection_events").fetchone()[0]
        truth.append(dict(month=month, n_pool=n_pool, n_slice=n_slice, flips=flips, slice_effect_pp=100 * flips / max(n_slice, 1), pool_effect_pp=100 * flips / max(n_pool, 1), d3_removed=removed))
    c.sql("""create or replace table main.bucket_flow_history as select lender_id, month_date, product_type, region, bucket_prev as bucket_from, bucket_curr as bucket_to, count(*)::INTEGER as account_count,
             sum(pos_opening)::BIGINT as pos_opening_amount from main.d1_account_monthly where bucket_prev <> 'NEW' group by all""")
    transition_matrix.build(c, "2025-09-01"); c.close(); return truth
def scenario_db(spec):
    base = build_base(spec["lender"]); path = DIR / f"scn_{spec['name']}.duckdb"
    if path.exists(): path.unlink()
    shutil.copy(base, path); truth = plant(path, spec); return path, truth
# ------------------------------------------------------------------ detection on a planted DB
def affected_segments(spec):
    P, R = ["BUSINESS_LOAN", "PERSONAL_LOAN", "TWO_WHEELER"], ["EAST", "NORTH", "SOUTH", "WEST"]; p, r = spec.get("pool", {}).get("product_type"), spec.get("pool", {}).get("region")
    return {(a, b) for a in P for b in R if (not p or a == p) and (not r or b == r)}
def node_segments(level, node):
    P, R = ["BUSINESS_LOAN", "PERSONAL_LOAN", "TWO_WHEELER"], ["EAST", "NORTH", "SOUTH", "WEST"]; p = node.split("|")[1:]
    if level == "lender": return {(a, b) for a in P for b in R}
    if level == "lender_product": return {(p[0], b) for b in R}
    if level == "lender_region": return {(a, p[0]) for a in P}
    return {(p[0], p[1])}
_FC = {}
def detect(path, spec, orig_con, top_n=8, min_excess=25):
    """-> DataFrame of investigations in the planted months for the planted lender, with global-style priority."""
    L = spec["lender"]
    if L not in _FC: f = orig_con.sql(f"select * from mart.detect_forecasts where lender_id='{L}'").df(); _FC[L] = f
    pc = duckdb.connect(str(path), read_only=True); seg = detection.metric_frame(pc, _FC[L]); pc.close()
    df = detection.score(detection.level_frames(seg)); months = [pd.Timestamp(m) for m in spec["months"]]; inv = pd.concat([detection.group(df, m) for m in months], ignore_index=True)
    if not len(inv): return inv
    others = orig_con.sql(f"select * from mart.investigations where node not like '{L}%' and month in ({','.join(repr(str(m.date())) for m in months)})").df()
    inv["abs_excess"] = inv.excess_accounts.abs(); allv = pd.concat([inv.assign(_p=1), others.assign(_p=0)], ignore_index=True, sort=False); allv["abs_excess"] = allv.excess_accounts.abs()
    allv["rank"] = allv.groupby("month").abs_excess.rank(ascending=False, method="first"); allv = allv[allv._p == 1]; inv["priority"] = ((allv["rank"].values <= top_n) & (allv.abs_excess.values >= min_excess)); inv["rank"] = allv["rank"].values; return inv
def match(inv, spec, month):
    """investigations in `month` that cover the planted pool, with the right bucket, metric and direction."""
    if not len(inv): return inv
    aff = affected_segments(spec); m = inv[(pd.to_datetime(inv.month) == pd.Timestamp(month)) & (inv.bucket_from == spec["bucket"]) & (inv.metric == spec.get("metric", "roll_forward")) & (inv.direction == "up")]
    return m[[bool(node_segments(r.level, r.node) & aff) for r in m.itertuples()]]
