"""Section 4: data sanity checks + data-quality report on the PUBLIC schema.
Writes docs/data_quality_report.md and docs/data_quality_report.json.
Exit code 1 if any FAIL (the orchestrator pauses the run on FAIL; WARN continues)."""
import duckdb, json, pathlib, sys, datetime, uuid
root = pathlib.Path(__file__).resolve().parent.parent
THIN = 30   # min opening accounts per segment-bucket-month to forecast a rate reliably
def run(db=root / "rollrate.duckdb", schema="main"):
    con = duckdb.connect(str(db), read_only=True)
    q = lambda s: con.sql(s.replace("{S}", schema)).fetchall()
    res = []
    def add(name, status, detail, sample=None):
        res.append({"check": name, "status": status, "detail": detail, "sample": sample})
    one = lambda s: q(s)[0][0]
    # 1 uniqueness
    n = one("select count(*) from (select account_id, month_date from {S}.d1_account_monthly group by 1,2 having count(*)>1)")
    add("D1 one row per account per month", "PASS" if n == 0 else "FAIL", f"{n} duplicated (account, month) keys")
    n = one("select count(*) - count(distinct event_id) from {S}.d3_collection_events")
    add("D3 event_id unique", "PASS" if n == 0 else "FAIL", f"{n} duplicate event_ids")
    # 2 nulls in key columns
    bad = {}
    for t, cols in {"d1_account_monthly": ["month_date","account_id","lender_id","product_type","region","bucket_prev","bucket_curr","dpd_curr"],
                    "d3_collection_events": ["event_id","account_id","lender_id","month_date","channel"],
                    "bucket_flow_history": ["lender_id","month_date","product_type","region","bucket_from","bucket_to","account_count"]}.items():
        for c in cols:
            k = one(f"select count(*) from {{S}}.{t} where {c} is null")
            if k: bad[f"{t}.{c}"] = k
    add("No nulls in key columns", "PASS" if not bad else "FAIL", str(bad) if bad else "all key columns complete")
    # 3 month continuity
    for t in ["d1_account_monthly", "d3_collection_events", "bucket_flow_history"]:
        r = q(f"select lender_id, count(distinct month_date), min(month_date), max(month_date) from {{S}}.{t} group by 1 order by 1")
        ok = all(x[1] == 24 for x in r)
        add(f"{t}: 24 months per lender", "PASS" if ok else "FAIL", "; ".join(f"{x[0]}: {x[1]} months {x[2]}→{x[3]}" for x in r))
    # 4 bucket_flow reconciles with D1 (counts)
    r = q("""with d as (select lender_id, month_date, product_type, region, bucket_prev bf, bucket_curr bt, count(*) n
                         from {S}.d1_account_monthly where bucket_prev <> 'NEW' group by all),
                  b as (select lender_id, month_date, product_type, region, bucket_from bf, bucket_to bt, sum(account_count) n
                         from {S}.bucket_flow_history group by all)
             select count(*), sum(case when d.n is distinct from b.n then 1 else 0 end)
             from d full outer join b using (lender_id, month_date, product_type, region, bf, bt)""")[0]
    add("bucket_flow_history reconciles with D1 (account counts)", "PASS" if r[1] == 0 else "FAIL", f"{r[0]:,} cells compared, {r[1]} mismatches")
    # 5 impossible bucket jumps
    order = "case {c} when 'NEW' then -1 when 'CURRENT' then 0 when '1-30' then 1 when '31-60' then 2 when '61-90' then 3 when '90+' then 4 end"
    p, c_ = order.format(c="bucket_prev"), order.format(c="bucket_curr")
    n = one(f"select count(*) from {{S}}.d1_account_monthly where bucket_curr in ('CURRENT','1-30','31-60','61-90','90+') and bucket_prev<>'NEW' and ({c_})-({p}) > 1")
    add("No forward bucket skips (e.g. CURRENT -> 31-60 in one month)", "PASS" if n == 0 else "FAIL", f"{n} accounts skipped a bucket")
    n = one("select count(*) from {S}.d1_account_monthly where bucket_prev in ('CLOSED','WRITTEN_OFF')")
    add("No transitions out of terminal buckets", "PASS" if n == 0 else "FAIL", f"{n} rows")
    # 6 dpd vs bucket consistency
    n = one("""select count(*) from {S}.d1_account_monthly where bucket_curr in ('CURRENT','1-30','31-60','61-90','90+') and
        not ((bucket_curr='CURRENT' and dpd_curr<=0) or (bucket_curr='1-30' and dpd_curr between 1 and 30) or (bucket_curr='31-60' and dpd_curr between 31 and 60)
          or (bucket_curr='61-90' and dpd_curr between 61 and 90) or (bucket_curr='90+' and dpd_curr>=91))""")
    add("dpd_curr agrees with bucket_curr", "PASS" if n == 0 else "FAIL", f"{n} inconsistent rows")
    # 7 negatives / impossible values
    n = one("select count(*) from {S}.d1_account_monthly where pos_opening<0 or pos_closing<0 or overdue_amount<0 or emi_amount<=0 or loan_amount<=0")
    add("No negative or zero amounts in D1", "PASS" if n == 0 else "FAIL", f"{n} rows")
    n = one("select count(*) from {S}.d1_account_monthly where bureau_score is not null and (bureau_score<300 or bureau_score>900)")
    add("Bureau score within 300-900", "PASS" if n == 0 else "WARN", f"{n} rows out of range")
    # 8 D3 referential integrity
    n = one("select count(*) from {S}.d3_collection_events e left join (select distinct account_id from {S}.d1_account_monthly) a using (account_id) where a.account_id is null")
    add("D3 events link to a D1 account", "PASS" if n == 0 else "FAIL", f"{n} orphan events")
    n = one("select count(*) from {S}.d3_collection_events where date_trunc('month', event_timestamp) <> month_date")
    add("D3 event_timestamp falls in its month_date", "PASS" if n == 0 else "WARN", f"{n} events")
    n = one("select count(*) from {S}.d3_collection_events where payment_status='SUCCESS' and (payment_amount is null or payment_amount<=0)")
    add("Successful payments carry an amount", "PASS" if n == 0 else "WARN", f"{n} events")
    # 9 event calendar
    n = one("select count(*) from {S}.event_calendar where event_end_date is not null and event_end_date < event_start_date")
    add("Event calendar: end date not before start", "PASS" if n == 0 else "FAIL", f"{n} events")
    n = one("select count(*) from {S}.event_calendar where announced_date > event_start_date and known_in_advance")
    add("Event calendar: 'known in advance' events announced before start", "PASS" if n == 0 else "WARN", f"{n} events")
    # 10 thin segments (forecast reliability) -> WARN list
    thin = q(f"""select lender_id, product_type, region, bucket_from, count(*) months_thin, min(n) min_n from (
                  select lender_id, product_type, region, bucket_from, month_date, sum(account_count) n from {{S}}.bucket_flow_history group by all)
               where n < {THIN} group by all order by months_thin desc""")
    total = one("select count(*) from (select distinct lender_id, product_type, region, bucket_from from {S}.bucket_flow_history)")
    add(f"Segment thickness (opening accounts >= {THIN}/month)", "PASS" if not thin else "WARN",
        f"{len(thin)} of {total} segment-buckets have months below {THIN} accounts; rates there are noisy",
        [dict(zip(["lender","product","region","bucket","months_thin","min_accounts"], t)) for t in thin[:25]])
    rid = f"dq_{datetime.datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"
    summary = {s: sum(r["status"] == s for r in res) for s in ["PASS", "WARN", "FAIL"]}
    return {"run_id": rid, "schema": schema, "generated": datetime.datetime.now().isoformat(timespec="seconds"), "summary": summary, "checks": res}
def write(rep):
    (root / "docs/data_quality_report.json").write_text(json.dumps(rep, indent=1, default=str))
    icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}
    md = [f"# Data-quality report — {rep['run_id']}\n", f"Schema `{rep['schema']}` · {rep['generated']} · " + " · ".join(f"{k}: {v}" for k, v in rep["summary"].items()) + "\n",
          "| | check | result |\n|---|---|---|"]
    md += [f"| {icon[r['status']]} | {r['check']} | {r['detail']} |" for r in rep["checks"]]
    for r in rep["checks"]:
        if r["sample"]:
            md += ["", f"### {r['check']} (first {len(r['sample'])})", "| " + " | ".join(r["sample"][0]) + " |", "|" + "---|" * len(r["sample"][0])]
            md += ["| " + " | ".join(str(v) for v in s.values()) + " |" for s in r["sample"]]
    (root / "docs/data_quality_report.md").write_text("\n".join(md))
if __name__ == "__main__":
    rep = run(); write(rep)
    for r in rep["checks"]: print(f"{r['status']:5} {r['check']}: {r['detail']}")
    print(rep["summary"]); sys.exit(1 if rep["summary"]["FAIL"] else 0)
