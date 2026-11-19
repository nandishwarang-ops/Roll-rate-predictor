"""Section 14: attribution engine = the ONLY place a 'how much does this cause explain' number is produced (the LLM never invents it).
For a pool (e.g. Lender A / WEST / 31-60 opening bucket) and a metric (roll_forward or cure), comparing the current window with a baseline:
  observed change  = rate_T - rate_base for the whole pool
  per cause        = a named slice (dimension in values). CONTROL-ADJUSTED EXCESS: how much more (or less) the slice moved than its control
                     (default control = the rest of the pool) -> contribution_pp = w_T(slice) * [(r_T,S - r_B,S) - (r_T,C - r_B,C)]
                     = the counterfactual 'had the slice moved like its control'. share = contribution / observed change.
  mix vs rate      = exact shift-share split over a partition dimension: mix (who is in the pool) + rate (how the same kind of account behaves) = change.
  shares + unexplained = 100%: causes cannot overlap; whatever is not attributed is reported as UNEXPLAINED (never stretched).
  uncertainty      = parametric bootstrap of every cell (400 draws) -> 80% range; a slice below MIN_T/MIN_B accounts is refused.
Every call is logged with an id (A001...) for citation, like SQL queries."""
import numpy as np, pandas as pd, pathlib, sys, json, datetime
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
root = pathlib.Path(__file__).resolve().parent.parent
MIN_T, MIN_B, MIN_CHANGE_PP, B = 50, 100, 0.3, 400
def _mask(df, spec): return df[spec["dimension"]].astype(str).isin([str(v) for v in spec["values"]])
def _cells(df, y):   # (n, k) for current / baseline
    return {p: (int(len(g)), int(g[y].sum())) for p, g in [("T", df[df.is_T]), ("B", df[~df.is_T])]}
def shift_share(df, y, dim):
    T, Bs = df[df.is_T], df[~df.is_T]; rB = Bs[y].mean(); rows = []
    for k in sorted(set(T[dim].astype(str)) | set(Bs[dim].astype(str))):
        t, b = T[T[dim].astype(str) == k], Bs[Bs[dim].astype(str) == k]
        wT, wB = len(t) / len(T), len(b) / len(Bs); rT, rBk = (t[y].mean() if len(t) else 0.0), (b[y].mean() if len(b) else rB)
        rows.append(dict(category=k, mix_pp=100 * (wT - wB) * (rBk - rB), rate_pp=100 * wT * (rT - rBk) if len(t) else 0.0, w_T=wT, w_B=wB, rate_T=rT, rate_B=rBk))
    d = pd.DataFrame(rows); d["total_pp"] = d.mix_pp + d.rate_pp; return d
def attribute(df, metric, causes, control=None, partition=None, seed=0):
    """df: account rows with is_T flag and boolean column `metric`; causes: {name: {dimension, values}}; control: optional spec."""
    rng = np.random.default_rng(seed); y = metric; n_T, n_B = int(df.is_T.sum()), int((~df.is_T).sum())
    pT, pB = df[df.is_T][y].mean(), df[~df.is_T][y].mean(); delta = pT - pB
    out = {"metric": metric, "pool_n_T": n_T, "pool_n_B": n_B, "rate_base": float(pB), "rate_T": float(pT), "observed_change_pp": float(100 * delta), "causes": {}, "warnings": []}
    masks = {k: _mask(df, s) for k, s in causes.items()}
    names = list(masks)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if (masks[a] & masks[b]).any(): out["warnings"].append(f"causes '{a}' and '{b}' overlap; shares are not additive"); 
    any_slice = np.zeros(len(df), bool)
    for m in masks.values(): any_slice |= m.values
    ctl = _mask(df, control) if control else pd.Series(~any_slice, index=df.index)
    if control and (ctl & any_slice).any(): out["warnings"].append("control group overlaps a cause slice")
    groups = {k: masks[k] for k in names}; groups["__control__"] = ctl
    cells = {g: _cells(df[m.values], y) for g, m in groups.items()}
    ok = {}
    for k in names:
        c = cells[k]
        if c["T"][0] < MIN_T or c["B"][0] < MIN_B: out["causes"][k] = {"status": "too_small_to_attribute", "n_T": c["T"][0], "n_B": c["B"][0]}
        else: ok[k] = c
    if cells["__control__"]["T"][0] < MIN_T or cells["__control__"]["B"][0] < MIN_B:
        out["warnings"].append("control group too small; contributions not computed"); ok = {}
    def contributions(cl):
        pool_n = sum(cl[g]["T"][0] for g in cl) or 1; res = {}
        cT, cB = cl["__control__"]["T"], cl["__control__"]["B"]; rc = cT[1] / max(cT[0], 1) - cB[1] / max(cB[0], 1)
        for k in ok:
            sT, sB = cl[k]["T"], cl[k]["B"]; rs = sT[1] / max(sT[0], 1) - sB[1] / max(sB[0], 1); res[k] = sT[0] / pool_n * (rs - rc)
        return res
    if ok:
        point = contributions({g: cells[g] for g in cells})
        draws = {k: [] for k in ok}; dl = []
        for _ in range(B):
            cl = {g: {p: (n, int(rng.binomial(n, k / n)) if n else 0) for p, (n, k) in v.items()} for g, v in cells.items()}
            for k, v in contributions(cl).items(): draws[k].append(v)
            t_n = sum(v["T"][0] for v in cl.values()); b_n = sum(v["B"][0] for v in cl.values())
            dl.append(sum(v["T"][1] for v in cl.values()) / t_n - sum(v["B"][1] for v in cl.values()) / b_n)
        se = np.sqrt(pT * (1 - pT) / n_T + pB * (1 - pB) / n_B)   # change must beat both a floor and sampling noise (2 se)
        material = abs(delta) >= max(MIN_CHANGE_PP / 100, 2 * se); tot = 0.0
        cT, cB = cells["__control__"]["T"], cells["__control__"]["B"]; out["control_change_pp"] = float(100 * (cT[1] / cT[0] - cB[1] / cB[0]))
        for k in ok:
            c = point[k]; d = np.array(draws[k]); sT, sB = cells[k]["T"], cells[k]["B"]
            r = {"status": "ok", "n_T": sT[0], "n_B": sB[0], "rate_base": sB[1] / sB[0], "rate_T": sT[1] / sT[0],
                 "slice_change_pp": 100 * (sT[1] / sT[0] - sB[1] / sB[0]), "contribution_pp": 100 * c, "contribution_pp_80": [100 * float(np.percentile(d, 10)), 100 * float(np.percentile(d, 90))],
                 "excess_accounts": c * n_T}
            if material:
                # share of the observed change; ratio bootstrap pairs each draw's contribution with that draw's own pool change
                sh = d / np.where(np.abs(np.array(dl)) < 1e-9, np.nan, np.array(dl)); lo, hi = np.nanpercentile(sh, [10, 90])
                r.update(share_of_change=float(c / delta), share_80=[float(lo), float(hi)]); tot += c / delta
            else: r["share_of_change"] = None
            out["causes"][k] = r
        out["unexplained_share"] = float(1 - tot) if material else None   # negative = offset by the control group
        if material and tot > 1.05: out["warnings"].append(f"attributed shares exceed 100%: the control group moved {out['control_change_pp']:+.2f}pp the opposite way and offsets part of the effect; report it as an offset, not as extra explanation")
        if not material: out["warnings"].append("observed change is within sampling noise (or below 0.3pp): shares not reported")
    if partition: ss = shift_share(df, y, partition); out["shift_share"] = {"dimension": partition, "mix_total_pp": float(ss.mix_pp.sum()), "rate_total_pp": float(ss.rate_pp.sum()),
                  "top": ss.reindex(ss.total_pp.abs().sort_values(ascending=False).index).head(6).round(4).to_dict("records")}
    return out
# ---------------- agent tool wrapper ----------------
SPEC = {"name": "attribute_change", "description": "Deterministic calculator: how much of a change in a roll-forward or cure rate is explained by named causes (slices). "
        "Use it AFTER you have a hypothesis; never estimate percentages yourself. Returns observed change, each cause's control-adjusted contribution with an 80% range, "
        "mix-vs-rate split, and the UNEXPLAINED remainder. Causes must not overlap.",
        "input_schema": {"type": "object", "required": ["month", "bucket_from", "metric", "causes"], "properties": {
            "month": {"type": "string", "description": "YYYY-MM-01, the current month"}, "bucket_from": {"type": "string", "enum": ["CURRENT", "1-30", "31-60", "61-90"]},
            "metric": {"type": "string", "enum": ["roll_forward", "cure"]}, "product_type": {"type": "string"}, "region": {"type": "string"},
            "recent_months": {"type": "integer", "description": "length of the current window in months (default 1)"}, "baseline_lag": {"type": "integer", "description": "months skipped between baseline and current window (default 0; use 3 if the shift started earlier)"},
            "causes": {"type": "object", "description": "name -> {dimension, values}; dimension e.g. agency_id, city, emi_band, had_field_visit, mob_band, ntc_flag"},
            "control": {"type": "object", "description": "optional {dimension, values}; default is the rest of the pool"}, "partition_dimension": {"type": "string", "description": "for the mix-vs-rate split, e.g. agency_id"}}}}
class AttributionTool:
    spec = SPEC
    def __init__(self, lender_id, as_of, run_id="run", g=None, audit_dir=root / "outputs/audit", id_offset=0, trace=None):
        from guarded_sql import GuardedSQL
        self.g = g or GuardedSQL(lender_id, as_of, run_id=run_id); self.run_id, self.n, self.id_offset, self.trace = run_id, 0, id_offset, trace
        audit_dir.mkdir(parents=True, exist_ok=True); self.path = audit_dir / f"{run_id}.jsonl"; self.evidence = {}
    def __call__(self, month, bucket_from, metric, causes, product_type=None, region=None, recent_months=1, baseline_lag=0, control=None, partition_dimension=None):
        import drift_profiler as dp
        try:
            for s in list(causes.values()) + ([control] if control else []):
                if s["dimension"] not in dp.CATS: return {"ok": False, "error": f"unknown dimension {s['dimension']}; use one of {dp.CATS}"}
            df = dp.pull(self.g, month, bucket_from, product_type, region, 6, baseline_lag, recent_months)
            if df.is_T.sum() == 0: return {"ok": False, "error": "no accounts in the current window for this pool"}
            res = attribute(df, metric, causes, control, partition_dimension)
        except Exception as e: return {"ok": False, "error": str(e).splitlines()[0]}
        self.n += 1; aid = f"A{self.n + self.id_offset:03d}"
        res = {"ok": True, "attribution_id": aid, **res, "args": dict(month=month, bucket_from=bucket_from, metric=metric, product_type=product_type, region=region,
               recent_months=recent_months, baseline_lag=baseline_lag, causes=causes, control=control)}
        self.evidence[aid] = res
        if self.trace:
            cz = {k: {x: v.get(x) for x in ("status", "contribution_pp", "share_of_change", "n_T")} for k, v in res["causes"].items()}
            self.trace.emit("attribution", "investigate", "code", f"{aid} {metric} {bucket_from} observed {res['observed_change_pp']:+.2f}pp", {"attribution_id": aid, "tool_run": self.run_id, "args": res["args"], "observed_change_pp": res["observed_change_pp"], "causes": cz, "warnings": res["warnings"], "result_sha": __import__("hashlib").sha1(json.dumps(res, default=str, sort_keys=True).encode()).hexdigest()[:12]})
        with open(self.path, "a") as f: f.write(json.dumps({"run_id": self.run_id, "attribution_id": aid, "ts": datetime.datetime.now().isoformat(timespec="seconds"),
              "args": dict(month=month, bucket_from=bucket_from, metric=metric, product_type=product_type, region=region, recent_months=recent_months, baseline_lag=baseline_lag, causes=causes, control=control), "result": res}, default=str) + "\n")
        return res
