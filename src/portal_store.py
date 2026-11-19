"""Section 30: review-portal state (SQLite) + the pack lifecycle state machine + a hash-chained log of every human action.
Pack states: draft -> in_review -> approved -> delivered (or rejected / superseded). Rules enforced HERE, not in the UI:
  * only analysts review/approve/reject/deliver; lender users only ever see their own lender's DELIVERED packs
  * four-eyes: the approver must differ from the person who started the run (switchable for a demo)
  * approval needs a clean numeric audit and an intact trace chain; delivery re-verifies the manifest hashes and the trace chain, so an edited pack cannot go out."""
import sqlite3, json, pathlib, threading, datetime, shutil, hashlib, sys
from werkzeug.security import generate_password_hash, check_password_hash
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from audit_trace import sha, canon, GENESIS, verify_chain, redact
SCHEMA = """
create table if not exists users (username text primary key, pw_hash text not null, role text not null check (role in ('analyst','lender')), lender text, active integer default 1);
create table if not exists runs (id text primary key, lender text not null, month text not null, requested_by text not null, status text not null, pack_state text not null default 'none', investigator text, started text, finished text, secs real,
  out_root text, pack_dir text, trace_path text, record_path text, error text, reviewed_by text, approved_by text, approved_at text, delivered_at text, delivered_dir text, note text);
create table if not exists comments (id integer primary key autoincrement, run_id text, username text, ts text, body text);
"""
now = lambda: datetime.datetime.now().isoformat(timespec="seconds")
class Store:
    def __init__(self, base, four_eyes=True):
        self.base = pathlib.Path(base); self.base.mkdir(parents=True, exist_ok=True); self.db = self.base / "portal.sqlite"; self.four_eyes = four_eyes; self.lock = threading.Lock()
        with self.c() as c: c.executescript(SCHEMA)
        self.audit_path = self.base / "audit.jsonl"; self.seq, self.prev = 0, GENESIS
        if self.audit_path.exists():
            for line in open(self.audit_path): e = json.loads(line); self.seq, self.prev = e["seq"], e["hash"]
    def c(self): c = sqlite3.connect(self.db, timeout=30); c.row_factory = sqlite3.Row; return c
    # ---------------------------------------------------------------- human-action audit (hash chain, continues across restarts)
    def log(self, actor, type, summary, payload=None):
        with self.lock:
            self.seq += 1; ev = {"seq": self.seq, "ts": now(), "actor": actor, "type": type, "summary": str(summary)[:300], "payload": redact(payload or {})}; ev["prev"] = self.prev
            ev["hash"] = sha(self.prev + canon({k: v for k, v in ev.items() if k != "hash"})); self.prev = ev["hash"]
            with open(self.audit_path, "a") as f: f.write(json.dumps(ev, default=str) + "\n")
    def verify_audit(self): return verify_chain(self.audit_path) if self.audit_path.exists() else (True, None, "empty")
    def events_for(self, run_id): return [e for e in (json.loads(l) for l in open(self.audit_path)) if e["payload"].get("run_id") == run_id] if self.audit_path.exists() else []
    # ---------------------------------------------------------------- users
    def create_user(self, username, password, role, lender=None):
        if role == "lender" and not lender: raise ValueError("lender users need a lender")
        if len(password) < 10: raise ValueError("password must be at least 10 characters")
        with self.c() as c: c.execute("insert or replace into users (username, pw_hash, role, lender, active) values (?,?,?,?,1)", (username, generate_password_hash(password, method="pbkdf2:sha256:600000"), role, lender))
        self.log("system", "user_created", f"user {username} ({role}{', ' + lender if lender else ''})", {"username": username, "role": role})
    def user(self, username):
        with self.c() as c: r = c.execute("select * from users where username=? and active=1", (username,)).fetchone()
        return dict(r) if r else None
    def check_login(self, username, password):
        u = self.user(username); return u if u and check_password_hash(u["pw_hash"], password) else None
    # ---------------------------------------------------------------- runs
    def create_run(self, lender, month, user, investigator):
        with self.lock, self.c() as c:
            n = c.execute("select count(*) from runs where lender=? and month=?", (lender, month)).fetchone()[0] + 1; rid = f"{lender[-1]}-{month[:7]}-{n:02d}"
            c.execute("insert into runs (id, lender, month, requested_by, status, investigator, started) values (?,?,?,?,?,?,?)", (rid, lender, month[:7], user, "queued", investigator, now()))
        self.log(user, "run_requested", f"run {rid} for {lender} {month[:7]}", {"run_id": rid}); return rid
    def active_run(self, lender, month):
        with self.c() as c: r = c.execute("select id from runs where lender=? and month=? and status in ('queued','running')", (lender, month[:7])).fetchone()
        return r[0] if r else None
    def update(self, rid, **kw):
        with self.c() as c: c.execute(f"update runs set {', '.join(k + '=?' for k in kw)} where id=?", (*kw.values(), rid))
    def run(self, rid):
        with self.c() as c: r = c.execute("select * from runs where id=?", (rid,)).fetchone()
        return dict(r) if r else None
    def runs(self, lender=None, delivered_only=False):
        q, a = "select * from runs", []; w = []
        if lender: w.append("lender=?"); a.append(lender)
        if delivered_only: w.append("pack_state='delivered'")
        with self.c() as c: return [dict(r) for r in c.execute(q + (" where " + " and ".join(w) if w else "") + " order by started desc", a).fetchall()]
    def comment(self, rid, user, body):
        with self.c() as c: c.execute("insert into comments (run_id, username, ts, body) values (?,?,?,?)", (rid, user, now(), body[:2000]))
        self.log(user, "comment", f"comment on {rid}", {"run_id": rid, "chars": len(body)})
    def comments(self, rid):
        with self.c() as c: return [dict(r) for r in c.execute("select * from comments where run_id=? order by id", (rid,)).fetchall()]
    # ---------------------------------------------------------------- pack lifecycle
    def check_pack(self, run):
        """-> list of blocking problems for approval/delivery: numeric audit, trace chain, manifest hashes."""
        probs = []; pd_ = pathlib.Path(run["pack_dir"] or "")
        if not (pd_ / "pack.pdf").exists(): return ["no pack was produced for this run"]
        man = json.loads((pd_ / "manifest.json").read_text())
        for f, h in man["files"].items():
            p = pd_ / f
            if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != h: probs.append(f"file {f} does not match the manifest (edited after generation)")
        if run["trace_path"] and pathlib.Path(run["trace_path"]).exists():
            ok, bad, msg = verify_chain(run["trace_path"]); 
            if not ok: probs.append(f"audit trace chain broken: {msg}")
        else: probs.append("audit trace is missing")
        if (man.get("audit") or {}).get("rendered_issues"): probs.append("the numeric audit reported issues")
        return probs
    def transition(self, rid, user, action, note=""):
        """-> (ok, message). The only place pack state changes."""
        r = self.run(rid)
        if not r: return False, "unknown run"
        if user["role"] != "analyst": return False, "only analysts can do this"
        st = r["pack_state"]; u = user["username"]
        if action == "start_review":
            if st != "draft": return False, f"cannot start review from state '{st}'"
            self.update(rid, pack_state="in_review", reviewed_by=u)
        elif action == "approve":
            if st != "in_review": return False, "approve only after review has started"
            if self.four_eyes and u == r["requested_by"]: return False, "four-eyes: the approver must be a different person from the one who started the run"
            probs = self.check_pack(r)
            if probs: return False, "cannot approve: " + "; ".join(probs)
            self.update(rid, pack_state="approved", approved_by=u, approved_at=now(), note=note)
        elif action == "reject":
            if st not in ("draft", "in_review"): return False, f"cannot reject from state '{st}'"
            if not note.strip(): return False, "a reason is required"
            self.update(rid, pack_state="rejected", note=note)
        elif action == "supersede":
            if st in ("delivered", "none"): return False, f"cannot supersede from state '{st}'"
            self.update(rid, pack_state="superseded", note=note)
        elif action == "deliver":
            if st != "approved": return False, "only an approved pack can be delivered"
            probs = self.check_pack(r)
            if probs: return False, "delivery blocked: " + "; ".join(probs)
            dest_root = self.base / "delivered" / r["lender"] / r["month"]; n = len(list(dest_root.glob("v*"))) + 1 if dest_root.exists() else 1; dest = dest_root / f"v{n}"
            shutil.copytree(r["pack_dir"], dest, ignore=shutil.ignore_patterns("preview_*"))
            with self.c() as c:
                c.execute("update runs set pack_state='superseded' where lender=? and month=? and pack_state='delivered' and id<>?", (r["lender"], r["month"], rid))
                c.execute("update runs set pack_state='delivered', delivered_at=?, delivered_dir=? where id=?", (now(), str(dest), rid))
        else: return False, "unknown action"
        self.log(u, f"pack_{action}", f"{action} {rid}", {"run_id": rid, "from": st, "note": note[:200]}); return True, f"{action} done"
