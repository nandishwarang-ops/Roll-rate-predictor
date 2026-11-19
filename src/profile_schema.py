"""Section 3: schema discovery + profiling of the PUBLIC (main) schema only.
Writes docs/column_catalogue.json (machine-readable, fed to the Detective agent)
and docs/column_catalogue.md (human-readable)."""
import duckdb, json, pathlib, datetime
root = pathlib.Path(__file__).resolve().parent.parent
con = duckdb.connect(str(root / "rollrate.duckdb"), read_only=True)
LOWCARD = 30
tables = [r[0] for r in con.sql("select table_name from information_schema.tables where table_schema='main' order by 1").fetchall()]
cat = {"generated": datetime.date.today().isoformat(), "schema": "main", "tables": {}}
for t in tables:
    n = con.sql(f"select count(*) from main.{t}").fetchone()[0]
    cols = con.sql(f"describe main.{t}").fetchall()
    info = {"rows": n, "columns": {}}
    exprs = []
    for c, ty, *_ in cols:
        exprs += [f'count("{c}")', f'approx_count_distinct("{c}")', f'min("{c}")::VARCHAR', f'max("{c}")::VARCHAR']
    row = con.sql(f"select {','.join(exprs)} from main.{t}").fetchone()
    for i, (c, ty, *_) in enumerate(cols):
        nn, nd, mn, mx = row[4*i:4*i+4]
        d = {"type": ty, "null_pct": round(100*(n-nn)/n, 2) if n else 0, "distinct": int(nd), "min": mn, "max": mx}
        if 0 < nd <= LOWCARD:
            d["values"] = {str(v): int(k) for v, k in con.sql(f'select "{c}", count(*) from main.{t} group by 1 order by 2 desc').fetchall()}
        info["columns"][c] = d
    # time coverage
    if any(c[0] == "month_date" for c in cols):
        info["months"] = [str(m[0])[:7] for m in con.sql(f"select distinct month_date from main.{t} order by 1").fetchall()]
    cat["tables"][t] = info
(root / "docs/column_catalogue.json").write_text(json.dumps(cat, indent=1, default=str))
md = [f"# Column catalogue (public schema, generated {cat['generated']})\n"]
for t, i in cat["tables"].items():
    md.append(f"## {t} — {i['rows']:,} rows" + (f", {len(i['months'])} months ({i['months'][0]} → {i['months'][-1]})" if "months" in i else "") + "\n")
    md.append("| column | type | null% | distinct | min | max | values |\n|---|---|---|---|---|---|---|")
    for c, d in i["columns"].items():
        v = ", ".join(f"{k}" for k in list(d.get("values", {}))[:12])
        md.append(f"| {c} | {d['type']} | {d['null_pct']} | {d['distinct']:,} | {d['min']} | {d['max']} | {v} |")
    md.append("")
(root / "docs/column_catalogue.md").write_text("\n".join(md))
print("tables:", {t: i["rows"] for t, i in cat["tables"].items()})
for t, i in cat["tables"].items():
    if "months" in i: print(t, len(i["months"]), i["months"][0], i["months"][-1])
