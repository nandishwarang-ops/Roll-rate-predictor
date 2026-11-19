import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from guarded_sql import GuardedSQL, Blocked
g = GuardedSQL("LENDER_B", "2025-09-01", run_id="test")
ok = lambda name, cond: print(("PASS " if cond else "FAIL ") + name) or cond
res = []
res.append(ok("only LENDER_B visible in D1", g.query("select distinct lender_id from d1_account_monthly").lender_id.tolist() == ["LENDER_B"]))
res.append(ok("only LENDER_B visible in D3", g.query("select distinct lender_id from d3_collection_events").lender_id.tolist() == ["LENDER_B"]))
res.append(ok("no months after cutoff", str(g.query("select max(month_date) m from d1_account_monthly").m[0])[:10] == "2025-09-01"))
res.append(ok("dim_lender only LENDER_B", len(g.query("select * from dim_lender")) == 1))
res.append(ok("mart tables are lender-locked", g.query("select distinct lender_id from transitions_segment").lender_id.tolist() == ["LENDER_B"]))
ev = g.query("select event_name, lender_id from event_calendar")
res.append(ok("calendar shows no other lender's private events", set(ev.lender_id.dropna()) <= {"LENDER_B"}))
res.append(ok("forward-known festival (Diwali 2025) visible", g.query("select count(*) n from event_calendar where event_start_date > date '2025-09-01' and known_in_advance").n[0] >= 1))
for name, sql in {"hidden schema": "select * from hidden.d1_account_monthly", "source db": "select * from src.main.d1_account_monthly",
                  "file read": "select * from read_parquet('data/hidden/d1_account_monthly.parquet')", "write": "create table x as select 1",
                  "drop": "drop table d1_account_monthly", "multi-statement": "select 1; select 2", "attach": "attach 'rollrate.duckdb' as z",
                  "answer key csv": "select * from 'answer_key/seeded_events_answer_key.csv'", "set config": "set enable_external_access=true"}.items():
    try: g.query(sql); res.append(ok(f"blocked: {name}", False))
    except Blocked: res.append(ok(f"blocked: {name}", True))
res.append(ok("every attempt audited", len(g.audit) >= 16 and sum(a["status"] != "OK" for a in g.audit) == 9))
# other lender + earlier cutoff
h = GuardedSQL("LENDER_A", "2025-06-01")
res.append(ok("cutoff 2025-06 hides Jul-Sep", str(h.query("select max(month_date) m from d3_collection_events").m[0])[:10] == "2025-06-01"))
sys.exit(0 if all(res) else 1)
