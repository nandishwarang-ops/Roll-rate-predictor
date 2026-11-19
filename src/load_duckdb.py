"""Section 2: load datasets into DuckDB. Public -> main schema, hidden -> hidden schema.
The answer key is never loaded."""
import duckdb, pathlib, sys
root = pathlib.Path(__file__).resolve().parent.parent
con = duckdb.connect(str(root / "rollrate.duckdb"))
con.sql("CREATE SCHEMA IF NOT EXISTS hidden")
for t in ["d1_account_monthly", "d3_collection_events", "bucket_flow_history", "event_calendar"]:
    con.sql(f"CREATE OR REPLACE TABLE main.{t} AS SELECT * FROM read_parquet('{root}/data/public/{t}.parquet')")
    con.sql(f"CREATE OR REPLACE TABLE hidden.{t} AS SELECT * FROM read_parquet('{root}/data/hidden/{t}.parquet')")
for t in ["dim_lender", "dim_product", "dim_bucket", "dim_geography", "dim_agency"]:
    con.sql(f"CREATE OR REPLACE TABLE main.{t} AS SELECT * FROM read_parquet('{root}/data/reference/{t}.parquet')")
print(f"{'table':32}{'rows':>12}")
for schema, t in con.sql("select table_schema, table_name from information_schema.tables order by 1,2").fetchall():
    n = con.sql(f"select count(*) from {schema}.{t}").fetchone()[0]
    print(f"{schema+'.'+t:32}{n:>12,}")
