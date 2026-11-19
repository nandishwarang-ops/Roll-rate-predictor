"""Section 24: Agent 3 - Review Pack Author + NUMERIC AUDITOR.
Guarantee: no number in the pack was typed by a model. The author (template or LLM) writes prose with fact TOKENS like {{F012}}; every token resolves to a value that a tool
computed (roll-up, attribution, forecast run, registry...) and is formatted by code. The auditor then checks, independently of whoever wrote the text:
  1. every token exists;  2. no numeric literal outside tokens (except years, bucket labels, ids, list markers, the '80%' range label, '3-month');
  3. every number in the RENDERED text matches some fact's formatted value (catches hand edits after rendering);
  4. direction words (rose/fell/higher/lower...) agree with the sign of the fact they describe;
  5. every driver paragraph carries citations (query ids Q###, attribution ids A###) that exist in this run's evidence ledger, and every forecast section names its model run id.
Two authors share this contract: a deterministic TEMPLATE author (always available, the fallback) and an LLM author (needs ANTHROPIC_API_KEY) whose output must pass the same audit."""
import json, pathlib, re, sys, datetime
import numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
root = pathlib.Path(__file__).resolve().parent.parent
MONTHLY = lambda d: pd.Timestamp(d).strftime("%B %Y")
# ------------------------------------------------------------------ facts
class Facts:
    def __init__(self): self.f = {}; self.n = 0
    def add(self, label, value, kind, source, signed=False):
        """kind: int | pct (fraction -> 12.3%) | pp (points, signed) | ratio | text. Returns the token '{{Fnnn}}'."""
        self.n += 1; fid = f"F{self.n:03d}"; self.f[fid] = dict(id=fid, label=label, value=value, kind=kind, source=source, signed=signed or kind == "pp"); return "{{" + fid + "}}"
    def fmt(self, fid):
        x = self.f[fid]; v = x["value"]; k = x["kind"]
        if v is None or (isinstance(v, float) and np.isnan(v)): return "n/a"
        if k == "int": return f"{v:,.0f}"
        if k == "pct": return f"{100 * v:.1f}%"
        if k == "pp": return f"{abs(v):.1f} points" if not x.get("keep_sign") else f"{v:+.1f} points"
        if k == "ratio": return f"{100 * v:.0f}%"
        return str(v)
    def numbers_of(self, fid): return set(re.findall(r"\d[\d,]*(?:\.\d+)?", self.fmt(fid)))
    def catalogue(self): return [dict(id=i, label=x["label"], value=self.fmt(i), source=x["source"]) for i, x in self.f.items()]
TOKEN = re.compile(r"\{\{(F\d+)\}\}")
def render(md, facts): return TOKEN.sub(lambda m: facts.fmt(m.group(1)) if m.group(1) in facts.f else m.group(0), md)
# ------------------------------------------------------------------ audit
ALLOW = [r"\[[^\]]*\]", r"`[^`]*`", r"\b20\d\d\b", r"\b(?:1-30|31-60|61-90|90\+?)\b", r"\b80%", r"\b3-month\b", r"\(3 months\)", r"\b3 months\b", r"\b(?:90|60|30)[- ]days?\b", r"^\s*\d+\.\s", r"^#+\s*\d+\.?\s", r"\bQ\d{3}\b|\bA\d{3}\b|\bD-[A-Z]-\d{3}\b|\bE-[A-Z]-\d+-\d+\b|\bF\d{3}\b", r"\|\s*-+\s*(?=\|)", r"\bStage\s[123]\b|\bInd-AS 109\b|\bPS-03\b"]
NUM = re.compile(r"(?<![\w.])[+-]?\d[\d,]*(?:\.\d+)?%?")
UP, DOWN = re.compile(r"\b(rose|rise|rises|rising|up|higher|increase[sd]?|grew|growth|worsen\w*|elevated|above)\b", re.I), re.compile(r"\b(fell|fall|falls|falling|down|lower|decrease[sd]?|declin\w*|improv\w*|below|dropped)\b", re.I)
def _strip(text):
    for a in ALLOW: text = re.sub(a, " ", text, flags=re.M)
    return text
def audit(md, facts, evidence_ids=(), sections=None):
    """audit TOKENISED text (before rendering). -> list of issues (empty = clean)."""
    issues = []
    for m in TOKEN.finditer(md):
        if m.group(1) not in facts.f: issues.append(f"unknown fact token {m.group(0)}")
    body = TOKEN.sub(" ", md)
    for n in NUM.findall(_strip(body)):
        if re.fullmatch(r"[+-]?\d+", n) and int(re.sub(r"[+-]", "", n)) in (1, 2, 3) and False: continue
        issues.append(f"number '{n}' typed in prose instead of a fact token")
    for m in TOKEN.finditer(md):                                                          # direction agrees with sign
        fid = m.group(1)
        if fid in facts.f and facts.f[fid]["signed"] and isinstance(facts.f[fid]["value"], (int, float)):
            pre = md[max(0, m.start() - 45):m.start()]; up, dn = list(UP.finditer(pre)), list(DOWN.finditer(pre)); v = facts.f[fid]["value"]
            last = max([(x.end(), "up") for x in up] + [(x.end(), "down") for x in dn], default=(0, None))[1]
            if last == "up" and v < 0 or last == "down" and v > 0: issues.append(f"direction word contradicts the sign of {fid} ({facts.f[fid]['label']})")
    ids = set(evidence_ids)
    for cit in re.findall(r"\b([QA]\d{3})\b", md):
        if cit not in ids: issues.append(f"citation {cit} is not in this run's evidence ledger")
    if sections:
        for name, body_ in sections.items():
            if name.startswith("Drivers"):
                for par in re.split(r"(?m)^### ", body_)[1:]:
                    if not re.search(r"\b[QA]\d{3}\b", par): issues.append(f"driver paragraph without evidence citation: {par.strip().splitlines()[0][:60]}")
            if name.startswith(("Outlook", "Forecast")) and not re.search(r"fc_[A-Z_]+_\d{4}-\d{2}_\w+|model run", body_): issues.append(f"section '{name}' does not name its model run id")
    return issues
def audit_rendered(text, facts):
    """audit FINAL text: every number must be one of the formatted fact values (catches edits after rendering)."""
    allowed = set(); [allowed.update(facts.numbers_of(i)) for i in facts.f]
    norm = lambda s: s.replace(",", "").rstrip("%").lstrip("+-")
    allowed_n = {norm(a) for a in allowed}; bad = []
    for n in NUM.findall(_strip(text)):
        if norm(n) not in allowed_n: bad.append(f"rendered number '{n}' matches no fact value")
    return bad
# ------------------------------------------------------------------ deterministic template author
def build_facts(ctx):
    """ctx: lender, origin, rollup (section 22 DataFrame), drivers [dict], movers (shift-share DataFrame + total pp + label), run_id, escalation_md, dq, calibration."""
    F = Facts(); ru = ctx["rollup"]; L = ctx["lender"]; R = {}
    g = ru[(ru.level == "lender")]
    def row(metric, h): return g[(g.metric == metric) & (g.h == h)].iloc[0]
    for m in ["npa_accounts", "npa_additions", "npa_principal", "npa_ratio", "live_accounts", "stage2_principal"]:
        a = row(m, 1); kind = "pct" if m == "npa_ratio" else "int"; R[f"{m}_now"] = F.add(f"{m} at {MONTHLY(ctx['origin'])} (actual)", a.actual_origin, kind, "D1 closing state at origin")
        for h in (1, 2, 3):
            r = row(m, h); src = f"simulation {ctx['run_id']} (section 21), month +{h}"
            R[f"{m}_p50_{h}"] = F.add(f"{m} forecast median, month +{h}", r.p50, kind, src); R[f"{m}_lo_{h}"] = F.add(f"{m} P10, month +{h}", r.p10, kind, src); R[f"{m}_hi_{h}"] = F.add(f"{m} P90, month +{h}", r.p90, kind, src)
        R[f"{m}_chg3"] = F.add(f"{m} change over 3 months (median minus actual)", row(m, 3).p50 - a.actual_origin, "pp" if False else kind, src, signed=True)
        F.f[R[f"{m}_chg3"].strip("{}")]["kind"] = "int" if kind == "int" else "pct"
    for b in ["CURRENT", "1-30", "31-60", "61-90"]:
        for met in ["roll_forward", "cure"]:
            if met == "cure" and b == "CURRENT": continue
            a = row(f"{met}_{b}", 1); R[f"{met}_{b}_now"] = F.add(f"{met} rate {b}, actual", a.actual_origin, "pct", "mart.moves_lender")
            for h in (1, 3):
                r = row(f"{met}_{b}", h); R[f"{met}_{b}_p50_{h}"] = F.add(f"{met} {b} forecast median, month +{h}", r.p50, "pct", f"simulation {ctx['run_id']}"); R[f"{met}_{b}_lo_{h}"] = F.add(f"{met} {b} P10, +{h}", r.p10, "pct", ""); R[f"{met}_{b}_hi_{h}"] = F.add(f"{met} {b} P90, +{h}", r.p90, "pct", "")
    ctx["R"] = R; return F
def _movers_md(ctx, F):
    mv = ctx.get("movers"); 
    if not mv: return "No segment-level movement analysis was requested for this pack.\n"
    ss, tot, label = mv["table"], mv["total_pp"], mv["label"]; t = F.add(f"lender-level change in {label}", tot, "pp", mv["source"], signed=True); F.f[t.strip("{}")]["keep_sign"] = False
    word = "rose" if tot > 0 else "fell"; lines = [f"The lender-level {label} {word} by {t} in {MONTHLY(mv['month'])}. The segments that moved it most:\n", "| Segment | Contribution to the change |", "|---|---|"]
    for seg, r in ss.head(4).iterrows():
        c = F.add(f"contribution of {seg}", r.total_pp, "pp", mv["source"], signed=True); F.f[c.strip("{}")]["keep_sign"] = True; lines.append(f"| {seg.replace('|', ' / ').replace('_', ' ').title()} | {c} |")
    mixt, ratet = F.add("mix effect total", ss.mix_pp.sum(), "pp", mv["source"], signed=True), F.add("rate effect total", ss.rate_pp.sum(), "pp", mv["source"], signed=True)
    F.f[mixt.strip("{}")]["keep_sign"] = F.f[ratet.strip("{}")]["keep_sign"] = True
    return "\n".join(lines) + f"\n\nOf the total, the mix of accounts contributed {mixt} and changed behaviour within the same kind of account contributed {ratet}.\n"
def template_author(ctx, F):
    R, L, O = ctx["R"], ctx["lender"], ctx["origin"]; rid = ctx["run_id"]; m1, m3 = pd.Timestamp(O) + pd.DateOffset(months=1), pd.Timestamp(O) + pd.DateOffset(months=3); S = {}
    drivers = ctx.get("drivers", [])
    if drivers:
        d = drivers[0]; ch = F.add(f"observed change in {d['pool_label']}", d["observed_change_pp"], "pp", d["attribution_id"], signed=True)
        head = f"{d['pool_label']} {'rose' if d['observed_change_pp'] > 0 else 'fell'} by {ch} in {MONTHLY(O)}; the main finding: {d['what']} ({d['category'].replace('_', ' ')}). [{', '.join(d['evidence_ids'])}]"
    else: head = f"No unusual movement was found for {L} in {MONTHLY(O)}; the forecast below follows the statistical baseline."
    S["Headline"] = head
    S["Outlook (3 months)"] = (f"Model run `{rid}`. At {MONTHLY(O)} close, {R['npa_accounts_now']} loans were more than 90 days past due ({R['npa_ratio_now']} of live loans). "
        f"We expect {R['npa_accounts_p50_3']} in {MONTHLY(m3)} (80% range {R['npa_accounts_lo_3']} to {R['npa_accounts_hi_3']}), a change of {R['npa_accounts_chg3']}. "
        f"Loans newly entering the 90+ bucket should be about {R['npa_additions_p50_1']} in {MONTHLY(m1)} (80% range {R['npa_additions_lo_1']} to {R['npa_additions_hi_1']}); "
        f"principal in Stage 3 should be about {R['npa_principal_p50_3']} rupees in {MONTHLY(m3)} (80% range {R['npa_principal_lo_3']} to {R['npa_principal_hi_3']}).")
    rows = ["| Opening bucket | Roll-forward now | Forecast " + MONTHLY(m1) + " | Forecast " + MONTHLY(m3) + " (80% range) |", "|---|---|---|---|"]
    for b in ["CURRENT", "1-30", "31-60", "61-90"]: rows.append(f"| {b} | {R[f'roll_forward_{b}_now']} | {R[f'roll_forward_{b}_p50_1']} | {R[f'roll_forward_{b}_p50_3']} ({R[f'roll_forward_{b}_lo_3']} to {R[f'roll_forward_{b}_hi_3']}) |")
    S["Forecast by bucket"] = f"Source: model run `{rid}`. Roll-forward means the share of loans in a bucket that end the month in a worse bucket.\n\n" + "\n".join(rows)
    S["What moved"] = _movers_md(ctx, F)
    if drivers:
        parts = []
        for d in drivers:
            sc = ", ".join(f"{s['name']} ({F.add('scenario weight ' + s['name'], s['weight'], 'ratio', 'classifier ' + d['driver_id'])})" for s in d["scenarios"])
            att = ""
            if d.get("contribution_pp") is not None:
                c = F.add(f"contribution of {d['what']}", d["contribution_pp"], "pp", d["attribution_id"], signed=True); lo, hi = F.add("contribution low", d["contribution_pp_80"][0], "pp", d["attribution_id"], signed=True), F.add("contribution high", d["contribution_pp_80"][1], "pp", d["attribution_id"], signed=True)
                F.f[c.strip("{}")]["keep_sign"] = False; F.f[lo.strip("{}")]["keep_sign"] = F.f[hi.strip("{}")]["keep_sign"] = True
                verb = "added" if d["contribution_pp"] >= 0 else "subtracted"
                att = f" Compared with its control group, this cause {verb} {c} {'to' if verb == 'added' else 'from'} the pool's rate (80% range {lo} to {hi})."
                sh = d.get("share_of_change")
                if sh is not None and 0 <= sh <= 1.05:
                    att += f" That is {F.add('share of change', sh, 'ratio', d['attribution_id'])} of the observed movement."
                    if d.get("unexplained_share") is not None: att += f" The remainder, {F.add('unexplained share', d['unexplained_share'], 'ratio', d['attribution_id'])}, is not explained by this cause."
                else:
                    ctl = F.add("control group movement", d["control_change_pp"], "pp", d["attribution_id"], signed=True); F.f[ctl.strip("{}")]["keep_sign"] = True
                    att += f" The rest of the pool moved by {ctl}, so a share of the net movement is not meaningful here; both effects are real and they partly offset each other."
            parts.append(f"### {d['what'][0].upper() + d['what'][1:]}\n\n**What:** {d['what']}. **Where:** {d['where']}. **When:** since {d['start_label']}. **Category:** {d['category'].replace('_', ' ')}. **Registry status:** {d['status'].replace('_', ' ')} ({d['driver_id']}).{att} Control group: {d['control_group_note']}. Forecast scenarios: {sc}. [{', '.join(d['evidence_ids'])}]")
        S["Drivers"] = "\n\n".join(parts)
    else: S["Drivers"] = "No driver was confirmed this month."
    ch = ctx.get("changes")
    S["Changes since last month"] = "\n".join(f"- {r.driver_id}: {r.what} moved from {r.from_status.replace('_', ' ')} to {r.to_status.replace('_', ' ')}." for r in ch.itertuples()) if ch is not None and len(ch) else "No driver changed status since last month."
    esc = ctx.get("escalations") or []; parts = []
    for e in esc:
        due = F.add(f"reply-by date for {e['id']}", pd.Timestamp(e["due"]).strftime("%d %b %Y"), "text", "escalation store")
        parts.append(f"**{e['id']}** ({e['scope']}, {e['bucket_from']} bucket, {e['priority']} priority{', asked again' if e.get('reask_count') else ''}; reply by {due})\n\n" + "\n".join(f"{i}. {q}" for i, q in enumerate(e["questions"], 1)))
    S["Open questions for operations"] = "\n\n".join(parts) if parts else "No open questions."
    dq, cal = ctx.get("dq"), ctx.get("calibration")
    meth = "**Method.** Roll-rates are forecast per segment with an ensemble of three statistical models; a change-detection step flags unusual months; each flagged movement is investigated by testing hypotheses against control groups; effects are quantified by a deterministic calculator, never estimated by the writing model. Ranges come from simulating the full three-month chain with errors calibrated on past forecasts."
    if cal: meth += f" In back-tests the 80% ranges covered the actual outcome between {F.add('min coverage', cal['min_cov'], 'ratio', 'docs/range_calibration.md')} and {F.add('max coverage', cal['max_cov'], 'ratio', 'docs/range_calibration.md')} of the time."
    if dq: meth += f" Data checks: {F.add('checks passed', dq['PASS'], 'int', 'docs/data_quality_report.json')} passed, {F.add('checks warned', dq['WARN'], 'int', 'docs/data_quality_report.json')} warned, {F.add('checks failed', dq['FAIL'], 'int', 'docs/data_quality_report.json')} failed."
    inc = ctx.get("incomplete") or []
    if inc: meth += f" {F.add('incomplete investigations', len(inc), 'int', 'run record')} flagged movement(s) could not be investigated automatically this month ({'; '.join(inc)}); those segments keep their statistical baseline forecast."
    S["Methodology and limits"] = meth + " New loans are assumed to continue at the recent average pace, and principal per account is held at its latest level."
    return S
def assemble(S): return "\n\n".join(f"## {k}\n\n{v}" if k != "Headline" else f"# {v}" for k, v in S.items())
# ------------------------------------------------------------------ LLM author (same audit)
SYSTEM = """You write the monthly roll-rate review pack for a lender's risk team, in plain language for non-technical readers.
HARD RULES: (1) Never type a number. Every figure must be a fact token from the catalogue, written exactly like {{F012}}. (2) Years and bucket labels (1-30, 31-60, 61-90, 90+) may be written normally. (3) Every driver paragraph must cite the evidence ids it relies on, like [Q003, A001]. (4) The Outlook and Forecast sections must name the model run id. (5) Direction words (rose, fell, higher, lower) must match the sign of the fact they describe. (6) Cover improvements as well as deteriorations. (7) Say plainly what is unexplained. Submit with submit_pack."""
SUBMIT = {"name": "submit_pack", "description": "Submit the pack sections as markdown with fact tokens.", "input_schema": {"type": "object", "required": ["sections"], "properties": {"sections": {"type": "object", "description": "section title -> markdown. Use the same titles as the draft.", "additionalProperties": {"type": "string"}}}}}
def llm_author(ctx, F, draft, client, evidence_ids, max_turns=5):
    msgs = [{"role": "user", "content": "FACT CATALOGUE (use tokens only):\n" + json.dumps(F.catalogue()) + "\n\nSECTION TITLES AND DRAFT (improve the wording; keep tokens and citations):\n" + json.dumps(draft) + f"\n\nModel run id: {ctx['run_id']}\nEvidence ids available: {sorted(evidence_ids)}"}]
    for _ in range(max_turns):
        r = client.create(SYSTEM, msgs, [SUBMIT]); msgs.append({"role": "assistant", "content": r["content"]}); calls = [b for b in r["content"] if b["type"] == "tool_use"]
        if not calls: msgs.append({"role": "user", "content": "Call submit_pack."}); continue
        c = calls[0]; secs = c["input"].get("sections", {}); issues = audit(assemble(secs), F, evidence_ids, secs)
        if not issues: return secs, "llm", []
        msgs.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": c["id"], "content": "REJECTED by the numeric auditor - fix and resubmit:\n- " + "\n- ".join(issues[:12])}]})
    return draft, "template (LLM output failed the audit)", issues
def build_pack(ctx, client=None, out_dir=root / "outputs/packs"):
    F = build_facts(ctx); draft = template_author(ctx, F); ev = set(ctx.get("evidence_ids", [])); issues = audit(assemble(draft), F, ev, draft); source = "template"; llm_issues = []
    if issues: raise AssertionError("template author failed its own audit: " + "; ".join(issues))
    secs = draft
    if client is not None: secs, source, llm_issues = llm_author(ctx, F, draft, client, ev)
    md = render(assemble(secs), F); rendered_issues = audit_rendered(md, F)
    if rendered_issues: raise AssertionError("rendered pack failed the numeric audit: " + "; ".join(rendered_issues))
    out_dir.mkdir(parents=True, exist_ok=True); stem = f"{ctx['lender']}_{str(ctx['origin'])[:7]}"
    (out_dir / f"{stem}.md").write_text(md); (out_dir / f"{stem}.facts.json").write_text(json.dumps(F.catalogue(), indent=1))
    (out_dir / f"{stem}.audit.json").write_text(json.dumps({"source": source, "tokenised_issues": llm_issues, "rendered_issues": rendered_issues, "facts": len(F.f), "run_id": ctx["run_id"]}, indent=1))
    return dict(markdown=md, facts=F, sections=secs, source=source, path=str(out_dir / f"{stem}.md"), llm_issues=llm_issues)

def escalations_for(lender, state=None):
    import escalations as E
    c = E._con(state); rows = c.sql("select escalation_id, scope, bucket_from, priority, due_at, questions, reask_count from escalations where lender_id=? and status='open' order by case priority when 'high' then 0 when 'medium' then 1 else 2 end", params=[lender]).fetchall(); c.close()
    return [dict(id=r[0], scope=r[1], bucket_from=r[2], priority=r[3], due=r[4], questions=json.loads(r[5]), reask_count=r[6]) for r in rows]
