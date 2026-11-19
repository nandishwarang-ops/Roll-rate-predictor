"""Section 16: escalation questions + NON-BLOCKING notification.
When the Detective cannot explain a movement (or only with low confidence) it hands operations 2-3 concrete questions.
This module (a) checks the questions are specific, (b) stores them as escalation records, (c) notifies operations in the background
so a slow or failing channel can never stall or fail the run, (d) de-duplicates repeats, and (e) turns the replies into testable
follow-up hypotheses that the Detective receives next month.
Default channel is a local OUTBOX folder (markdown files). Nothing is sent externally unless an email/webhook notifier is configured explicitly."""
import duckdb, json, hashlib, re, pathlib, threading, datetime, time
root = pathlib.Path(__file__).resolve().parent.parent
STATE = root / "outputs/state.duckdb"
GENERIC = re.compile(r"^(did|was|is|has|have)\s+(anything|something)\s+(change|happen)", re.I)
DDL = """create table if not exists escalations (escalation_id varchar primary key, lender_id varchar, month_date date, scope varchar, metric varchar, bucket_from varchar,
  questions varchar, priority varchar, excess_accounts double, status varchar, created_at timestamp, due_at timestamp, notify_status varchar, notify_error varchar,
  answer varchar, answered_by varchar, answered_at timestamp, reask_count integer, question_hash varchar, resolution varchar)"""
def _con(path=None):
    p = pathlib.Path(path or STATE); p.parent.mkdir(parents=True, exist_ok=True); c = duckdb.connect(str(p)); c.sql(DDL); return c
# ---------------------------------------------------------------- question quality
def entities(inv, evidence):
    """concrete tokens a good question can refer to: scope + string values that appeared in this run's query results."""
    toks = set(inv["node"].split("|")) | {inv["bucket_from"], inv["metric"].replace("_", " ")}
    for e in (evidence or {}).values():
        for row in ((e.get("result") or {}).get("rows") or []):
            toks |= {v for v in row if isinstance(v, str) and len(v) >= 4}
    return {t.lower() for t in toks}
def check_question(q, ents):
    if not q.strip().endswith("?"): return "not a question"
    if not 20 <= len(q) <= 300: return "length must be 20-300 characters"
    if GENERIC.match(q.strip()): return "too generic"
    if not any(t in q.lower() for t in ents): return "names no concrete entity (agency, city, product, region, indicator, date) from the evidence"
    return None
def fallback_questions(inv, clues):
    """deterministic questions from the top profiler clues, used when the model's questions fail the check."""
    out = []; m = datetime.datetime.fromisoformat(str(inv["month"])[:10]).strftime("%B %Y"); lender, scope = inv["node"].split("|")[0], " / ".join(inv["node"].split("|")[1:]) or "all products and regions"
    for c in clues[:2]: out.append(f"Did anything change in {c} for {lender} {scope} around {m} (staffing, allocation, calling hours, policy, system)?")
    out.append(f"Was there any process, system or policy change in {lender} {scope} collections in {m} that affects accounts opening in the {inv['bucket_from']} bucket?")
    return out[:3]
# ---------------------------------------------------------------- notification (never blocks, never raises)
class FileOutbox:
    name = "outbox"
    def __init__(self, folder=root / "outputs/outbox"): self.folder = pathlib.Path(folder)
    def send(self, esc):
        self.folder.mkdir(parents=True, exist_ok=True)
        body = f"# Question for {esc['lender_id']} operations ({esc['priority']} priority)\n\nEscalation {esc['escalation_id']} - {esc['scope']} - {esc['month_date']}\nPlease reply by {esc['due_at']:%Y-%m-%d}.\n\n" + "\n".join(f"{i}. {q}" for i, q in enumerate(esc["questions"], 1))
        (self.folder / f"{esc['escalation_id']}.md").write_text(body)
class Dispatcher:
    def __init__(self, notifier=None, state=None, timeout=10, retries=2): self.n, self.state, self.timeout, self.retries, self.threads = notifier or FileOutbox(), state, timeout, retries, []
    def dispatch(self, esc):
        t = threading.Thread(target=self._run, args=(esc,), daemon=True); t.start(); self.threads.append(t); return t   # returns immediately
    def _run(self, esc):
        err = None
        for k in range(self.retries + 1):
            res = {}; th = threading.Thread(target=lambda: res.update(ok=self._try(esc))); th.start(); th.join(self.timeout)
            if th.is_alive(): err = f"timed out after {self.timeout}s"; continue
            if res.get("ok") is True: err = None; break
            err = res.get("ok"); time.sleep(0.05 * (k + 1))
        c = _con(self.state)
        c.sql("update escalations set notify_status=?, notify_error=? where escalation_id=?", params=["sent" if err is None else "failed", err, esc["escalation_id"]]); c.close()
    def _try(self, esc):
        try: self.n.send(esc); return True
        except Exception as e: return f"{type(e).__name__}: {e}"
    def wait(self, t=15): [x.join(t) for x in self.threads]
# ---------------------------------------------------------------- store + lifecycle
def needs_escalation(f):
    drivers = f.get("drivers", []); confirmed = [d for d in drivers if d.get("confidence") in ("high", "medium")]
    return bool(f.get("unexplained_note")) or not confirmed
def create_from_result(res, dispatcher=None, state=None, now=None, due_days=14, clues=()):
    """-> escalation dict or None. Idempotent per (lender, scope, metric, bucket, question set): a repeat re-asks instead of duplicating."""
    if res.get("status") != "complete" or not needs_escalation(res["findings"]): return None
    inv, f = res["investigation"], res["findings"]; now = now or datetime.datetime.now(); ents = entities(inv, res.get("evidence"))
    qs = [q for q in f.get("escalation_questions", []) if check_question(q, ents) is None]
    if not qs: qs = fallback_questions(inv, list(clues))
    qs = qs[:3]; lender = inv["node"].split("|")[0]; scope = " / ".join(inv["node"].split("|")[1:]) or "ALL"; month = pd_month(inv["month"])
    qh = hashlib.sha1("|".join([lender, scope, inv["metric"], inv["bucket_from"]] + sorted(q.lower() for q in qs)).encode()).hexdigest()[:12]
    c = _con(state); ex = c.sql("select escalation_id, reask_count from escalations where question_hash=? and status in ('open','answered')", params=[qh]).fetchone()
    if ex:
        c.sql("update escalations set reask_count = reask_count + 1 where escalation_id=?", params=[ex[0]]); c.close(); return {"escalation_id": ex[0], "deduplicated": True}
    n = c.sql("select count(*) from escalations where lender_id=? and strftime(month_date,'%Y%m')=?", params=[lender, month.strftime("%Y%m")]).fetchone()[0] + 1
    ex_acc = abs(float(inv.get("excess_accounts") or 0)); pri = "high" if ex_acc >= 100 else "medium" if ex_acc >= 40 else "low"
    esc = dict(escalation_id=f"E-{lender[-1]}-{month:%Y%m}-{n:02d}", lender_id=lender, month_date=month, scope=scope, metric=inv["metric"], bucket_from=inv["bucket_from"], questions=qs,
               priority=pri, excess_accounts=ex_acc, status="open", created_at=now, due_at=now + datetime.timedelta(days=due_days), notify_status="queued", question_hash=qh)
    c.sql("insert into escalations (escalation_id,lender_id,month_date,scope,metric,bucket_from,questions,priority,excess_accounts,status,created_at,due_at,notify_status,reask_count,question_hash) values (?,?,?,?,?,?,?,?,?,?,?,?,?,0,?)",
          params=[esc["escalation_id"], lender, month, scope, esc["metric"], esc["bucket_from"], json.dumps(qs), pri, ex_acc, "open", now, esc["due_at"], "queued", qh]); c.close()
    if dispatcher: dispatcher.dispatch(esc)
    return esc
def pd_month(m):
    m = datetime.datetime.fromisoformat(str(m)[:10]); return datetime.date(m.year, m.month, 1)
def record_answer(escalation_id, answer, answered_by, state=None, now=None):
    c = _con(state); c.sql("update escalations set answer=?, answered_by=?, answered_at=?, status='answered' where escalation_id=?", params=[answer, answered_by, now or datetime.datetime.now(), escalation_id]); c.close()
def close(escalation_id, resolution, state=None):
    c = _con(state); c.sql("update escalations set status='closed', resolution=? where escalation_id=?", params=[resolution, escalation_id]); c.close()
def followups_text(lender, state=None):
    """text for next month's Detective brief: answered-but-not-closed escalations become hypotheses to TEST (an answer is a lead, not proof)."""
    c = _con(state); rows = c.sql("select escalation_id, scope, bucket_from, metric, questions, answer, answered_by from escalations where lender_id=? and status='answered' order by answered_at", params=[lender]).fetchall(); c.close()
    if not rows: return ""
    return "OPERATIONS REPLIES to earlier escalations (treat as hypotheses to test with a control group, not as facts):\n" + "\n".join(
        f"- {r[0]} ({r[1]}, {r[2]} {r[3]}) asked: {' / '.join(json.loads(r[4]))}\n  reply from {r[6]}: {r[5]}" for r in rows) + "\n\n"
def overdue(state=None, now=None):
    c = _con(state); df = c.sql("select escalation_id, lender_id, scope, due_at, priority from escalations where status='open' and due_at < ? order by due_at", params=[now or datetime.datetime.now()]).df(); c.close(); return df
def open_section(lender, state=None):
    """markdown for the pack's non-blocking 'Open questions for operations' section."""
    c = _con(state); rows = c.sql("select escalation_id, scope, bucket_from, metric, questions, priority, reask_count, due_at from escalations where lender_id=? and status='open' order by case priority when 'high' then 0 when 'medium' then 1 else 2 end, due_at", params=[lender]).fetchall(); c.close()
    if not rows: return ""
    return "## Open questions for operations\n\n" + "\n".join(f"**{r[0]}** ({r[1]}, {r[2]} {r[3].replace('_',' ')}, {r[5]} priority{', asked again' if r[6] else ''}, reply by {r[7]:%d %b})\n" + "\n".join(f"{i}. {q}" for i, q in enumerate(json.loads(r[4]), 1)) + "\n" for r in rows)
