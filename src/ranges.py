"""Section 21: range calibration + simulation-based aggregate ranges.
Honest ranges = (a) model error estimated from the rolling-origin backtest, (b) sampling noise (loans are discrete), (c) propagation through the 3-month chain,
(d) errors that are SHARED across segments of a lender (so a lender-wide miss widens the totals instead of cancelling), (e) scenario uncertainty (blip vs lasting).
Method: the error of a forecast row-class (forward / stay / cure / exit rate of a from-bucket) is lognormal with a sigma fitted per (bucket, class, horizon):
    sigma^2 = E[e^2] - sampling variance,  kappa = share that is lender-wide,  phi = month-to-month persistence of the error.
Each simulation draw perturbs the matrices, redistributes every row (multinomial), chains 3 months and records every aggregate - so lender = sum of its segments
in every draw and all roll-ups reconcile. A calibration multiplier lambda per horizon is then chosen so that out-of-origin coverage of the 80% range is ~80%."""
import numpy as np, pandas as pd, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import chaining as C
root = pathlib.Path(__file__).resolve().parent.parent
CLASSES = ["forward", "stay", "cure", "exit"]
def cls(b, t): return 3 if t >= 5 else (1 if t == b else (0 if t > b else 2))
SEV = {k: i for i, k in enumerate(C.FROM)}
# ------------------------------------------------------------------ residuals + parameters
def residual_table(con, min_expected=5):
    fc = con.sql("select lender_id, product_type, region, bucket_from, bucket_to, month_date, h, origin, fc_rate from mart.bakeoff_forecasts where model='ensemble'").df()
    act = con.sql("select lender_id, product_type, region, bucket_from, bucket_to, month_date, account_count, opening_accounts from mart.transitions_segment").df()
    d = fc.merge(act, on=["lender_id", "product_type", "region", "bucket_from", "bucket_to", "month_date"])
    d["cls"] = [CLASSES[cls(SEV[b], C.TO.index(t))] for b, t in zip(d.bucket_from, d.bucket_to)]
    g = d.groupby(["lender_id", "product_type", "region", "bucket_from", "cls", "month_date", "h", "origin"], as_index=False).agg(p=("fc_rate", "sum"), k=("account_count", "sum"), n=("opening_accounts", "max"))
    g = g[g.n * g.p >= min_expected].copy(); g["e"] = np.log((g.k + 0.5) / (g.n * g.p + 0.5)); g["s2"] = (1 - g.p.clip(upper=0.999)) / (g.n * g.p); g["origin"] = pd.to_datetime(g.origin); return g
def fit_params(res, exclude_origin=None):
    r = res if exclude_origin is None else res[res.origin != pd.Timestamp(exclude_origin)]; P = {"sigma": {}, "kappa": {}, "phi": 0.9}
    for (b, c, h), g in r.groupby(["bucket_from", "cls", "h"]): P["sigma"][(b, c, h)] = float(np.sqrt(max((g.e ** 2).mean() - g.s2.mean(), 1e-4)))
    for (b, c), g in r.groupby(["bucket_from", "cls"]):
        grp = g.groupby(["lender_id", "origin", "h"]).agg(m=("e", "mean"), nseg=("e", "size"), s2=("s2", "mean")); common = np.clip(grp.m ** 2 - grp.s2 / grp.nseg, 0, None).mean()
        P["kappa"][(b, c)] = float(np.clip(common / max((g.e ** 2).mean() - g.s2.mean(), 1e-4), 0.0, 0.85))
    pv = r.pivot_table(index=["lender_id", "product_type", "region", "bucket_from", "cls", "origin"], columns="h", values="e"); cs = [pv[a].corr(pv[b]) for a, b in [(1, 2), (2, 3)] if a in pv and b in pv]
    P["phi_fitted"] = float(np.clip(np.nanmean(cs), 0.0, 0.9)) if cs else 0.4; return P      # phi itself stays at the calibrated 0.9 (see ranges_backtest.py)
def sigma(P, b, c, h): return P["sigma"].get((b, c, h), np.mean([v for (bb, cc, hh), v in P["sigma"].items() if bb == b and cc == c] or [0.1]))
# ------------------------------------------------------------------ simulation
def simulate(state, avg_pos, M_list, inflow, P, N=2000, lam=(1.0, 1.0, 1.0), seed=0):
    """M_list = [(M [H,12,5,7], weight), ...] scenario mixture (one entry = no scenario uncertainty). -> dict of arrays."""
    rng = np.random.default_rng(seed); H = M_list[0][0].shape[0]; w = np.array([x[1] for x in M_list], float); w /= w.sum()
    pick = rng.choice(len(M_list), size=N, p=w); Mall = np.stack([m for m, _ in M_list])[pick]                    # [N,H,12,5,7]
    clsmap = np.array([[cls(b, t) for t in range(7)] for b in range(5)])                                           # [5,7]
    phi = P["phi"]; Zc = np.zeros((N, 5, 4, H)); Zi = np.zeros((N, 12, 5, 4, H))
    for h in range(H):
        zc, zi = rng.standard_normal((N, 5, 4)), rng.standard_normal((N, 12, 5, 4))
        Zc[..., h] = zc if h == 0 else phi * Zc[..., h - 1] + np.sqrt(1 - phi ** 2) * zc; Zi[..., h] = zi if h == 0 else phi * Zi[..., h - 1] + np.sqrt(1 - phi ** 2) * zi
    sig = np.array([[[sigma(P, C.FROM[b], CLASSES[c], h + 1) * lam[h] for h in range(H)] for c in range(4)] for b in range(5)])     # [5,4,H]
    kap = np.array([[P["kappa"].get((C.FROM[b], CLASSES[c]), 0.3) for c in range(4)] for b in range(5)])                           # [5,4]
    eps = sig[None, None] * (np.sqrt(kap)[None, None, :, :, None] * Zc[:, None] + np.sqrt(1 - kap)[None, None, :, :, None] * Zi)       # [N,12,5,4,H]
    stock = np.zeros((N, H + 1, 12, 5)); stock[:, 0] = state; flows = np.zeros((N, H, 12, 5, 7))
    for h in range(H):
        e_cell = np.take_along_axis(eps[..., h], np.broadcast_to(clsmap, (N, 12, 5, 7)), axis=-1)                    # [N,12,5,7]: error of each cell's class
        Pm = Mall[:, h] * np.exp(e_cell); Pm /= Pm.sum(-1, keepdims=True)
        n_rem = stock[:, h].astype(np.int64); rem = np.ones_like(n_rem, float); x = np.zeros((N, 12, 5, 7))
        for k in range(6):                                                                                          # multinomial by sequential binomials
            pk = np.clip(Pm[..., k] / np.clip(rem, 1e-12, None), 0, 1); xk = rng.binomial(n_rem, pk); x[..., k] = xk; n_rem = n_rem - xk; rem = rem - Pm[..., k]
        x[..., 6] = n_rem; flows[:, h] = x; stock[:, h + 1] = x[..., :5].sum(2); stock[:, h + 1, :, 0] += rng.poisson(inflow, size=(N, 12))
    return dict(stock=stock, flows=flows, avg_pos=avg_pos)
def aggregates(sim, seg_mask=None):
    """per-draw aggregates [N,H]. seg_mask selects segments (product/region roll-ups); default all."""
    s, f, ap = sim["stock"], sim["flows"], sim["avg_pos"]; m = np.ones(12, bool) if seg_mask is None else seg_mask
    npa = s[:, 1:, m, 4].sum(-1); adds = f[:, :, m][..., :4, 4].sum(-1).sum(-1); pos = s[:, 1:, m] * ap[m]
    return {"npa_accounts": npa, "npa_additions": adds, "npa_principal": pos[..., 4].sum(-1), "stage2_principal": pos[..., 2:4].sum((-1, -2)), "stage3_principal": pos[..., 4].sum(-1),
            "live_accounts": s[:, 1:, m].sum((-1, -2)), "npa_ratio": npa / s[:, 1:, m].sum((-1, -2))}
def summarize(sim, groups=None, q=(0.1, 0.5, 0.9)):
    """P10/P50/P90 for lender total and roll-ups. groups: {'name': seg_mask}."""
    segs = C.segments(); gm = {"lender": None, **{f"product={p}": np.array([s[0] == p for s in segs]) for p in sorted({s[0] for s in segs})}, **{f"region={r}": np.array([s[1] == r for s in segs]) for r in sorted({s[1] for s in segs})}, **(groups or {})}
    rows = []
    for name, mask in gm.items():
        for k, a in aggregates(sim, mask).items():
            for h in range(a.shape[1]): rows.append(dict(group=name, metric=k, h=h + 1, **{f"p{int(x*100)}": float(np.quantile(a[:, h], x)) for x in q}))
    return pd.DataFrame(rows)
# ------------------------------------------------------------------ production entry point
def ranged_outlook(q, lender, origin, variants, con, N=2000, seed=0):
    """variants = [(forecast_df, weight), ...] (e.g. section 19's 'lasting' and 'blip' with the classifier's weights; one entry if no scenario uncertainty).
    -> (summary DataFrame of P10/P50/P90 for lender and roll-ups, sim). Uses the calibrated lambda/phi from src/range_calibration.json."""
    import json
    cal = json.loads((root / "src/range_calibration.json").read_text()); P = fit_params(residual_table(con)); P["phi"] = cal["phi"]
    state, ap = C.get_state(q, lender, origin); infl, _ = C.get_inflow(q, lender, origin)
    sim = simulate(state, ap, [(C.matrices(fc, lender), w) for fc, w in variants], infl, P, N=N, lam=tuple(cal["lambda"]), seed=seed)
    s = summarize(sim); s.insert(0, "lender_id", lender); s.insert(1, "origin", str(origin)[:7]); return s, sim
