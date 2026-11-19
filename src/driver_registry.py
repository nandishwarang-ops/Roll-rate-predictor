"""Section 17: driver registry = the system's memory across months.
Stores every confirmed driver (what/where/when/category + the machine-readable slice that defines it) in outputs/state.duckdb and RE-CHECKS it
against each new month's actuals with the attribution engine, so a blip is not mistaken for a lasting shift (or the reverse):
  open        new, seen once, effect not yet confirmed        -> classifier builds two scenarios (blip / lasting)
  persistent  effect still there next month                   -> STEP   (blip scenario dropped, ranges narrow)
  fading      still significant but shrinking                 -> TRANSIENT-fading
  closed_transient  effect gone after one month               -> DOT (blip)
  closed_reverted   a persistent driver disappeared twice in a row
Persistence is measured as the excess-over-control effect now vs when first seen, with the baseline placed BEFORE the driver's start month."""
import duckdb, json, pathlib, datetime, re
import pandas as pd
root = pathlib.Path(__file__).resolve().parent.parent
STATE = root / "outputs/state.duckdb"
DDL = ["""create table if not exists drivers (driver_id varchar primary key, lender_id varchar, category varchar, what varchar, where_json varchar, slice_spec varchar, first_seen date, start_month date,
          last_seen date, status varchar, label_hint varchar, n_obs integer, excess_first double, strikes integer, created_run_id varchar)""",
       "create table if not exists driver_obs (driver_id varchar, month_date date, excess_pp double, z double, n_T integer, evidence_ids varchar, run_id varchar, source varchar)",
       "create table if not exists driver_events (driver_id varchar, month_date date, from_status varchar, to_status varchar, reason varchar)"]
LABEL = {"open": "UNKNOWN (two scenarios)", "persistent": "STEP", "fading": "TRANSIENT (fading)", "closed_transient": "DOT", "closed_reverted": "CLOSED"}
ACTIVE = ("open", "persistent", "fading")
PERSIST_RATIO, GONE_RATIO, Z_OK, Z_GONE = 0.5, 0.25, 2.0, 1.5
def _con(path=None):
    p = pathlib.Path(path or STATE); p.parent.mkdir(parents=True, exist_ok=True); c = duckdb.connect(str(p)); [c.sql(d) for d in DDL]; return c
def M(x):
    x = str(x)[:10]; x = x + "-01" if len(x) == 7 else x; x = datetime.datetime.fromisoformat(x); return datetime.date(x.year, x.month, 1)
def months_between(a, b): a, b = M(a), M(b); return (b.year - a.year) * 12 + b.month - a.month
def tokens(where): return {t for t in re.split(r"[^a-z0-9_]+", " ".join(str(v) for v in where.values() if v).lower()) if len(t) > 2}
def excess_from_cause(res, name=None):
    """excess-over-control effect (pp) + z from an attribute_change result."""
    c = next(((k, v) for k, v in res["causes"].items() if v.get("status") == "ok" and (name is None or k == name)), None)
    if not c: return None
    v = c[1]; w = v["n_T"] / res["pool_n_T"]; lo, hi = v["contribution_pp_80"]
    ex = v["contribution_pp"] / w; se = max((hi - lo) / (2 * 1.2816) / w, 1e-9)
    return dict(cause=c[0], excess_pp=ex, z=ex / se, n_T=v["n_T"])
# ------------------------------------------------------------ register / match
def find_match(c, lender, category, where):
    for r in c.sql("select driver_id, where_json from drivers where lender_id=? and category=? and status in ('open','persistent','fading')", params=[lender, category]).fetchall():
        a, b = tokens(json.loads(r[1])), tokens(where)
        if a and b and len(a & b) / len(a | b) >= 0.6: return r[0]
    return None
def register_from_result(res, attr_evidence, state=None, run_id=None):
    """-> list of (driver_id, 'new'|'seen_again') for confirmed drivers (confidence high/medium) that carry an attribution id."""
    out = []; c = _con(state); inv, f = res["investigation"], res["findings"]; lender = inv["node"].split("|")[0]; month = M(inv["month"])
    for d in f.get("drivers", []):
        if d.get("confidence") not in ("high", "medium") or not d.get("attribution_id") or d["attribution_id"] not in attr_evidence: continue
        led = attr_evidence[d["attribution_id"]]; ex = excess_from_cause(led)
        if not ex: continue
        where = {**d["where"], "lender": lender}; did = find_match(c, lender, d["category"], where)
        start = M(d.get("when", {}).get("start_month") or month)
        if did:
            c.sql("update drivers set last_seen=? where driver_id=?", params=[month, did]); kind = "seen_again"
        else:
            n = c.sql("select count(*) from drivers where lender_id=?", params=[lender]).fetchone()[0] + 1; did = f"D-{lender[-1]}-{n:03d}"; a = led["args"]; spec = dict(
                pool=dict(bucket_from=a["bucket_from"], metric=a["metric"], product_type=a["product_type"], region=a["region"]), cause=led["causes"] and a["causes"][ex["cause"]], control=a["control"])
            c.sql("insert into drivers values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", params=[did, lender, d["category"], d["what"], json.dumps(where), json.dumps(spec), month, start, month, "open", LABEL["open"], 1, ex["excess_pp"], 0, run_id])
            c.sql("insert into driver_events values (?,?,?,?,?)", params=[did, month, None, "open", f"registered from {d['attribution_id']}"]); kind = "new"
        c.sql("insert into driver_obs values (?,?,?,?,?,?,?,?)", params=[did, month, ex["excess_pp"], ex["z"], ex["n_T"], json.dumps(d["evidence_ids"]), run_id, "detective"])
        out.append((did, kind))
    c.close(); return out
# ------------------------------------------------------------ state machine
def classify(first, history, z_now, now, status, strikes):
    """pure function: -> (new_status, new_strikes, reason). `history` = earlier excess values oldest->newest (excluding now)."""
    ratio = now / first if first else 0.0; same_sign = now * first > 0
    persists = same_sign and ratio >= PERSIST_RATIO and abs(z_now) >= Z_OK
    gone = (not same_sign) or ratio < GONE_RATIO or abs(z_now) < Z_GONE
    prev = history[-1] if history else None; shrinking = prev is not None and same_sign and now < 0.85 * prev if first > 0 else (prev is not None and same_sign and now > 0.85 * prev)
    if status == "open":
        if persists: return "persistent", 0, f"effect persisted: {ratio:.0%} of first-seen effect, z={z_now:.1f}"
        if gone: return "closed_transient", 0, f"effect gone after first month: {ratio:.0%} of first-seen effect, z={z_now:.1f}"
        if ratio < PERSIST_RATIO: return "fading", 0, f"effect weakening: {ratio:.0%} of first-seen effect, z={z_now:.1f}"
        return "open", 0, f"inconclusive (effect {ratio:.0%} of first-seen but z={z_now:.1f}); stays open"
    if status == "persistent":
        if persists: return "persistent", 0, f"still {ratio:.0%} of first-seen effect, z={z_now:.1f}"
        if gone: return ("closed_reverted", 2, f"gone for 2 months running ({ratio:.0%}, z={z_now:.1f})") if strikes >= 1 else ("persistent", 1, f"missing this month ({ratio:.0%}, z={z_now:.1f}); one more month before closing")
        if ratio < PERSIST_RATIO: return "fading", 0, f"weakening to {ratio:.0%} of first-seen effect"
        return "persistent", strikes, f"inconclusive this month (effect {ratio:.0%} of first-seen but z={z_now:.1f}); stays persistent"
    if status == "fading":
        if persists and not shrinking: return "persistent", 0, f"recovered to {ratio:.0%}, z={z_now:.1f}"
        if gone: return "closed_transient", 0, f"faded out ({ratio:.0%}, z={z_now:.1f})"
        return "fading", 0, f"still fading at {ratio:.0%}"
    return status, strikes, "closed"
def observe(driver_id, month, excess_pp, z, n_T, state=None, run_id=None, evidence="", source="recheck"):
    c = _con(state); d = c.sql("select status, excess_first, strikes, last_seen from drivers where driver_id=?", params=[driver_id]).fetchone()
    hist = [r[0] for r in c.sql("select excess_pp from driver_obs where driver_id=? order by month_date", params=[driver_id]).fetchall()][1:]
    if d[3] and M(month) <= M(d[3]): c.close(); return {"driver_id": driver_id, "status": d[0], "skipped": "month already observed"}
    new, strikes, why = classify(d[1], hist, z, excess_pp, d[0], d[2])
    c.sql("insert into driver_obs values (?,?,?,?,?,?,?,?)", params=[driver_id, M(month), excess_pp, z, n_T, json.dumps(evidence), run_id, source])
    c.sql("update drivers set status=?, label_hint=?, strikes=?, last_seen=?, n_obs=n_obs+1 where driver_id=?", params=[new, LABEL[new], strikes, M(month), driver_id])
    if new != d[0]: c.sql("insert into driver_events values (?,?,?,?,?)", params=[driver_id, M(month), d[0], new, why])
    c.close(); return {"driver_id": driver_id, "from": d[0], "status": new, "reason": why}
def recheck_all(lender, month, attr_tool, state=None, run_id=None):
    """re-run the attribution for every active driver of this lender against the new month; baseline placed before each driver's start."""
    c = _con(state); rows = c.sql("select driver_id, slice_spec, start_month from drivers where lender_id=? and status in ('open','persistent','fading')", params=[lender]).fetchall(); c.close(); out = []
    for did, spec, start in rows:
        s = json.loads(spec); p = s["pool"]; lag = max(0, months_between(start, month))
        res = attr_tool(month=str(M(month)), bucket_from=p["bucket_from"], metric=p["metric"], product_type=p["product_type"], region=p["region"], recent_months=1, baseline_lag=lag, causes={"driver": s["cause"]}, control=s["control"])
        ex = excess_from_cause(res) if res.get("ok") else None
        if not ex: out.append({"driver_id": did, "status": "unchanged", "reason": res.get("error") or "slice too small this month"}); continue
        out.append(observe(did, month, ex["excess_pp"], ex["z"], ex["n_T"], state, run_id, evidence=res["attribution_id"]))
    return out
# ------------------------------------------------------------ views for agents / pack
def active_text(lender, state=None):
    c = _con(state); rows = c.sql("select driver_id, what, category, status, label_hint, first_seen, n_obs, where_json from drivers where lender_id=? and status in ('open','persistent','fading') order by first_seen", params=[lender]).fetchall(); c.close()
    if not rows: return ""
    return "KNOWN DRIVERS from earlier months (re-check these first; do not rediscover them):\n" + "\n".join(f"- {r[0]} [{r[3]} -> {r[4]}] {r[1]} ({r[2]}; first seen {r[5]}, {r[6]} observation(s); where {json.loads(r[7])})" for r in rows) + "\n\n"
def history(driver_id, state=None):
    c = _con(state); o = c.sql("select month_date, excess_pp, z, n_T from driver_obs where driver_id=? order by 1", params=[driver_id]).df(); e = c.sql("select month_date, from_status, to_status, reason from driver_events where driver_id=? order by 1", params=[driver_id]).df(); c.close(); return o, e
def changes_since(lender, month, state=None):
    """for the pack's 'what changed since last month' section."""
    c = _con(state); e = c.sql("select e.driver_id, d.what, e.from_status, e.to_status, e.reason from driver_events e join drivers d using (driver_id) where d.lender_id=? and e.month_date=? and e.from_status is not null", params=[lender, M(month)]).df(); c.close(); return e
