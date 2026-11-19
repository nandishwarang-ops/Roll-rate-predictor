"""Section 7: seasonal-naive benchmark (and plain-naive reference).
Forecast for month m = the same segment / bucket_from / bucket_to rate in month m-12 (seasonal naive),
or in month m-1 (naive). Scored against actuals on the last N public months.
Metrics: MAPE (cells with actual rate > 0 and >= MIN_OPEN opening accounts) and WAPE (count-weighted, robust to tiny rates).
This is the bar the real models must beat by >= 30% MAPE."""
import duckdb, pathlib, sys
root = pathlib.Path(__file__).resolve().parent.parent
MIN_OPEN = 30
LEVELS = ["segment", "lender_product", "lender_region", "lender"]
def score(con, level="segment", method="seasonal", months=12, as_of=None):
    lag = 12 if method == "seasonal" else 1
    mx = f"(select max(month_date) from mart.transitions_{level})" if as_of is None else f"date '{as_of}'"
    return con.sql(f"""
      with a as (select * from mart.transitions_{level} where month_date > {mx} - interval {months} month and month_date <= {mx}),
           b as (select * from mart.transitions_{level})
      select a.*, b.rate_count as fc_rate from a
      join b on {' and '.join(f'a.{k}=b.{k}' for k in {'segment':['lender_id','product_type','region'],'lender_product':['lender_id','product_type'],'lender_region':['lender_id','region'],'lender':['lender_id']}[level])}
             and a.bucket_from=b.bucket_from and a.bucket_to=b.bucket_to and b.month_date = a.month_date - interval {lag} month""")
def metrics(con, rel, name):
    con.register("scored", rel.df() if hasattr(rel, "df") else rel)
    r = con.sql(f"""select
        count(*) filter (where rate_count>0 and opening_accounts>={MIN_OPEN}) n_cells,
        avg(abs(fc_rate-rate_count)/rate_count) filter (where rate_count>0 and opening_accounts>={MIN_OPEN}) mape,
        sum(abs(fc_rate-rate_count)*opening_accounts) / sum(rate_count*opening_accounts) wape
      from scored where fc_rate is not null""").fetchone()
    return r
if __name__ == "__main__":
    con = duckdb.connect(str(root / "rollrate.duckdb"))
    rows = []
    for level in LEVELS:
        for method in ["seasonal", "naive"]:
            for months in [12, 3]:
                rel = score(con, level, method, months)
                n, mape, wape = metrics(con, rel, f"{level}/{method}/{months}")
                rows.append((level, method, months, n, mape, wape))
    con.sql("create schema if not exists mart")
    con.register("res", __import__("pandas").DataFrame(rows, columns=["level", "method", "last_n_months", "n_cells", "mape", "wape"]))
    con.sql("create or replace table mart.benchmark_scores as select * from res")
    md = ["# Seasonal-naive benchmark (public data)\n",
          "Forecast for month m = same segment/bucket rate in m-12 (seasonal) or m-1 (naive). Scored on the last N public months; MAPE excludes zero-rate cells and cells with <30 opening accounts.\n",
          "| level | method | last N months | cells scored | MAPE | WAPE |", "|---|---|---|---|---|---|"]
    md += [f"| {l} | {m} | {k} | {n:,} | {mp:.1%} | {w:.1%} |" for l, m, k, n, mp, w in rows]
    (root / "docs/benchmark_seasonal_naive.md").write_text("\n".join(md))
    print("\n".join(md[4:]))
