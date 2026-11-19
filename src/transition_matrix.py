"""Section 6: full transition-matrix builder.
Builds mart.transition_cells: a DENSE grid (zeros filled) of
  lender x product x region x month x bucket_from x bucket_to -> account_count, pos, rate_count, rate_pos.
Plus mart.move_summary: forward / stay / cure / closed / written_off share per row, and mart.transition_levels
for the hierarchy (lender, lender+product, lender+region, segment). Rates are always computed from summed counts
(never averaged), so every level reconciles with the level below.
Time cutoff: only months <= as_of are used (leakage control)."""
import duckdb, pathlib, sys
root = pathlib.Path(__file__).resolve().parent.parent
FROM = ["CURRENT", "1-30", "31-60", "61-90", "90+"]
TO = ["CURRENT", "1-30", "31-60", "61-90", "90+", "CLOSED", "WRITTEN_OFF"]
SEV = {"CURRENT": 0, "1-30": 1, "31-60": 2, "61-90": 3, "90+": 4}
def build(con, as_of="2025-09-01", source="main"):
    con.sql("create schema if not exists mart")
    values = lambda xs: ",".join(f"('{x}')" for x in xs)
    con.sql(f"""create or replace table mart.transition_cells as
      with seg as (select distinct lender_id, product_type, region from {source}.bucket_flow_history),
           mon as (select distinct month_date from {source}.bucket_flow_history where month_date <= date '{as_of}'),
           f(bucket_from) as (values {values(FROM)}), t(bucket_to) as (values {values(TO)}),
           grid as (select * from seg, mon, f, t),
           act as (select lender_id, month_date, product_type, region, bucket_from, bucket_to,
                          sum(account_count) n, sum(pos_opening_amount) pos from {source}.bucket_flow_history group by all)
      select g.lender_id, g.product_type, g.region, g.month_date, g.bucket_from, g.bucket_to,
             coalesce(a.n,0)::BIGINT account_count, coalesce(a.pos,0)::BIGINT pos_amount
      from grid g left join act a using (lender_id, product_type, region, month_date, bucket_from, bucket_to)""")
    sev = "case {c} " + " ".join(f"when '{k}' then {v}" for k, v in SEV.items()) + " end"
    for name, keys in {"segment": "lender_id, product_type, region", "lender_product": "lender_id, product_type",
                       "lender_region": "lender_id, region", "lender": "lender_id"}.items():
        con.sql(f"""create or replace table mart.transitions_{name} as
          with c as (select {keys}, month_date, bucket_from, bucket_to, sum(account_count) account_count, sum(pos_amount) pos_amount
                     from mart.transition_cells group by all)
          select *, account_count / nullif(sum(account_count) over (partition by {keys}, month_date, bucket_from),0) rate_count,
                    pos_amount / nullif(sum(pos_amount) over (partition by {keys}, month_date, bucket_from),0) rate_pos,
                    sum(account_count) over (partition by {keys}, month_date, bucket_from) opening_accounts
          from c""")
        con.sql(f"""create or replace table mart.moves_{name} as
          select {keys}, month_date, bucket_from, max(opening_accounts) opening_accounts,
            sum(case when bucket_to in ('CLOSED','WRITTEN_OFF') then 0 when ({sev.format(c='bucket_to')}) > ({sev.format(c='bucket_from')}) then rate_count else 0 end) roll_forward,
            sum(case when bucket_to = bucket_from then rate_count else 0 end) stay_same,
            sum(case when bucket_to not in ('CLOSED','WRITTEN_OFF') and ({sev.format(c='bucket_to')}) < ({sev.format(c='bucket_from')}) then rate_count else 0 end) cure,
            sum(case when bucket_to = 'CLOSED' then rate_count else 0 end) closed,
            sum(case when bucket_to = 'WRITTEN_OFF' then rate_count else 0 end) written_off
          from mart.transitions_{name} group by all""")
def validate(con, source="main"):
    out = []
    n = con.sql("select count(*) from mart.transition_cells").fetchone()[0]
    segs = con.sql("select count(*) from (select distinct lender_id, product_type, region from mart.transition_cells)").fetchone()[0]
    months = con.sql("select count(distinct month_date) from mart.transition_cells").fetchone()[0]
    out.append(("dense grid size", n == segs * months * len(FROM) * len(TO), f"{n:,} = {segs} segments x {months} months x {len(FROM)} x {len(TO)}"))
    r = con.sql("""select count(*) from (select lender_id,product_type,region,month_date,bucket_from, sum(rate_count) s
                   from mart.transitions_segment group by all having abs(sum(rate_count)-1) > 1e-9)""").fetchone()[0]
    empty = con.sql("select count(*) from (select 1 from mart.transitions_segment group by lender_id,product_type,region,month_date,bucket_from having max(opening_accounts)=0)").fetchone()[0]
    out.append(("segment rows sum to 1 (excluding empty rows)", r == empty or r == 0, f"{r} rows not summing to 1 ({empty} empty rows have no opening accounts)"))
    d = con.sql(f"select sum(account_count) from {source}.bucket_flow_history where month_date <= (select max(month_date) from mart.transition_cells)").fetchone()[0]
    for lvl in ["segment", "lender_product", "lender_region", "lender"]:
        s = con.sql(f"select sum(account_count) from mart.transitions_{lvl}").fetchone()[0]
        out.append((f"{lvl} total == bucket_flow_history", s == d, f"{s:,} vs {d:,}"))
    m = con.sql("select max(abs(roll_forward+stay_same+cure+closed+written_off-1)) from mart.moves_segment where opening_accounts>0").fetchone()[0]
    out.append(("roll_forward+stay_same+cure+closed+written_off == 1", m < 1e-9, f"max deviation {m:.2e}"))
    return out
if __name__ == "__main__":
    con = duckdb.connect(str(root / "rollrate.duckdb"))
    build(con)
    ok = True
    for name, passed, detail in validate(con):
        print("PASS" if passed else "FAIL", name, "-", detail); ok &= bool(passed)
    print(con.sql("""select bucket_from, round(sum(roll_forward*opening_accounts)/sum(opening_accounts),4) roll_forward, round(sum(stay_same*opening_accounts)/sum(opening_accounts),4) stay_same,
                     round(sum(cure*opening_accounts)/sum(opening_accounts),4) cure, round(sum(closed*opening_accounts)/sum(opening_accounts),4) closed,
                     round(sum(written_off*opening_accounts)/sum(opening_accounts),4) written_off
                     from mart.moves_lender group by 1 order by 1""").df().to_string(index=False))
    sys.exit(0 if ok else 1)
