import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from sql_tool import SQLTool
ok = lambda n, c: print(("PASS " if c else "FAIL ") + n) or c
(pathlib.Path(__file__).resolve().parent.parent / "outputs/audit/test_sql_tool.jsonl").unlink(missing_ok=True)   # audit files append across runs
t = SQLTool("LENDER_B", "2025-09-01", run_id="test_sql_tool", budget=8, max_rows=5, timeout_s=3)
r = []
a = t("select bucket_prev, count(*) n from d1_account_monthly where month_date=date '2025-09-01' group by 1 order by 2 desc", "bucket mix")
r += [ok("valid query returns rows + id", a["ok"] and a["query_id"] == "Q001" and a["row_count"] > 0)]
r += [ok("text rendering", t.as_text(a).startswith("[Q001]"))]
b = t("select * from d1_account_monthly", "truncation"); r += [ok("rows capped + truncated flag", b["ok"] and b["truncated"] and b["row_count"] == 5)]
c = t("select * from hidden.d1_account_monthly", "hidden"); r += [ok("blocked query comes back as an error result, not an exception", (not c["ok"]) and "error" in c)]
d = t("select bucket_prev, count(*) n from d1_account_monthly where month_date=date '2025-09-01' group by 1 order by 2 desc", "dup")
r += [ok("identical query served from cache, no budget used", d.get("note", "").startswith("identical") and t.used == 3)]
e = t("select count(*) from d1_account_monthly a, d1_account_monthly b, d1_account_monthly c", "slow"); r += [ok("slow query hits timeout and returns an error", (not e["ok"]) and "time limit" in e["error"])]
f = t("select " + "x" * 5000, "long"); r += [ok("over-long query rejected", not f["ok"])]
for i in range(3): g = t(f"select {i} as v", "fill")
h = t("select 99", "over budget"); r += [ok("budget exhausted message", (not h["ok"]) and "budget" in h["error"])]
r += [ok("evidence ledger + citation", "Q001" in t.evidence and "bucket mix" in t.cite("Q001"))]
r += [ok("audit log written", t.audit_path.exists() and len(t.audit_path.read_text().splitlines()) == t.used)]
r += [ok("schema text lists only locked tables, no hidden", "d1_account_monthly" in t.schema_text() and "hidden" not in t.schema_text())]
t2 = SQLTool("LENDER_B", "2025-09-01", run_id="test_sql_tool2"); r += [ok("tool still usable after a timeout", t.g.query("select 1 x").x[0] == 1)]
sys.exit(0 if all(r) else 1)
