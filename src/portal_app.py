"""Section 30: the review portal (Flask). Run -> review -> approve -> deliver, plus a read-only lender view.
Runs locally by default (127.0.0.1). Sign-in is a local username/password store with two roles (analyst, lender) - it is NOT a production identity system.
Security: passwords hashed, signed httponly session cookie, CSRF token on every POST, authorization checked in the route AND in the store, lender users can only reach their own
lender's delivered packs, file serving is whitelisted and path-checked, all output auto-escaped, login throttled, every human action written to a hash-chained log."""
import os, sys, json, pathlib, secrets, threading, time, re, datetime
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from flask import Flask, request, session, redirect, url_for, render_template, abort, send_file, jsonify, flash
from werkzeug.security import safe_join
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from portal_store import Store
root = pathlib.Path(__file__).resolve().parent.parent
LENDERS = {"LENDER_A": "Lender A (Sahyadri Finserv)", "LENDER_B": "Lender B (Kaveri Auto & Personal Finance)", "LENDER_C": "Lender C (Nimbus Digital Lending)"}
SERVE_EXT = {".pdf", ".md", ".png", ".csv", ".json", ".txt"}
RUN_LOCK = threading.Lock()            # runs are serialised: the shared preparation step opens the database read-write
def default_runner(lender, month, out_root, state_path):
    import orchestrator as O
    O.prepare(month)
    client = None
    if os.environ.get("ANTHROPIC_API_KEY"):
        from detective import AnthropicClient; client = AnthropicClient()
    return O.run_lender(O.RunConfig(lender=lender, origin=month, client=client, state_path=state_path, out_root=out_root))
def months_available():
    try:
        import duckdb; c = duckdb.connect(str(root / "rollrate.duckdb"), read_only=True); m = [str(x[0])[:7] for x in c.sql("select distinct month from mart.investigations order by 1").fetchall()]; c.close(); return m
    except Exception: return ["2025-03", "2025-06", "2025-09"]
def create_app(base=None, runner=None, four_eyes=True, secret=None, months=None):
    base = pathlib.Path(base or root / "outputs/portal"); store = Store(base, four_eyes=four_eyes); app = Flask(__name__, template_folder=str(root / "src/portal_templates"))
    key = base / "secret.key"
    if secret is None:
        if not key.exists(): key.write_text(secrets.token_hex(32))
        secret = key.read_text()
    app.config.update(SECRET_KEY=secret, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", MAX_CONTENT_LENGTH=64 * 1024); app.store = store
    runner = runner or default_runner; pool = ThreadPoolExecutor(max_workers=1); fails = {}; MONTHS = months or months_available()
    state_path = base / "state.duckdb"
    from markupsafe import Markup, escape
    @app.template_filter("code")
    def code_filter(t):
        """escape first, then turn `identifier` into <code>identifier</code> (safe: the only markup produced is the code tag)."""
        return Markup(re.sub(r"`([^`]+)`", r"<code>\1</code>", str(escape(t if t is not None else ""))))
    # ------------------------------------------------------------ helpers
    @app.before_request
    def csrf():
        if request.method == "POST":
            tok = session.get("csrf")
            if not tok or not secrets.compare_digest(tok, request.form.get("csrf", "")): abort(400, "missing or invalid CSRF token")
    @app.after_request
    def headers(r):
        r.headers["X-Content-Type-Options"] = "nosniff"; r.headers["X-Frame-Options"] = "SAMEORIGIN"; r.headers["Referrer-Policy"] = "no-referrer"; r.headers["Cache-Control"] = "no-store"
        r.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'self'"; return r
    @app.context_processor
    def ctx():
        session.setdefault("csrf", secrets.token_hex(16)); return dict(csrf=session["csrf"], me=current(), LENDERS=LENDERS)
    def current(): return store.user(session["u"]) if session.get("u") else None
    def login_required(f):
        @wraps(f)
        def w(*a, **k):
            if not current(): return redirect(url_for("login", next=request.path))
            return f(*a, **k)
        return w
    def analyst_required(f):
        @wraps(f)
        @login_required
        def w(*a, **k):
            if current()["role"] != "analyst": abort(403)
            return f(*a, **k)
        return w
    def can_see(run, u):
        if u["role"] == "analyst": return True
        return run["lender"] == u["lender"] and run["pack_state"] == "delivered"
    def pack_root(run, u): return pathlib.Path(run["pack_dir"]) if u["role"] == "analyst" else pathlib.Path(run["delivered_dir"] or "/nonexistent")
    def load_record(run):
        p = run.get("record_path"); return json.loads(pathlib.Path(p).read_text()) if p and pathlib.Path(p).exists() else {}
    def key_figures(run):
        if not run.get("pack_dir"): return []
        pm = pathlib.Path(run["out_root"]) / "packs_md" / f"{run['lender']}_{run['month']}.facts.json"
        if not pm.exists(): return []
        f = {x["label"]: x["value"] for x in json.loads(pm.read_text())}; g = lambda pre: next((v for k, v in f.items() if k.startswith(pre)), "n/a"); out = []
        out.append(("Loans 90+ days past due now", g("npa_accounts at"))); out.append(("Forecast in 3 months (median)", g("npa_accounts forecast median, month +3")))
        out.append(("80% range", f"{g('npa_accounts P10, month +3')} to {g('npa_accounts P90, month +3')}")); out.append(("New 90+ loans next month (median)", g("npa_additions forecast median, month +1"))); return out
    def start_run(lender, month, user):
        rid = store.create_run(lender, month, user["username"], "LLM Detective" if os.environ.get("ANTHROPIC_API_KEY") else "rule-based investigator (no LLM)")
        out_root = base / "runs" / rid
        def job():
            with RUN_LOCK:
                store.update(rid, status="running"); t = time.time()
                try:
                    rec = runner(lender, month + "-01", out_root, state_path); st = rec["status"]; pk = out_root / "packs" / f"{lender}_{month}"
                    store.update(rid, status=st, finished=datetime.datetime.now().isoformat(timespec="seconds"), secs=round(time.time() - t, 1), out_root=str(out_root), pack_dir=str(pk) if (pk / "pack.pdf").exists() else None,
                                 trace_path=rec.get("trace"), record_path=str(out_root / "runs" / f"{rec['run_id']}.json"), error=rec.get("error"), pack_state="draft" if (pk / "pack.pdf").exists() else "none")
                    store.log("system", "run_finished", f"{rid} {st}", {"run_id": rid, "status": st})
                except Exception as e:
                    store.update(rid, status="failed", error=f"{type(e).__name__}: {e}", finished=datetime.datetime.now().isoformat(timespec="seconds")); store.log("system", "run_failed", f"{rid}: {e}", {"run_id": rid})
        pool.submit(job); return rid
    app.start_run = start_run
    # ------------------------------------------------------------ auth
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            u = request.form.get("username", "").strip(); t = fails.get(u, (0, 0))
            if t[0] >= 5 and time.time() < t[1]: flash("Too many attempts; wait a minute."); return render_template("login.html"), 429
            user = store.check_login(u, request.form.get("password", ""))
            if user:
                fails.pop(u, None); session.clear(); session["u"] = user["username"]; session["csrf"] = secrets.token_hex(16); store.log(u, "login", f"{u} signed in")
                nxt = request.args.get("next", ""); return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("home"))
            fails[u] = (t[0] + 1, time.time() + 60); store.log(u or "?", "login_failed", f"failed sign-in for '{u[:40]}'"); flash("Wrong username or password.")
        return render_template("login.html")
    @app.post("/logout")
    def logout(): session.clear(); return redirect(url_for("login"))
    # ------------------------------------------------------------ analyst
    @app.route("/")
    @login_required
    def home():
        u = current()
        if u["role"] == "lender": return redirect(url_for("lender_home"))
        return render_template("dashboard.html", runs=store.runs(), months=MONTHS, llm=bool(os.environ.get("ANTHROPIC_API_KEY")), audit_ok=store.verify_audit())
    @app.post("/run")
    @analyst_required
    def run_new():
        lender, month = request.form.get("lender", ""), request.form.get("month", "")
        if lender not in LENDERS or month not in MONTHS: abort(400)
        if store.active_run(lender, month): flash("A run for this lender and month is already in progress."); return redirect(url_for("home"))
        rid = start_run(lender, month, current()); return redirect(url_for("home") + f"#{rid}")
    @app.get("/api/runs")
    @login_required
    def api_runs():
        u = current(); rs = store.runs() if u["role"] == "analyst" else store.runs(lender=u["lender"], delivered_only=True)
        return jsonify([{k: r[k] for k in ("id", "lender", "month", "status", "pack_state", "secs")} for r in rs])
    @app.route("/runs/<rid>")
    @login_required
    def run_view(rid):
        u = current(); r = store.run(rid)
        if not r or not can_see(r, u): abort(404)
        rec = load_record(r); view = "analyst" if u["role"] == "analyst" else "lender"; esc = []
        import pack_author as PA
        esc = PA.escalations_for(r["lender"], state_path) if state_path.exists() else []
        ev = {}
        if view == "analyst" and r.get("pack_dir") and (pathlib.Path(r["pack_dir"]) / "evidence.json").exists(): ev = json.loads((pathlib.Path(r["pack_dir"]) / "evidence.json").read_text())
        ok_tr = None
        if view == "analyst" and r.get("trace_path") and pathlib.Path(r["trace_path"]).exists():
            from audit_trace import verify_chain; ok_tr = verify_chain(r["trace_path"])
        return render_template("run.html", r=r, rec=rec, view=view, esc=esc, evidence=ev, figures=key_figures(r), comments=store.comments(rid) if view == "analyst" else [], actions=store.events_for(rid) if view == "analyst" else [], trace_ok=ok_tr,
                               problems=store.check_pack(r) if view == "analyst" and r.get("pack_dir") and r["pack_state"] in ("draft", "in_review", "approved") else [], four_eyes=store.four_eyes)
    @app.post("/runs/<rid>/act")
    @analyst_required
    def act(rid):
        action, note = request.form.get("action", ""), request.form.get("note", "")
        ok, msg = store.transition(rid, current(), action, note); flash(msg)
        if ok and action == "supersede":
            r = store.run(rid)
            if not store.active_run(r["lender"], r["month"]): start_run(r["lender"], r["month"], current()); flash("A new run was started.")
        return redirect(url_for("run_view", rid=rid))
    @app.post("/runs/<rid>/comment")
    @analyst_required
    def add_comment(rid):
        body = request.form.get("body", "").strip()
        if body and store.run(rid): store.comment(rid, current()["username"], body)
        return redirect(url_for("run_view", rid=rid) + "#comments")
    @app.post("/runs/<rid>/reply")
    @login_required
    def reply(rid):
        """operations reply to an escalation: a lender user for their own lender, or an analyst on their behalf. The reply is a hypothesis for next month's investigation."""
        u = current(); r = store.run(rid)
        if not r or not can_see(r, u): abort(404)
        eid, text = request.form.get("escalation_id", ""), request.form.get("answer", "").strip()
        import pack_author as PA, escalations as ES
        if eid not in [e["id"] for e in PA.escalations_for(r["lender"], state_path)] or not text: flash("Nothing recorded."); return redirect(url_for("run_view", rid=rid))
        ES.record_answer(eid, text[:2000], u["username"], state_path); store.log(u["username"], "escalation_reply", f"reply to {eid}", {"run_id": rid, "escalation_id": eid, "chars": len(text)}); flash("Reply recorded; it will be tested in next month's run.")
        return redirect(url_for("run_view", rid=rid))
    @app.route("/runs/<rid>/file/<path:name>")
    @login_required
    def serve(rid, name):
        u = current(); r = store.run(rid)
        if not r or not can_see(r, u): abort(404)
        if pathlib.PurePath(name).suffix.lower() not in SERVE_EXT or name.endswith("evidence.json") and u["role"] != "analyst": abort(404)
        br = pack_root(r, u); p = safe_join(str(br), name)
        if not p or not pathlib.Path(p).is_file() or not pathlib.Path(p).resolve().is_relative_to(br.resolve()): abort(404)
        store.log(u["username"], "file_viewed", f"{name} of {rid}", {"run_id": rid, "file": name}); return send_file(p)
    # ------------------------------------------------------------ lender
    @app.route("/lender")
    @login_required
    def lender_home():
        u = current()
        if u["role"] != "lender": return redirect(url_for("home"))
        return render_template("lender_home.html", runs=store.runs(lender=u["lender"], delivered_only=True))
    return app
if __name__ == "__main__":
    app = create_app(); print("Review portal on http://127.0.0.1:5057  (create users with: python src/portal_cli.py create-user ...)"); app.run(host="127.0.0.1", port=5057, debug=False, threaded=True)
