"""Section 5: lender lock + time-cutoff (leakage) controls = the agent-facing, READ-ONLY SQL gateway.
For one run (lender_id, as_of) it builds an isolated in-memory database that holds ONLY
  - rows of that lender,
  - months <= as_of,
  - calendar events announced on/before the cutoff (so forward-known events like a scheduled festival remain visible),
then DETACHES the source file, turns off external access and locks the configuration. Because the other lenders'
rows, the hidden-period tables and the answer key are simply not in the database, no query text can reach them.
Only a single SELECT/WITH statement is accepted. Every call (allowed or blocked) is written to the audit list."""
import duckdb, pathlib, re, time, datetime
root = pathlib.Path(__file__).resolve().parent.parent
class Blocked(Exception): pass
LENDER_TABLES = ["d1_account_monthly", "d3_collection_events", "bucket_flow_history"]
class GuardedSQL:
    def __init__(self, lender_id, as_of, db=root / "rollrate.duckdb", run_id=None):
        self.lender_id, self.as_of, self.run_id, self.audit = lender_id, str(as_of)[:10], run_id, []
        con = duckdb.connect(":memory:")
        con.sql(f"attach '{db}' as src (read_only)")
        L, A = lender_id.replace("'", ""), self.as_of
        for t in LENDER_TABLES:       # month_date <= as_of and lender_id = L, copied into the sandbox
            con.sql(f"create table {t} as select * from src.main.{t} where lender_id='{L}' and month_date <= date '{A}'")
        con.sql(f"create table event_calendar as select * from src.main.event_calendar where announced_date <= date '{A}' "
                f"and (lender_id is null or lender_id='{L}')")
        con.sql(f"create table dim_lender as select * from src.main.dim_lender where lender_id='{L}'")
        for t in ["dim_product", "dim_bucket", "dim_geography", "dim_agency"]:
            con.sql(f"create table {t} as select * from src.main.{t}")
        mart = [r[0] for r in con.sql("select table_name from duckdb_tables() where database_name='src' and schema_name='mart'").fetchall()]
        for t in mart:
            cols = [r[0] for r in con.sql(f"describe src.mart.{t}").fetchall()]
            if "lender_id" in cols:
                con.sql(f"create table {t} as select * from src.mart.{t} where lender_id='{L}' and month_date <= date '{A}'")
        con.sql("detach src")
        con.sql("set enable_external_access=false"); con.sql("set lock_configuration=true")
        self.con = con
    def _log(self, sql, status, note=""):
        self.audit.append({"ts": datetime.datetime.now().isoformat(timespec="seconds"), "run_id": self.run_id, "lender": self.lender_id,
                           "as_of": self.as_of, "sql": sql, "status": status, "note": note})
    def query(self, sql, max_rows=1000):
        try:
            stmts = self.con.extract_statements(sql)
            if len(stmts) != 1: raise Blocked("exactly one statement allowed")
            if stmts[0].type != duckdb.StatementType.SELECT: raise Blocked(f"only SELECT allowed, got {stmts[0].type}")
            if re.search(r"\b(read_parquet|read_csv|read_json|glob|copy|attach|install|load|pragma|export|import)\b", sql, re.I):
                raise Blocked("file / system functions are not allowed")
            df = self.con.sql(sql).limit(max_rows).df()
        except Blocked as e:
            self._log(sql, "BLOCKED", str(e)); raise
        except Exception as e:       # e.g. table does not exist (hidden./mart tables of other lenders are not there)
            self._log(sql, "ERROR", str(e).splitlines()[0]); raise Blocked(str(e).splitlines()[0])
        self._log(sql, "OK", f"{len(df)} rows")
        return df
