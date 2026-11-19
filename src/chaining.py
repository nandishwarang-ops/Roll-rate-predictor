"""Section 20: multi-month chaining -> the 3-month outlook in ACCOUNTS and PRINCIPAL, not just rates.
A loan cannot go from on-time to 90+ in one month, so how many loans become NPA in 3 months must be built step by step:
    stock[t+1] = stock[t] x P[t+1]  (+ new disbursements entering CURRENT)
where P[t+1] is the forecast transition matrix for month t+1 (section 8/19). Tracked per segment, then rolled up:
live stock per bucket, NPA (90+) stock, NPA additions (loans newly entering 90+), cures, closures, write-offs and Ind-AS 109 stage stock.
chain() is a pure numpy function so section 21 can run it thousands of times on sampled matrices.
Assumptions (stated in the pack): new disbursals = mean of the last 3 months; principal per account in a bucket stays at its origin-month average."""
import numpy as np, pandas as pd, pathlib, sys
root = pathlib.Path(__file__).resolve().parent.parent
FROM = ["CURRENT", "1-30", "31-60", "61-90", "90+"]; TO = FROM + ["CLOSED", "WRITTEN_OFF"]; STAGE = {"CURRENT": 1, "1-30": 1, "31-60": 2, "61-90": 2, "90+": 3}
SEGKEYS = ["product_type", "region"]
def segments(): return [(p, r) for p in ["BUSINESS_LOAN", "PERSONAL_LOAN", "TWO_WHEELER"] for r in ["EAST", "NORTH", "SOUTH", "WEST"]]
# ------------------------------------------------------------ inputs (state, inflow) from D1 - same SQL for sandbox or plain connection
def get_state(q, lender, origin):
    d = q(f"select product_type, region, bucket_curr, count(*) n, sum(pos_closing) pos from d1_account_monthly where lender_id='{lender}' and month_date=date '{origin}' "
          f"and bucket_curr in ('CURRENT','1-30','31-60','61-90','90+') group by all")
    S = np.zeros((12, 5)); P = np.zeros((12, 5)); idx = {s: i for i, s in enumerate(segments())}
    for r in d.itertuples(): S[idx[(r.product_type, r.region)], FROM.index(r.bucket_curr)] = r.n; P[idx[(r.product_type, r.region)], FROM.index(r.bucket_curr)] = r.pos
    return S, np.divide(P, S, out=np.zeros_like(P), where=S > 0)                   # accounts, avg principal per account
def get_inflow(q, lender, origin, months=3):
    d = q(f"select product_type, region, month_date, count(*) n, avg(pos_closing) pos from d1_account_monthly where lender_id='{lender}' and bucket_prev='NEW' "
          f"and month_date > date '{origin}' - interval {months} month and month_date <= date '{origin}' group by all")
    n = np.zeros(12); pos = np.zeros(12); idx = {s: i for i, s in enumerate(segments())}
    for (p, r), g in d.groupby(SEGKEYS): n[idx[(p, r)]] = g.n.sum() / months; pos[idx[(p, r)]] = np.average(g.pos, weights=g.n)
    return n, pos
def matrices(fc, lender, horizon=3, rate_col="fc_rate"):
    """fc long frame (KEYS, month_date, h, rate) -> array [H, 12, 5, 7]; missing cells = 0, rows renormalised to 1; rows with no data stay put."""
    M = np.zeros((horizon, 12, 5, 7)); idx = {s: i for i, s in enumerate(segments())}; f = fc[fc.lender_id == lender]
    for h in range(1, horizon + 1):
        g = f[f.h == h] if "h" in f.columns else f
        for r in g.itertuples():
            M[h - 1, idx[(r.product_type, r.region)], FROM.index(r.bucket_from), TO.index(r.bucket_to)] = getattr(r, rate_col)
        for s in range(12):
            for b in range(5):
                tot = M[h - 1, s, b].sum()
                if tot > 0: M[h - 1, s, b] /= tot
                else: M[h - 1, s, b, b] = 1.0
    return M
# ------------------------------------------------------------ the chain
def chain(state, M, inflow):
    """state [12,5] accounts; M [H,12,5,7]; inflow [12] -> stock [H+1,12,5], flows [H,12,5,7] (accounts moving from-bucket -> to-state)."""
    H = M.shape[0]; stock = np.zeros((H + 1, 12, 5)); flows = np.zeros((H, 12, 5, 7)); stock[0] = state
    for h in range(H):
        flows[h] = stock[h][:, :, None] * M[h]                                     # [12,5,7]
        stock[h + 1] = flows[h][:, :, :5].sum(axis=1); stock[h + 1][:, 0] += inflow     # new loans enter CURRENT after the month's transitions
    return stock, flows
def outlook(stock, flows, avg_pos, inflow_pos=None):
    """roll-ups per forecast month: accounts and principal by bucket / Ind-AS stage, NPA stock and additions, cures, closures, write-offs."""
    H = flows.shape[0]; rows = []
    for h in range(1, H + 1):
        st = stock[h]; fl = flows[h - 1]; npa = st[:, 4].sum(); live = st.sum()
        add = fl[:, :4, 4].sum()                                                     # loans newly rolling into 90+
        cures = sum(fl[:, b, c].sum() for b in range(1, 5) for c in range(0, b)); wo = fl[:, 4, 6].sum(); cl = fl[:, :, 5].sum()
        pos = st * avg_pos; add_pos = (fl[:, :4, 4] * avg_pos[:, :4]).sum()
        rows.append(dict(h=h, accounts_live=live, npa_accounts=npa, npa_ratio=npa / live, npa_additions=add, npa_addition_rate=add / max(stock[h - 1][:, :4].sum(), 1), cures=cures, closures=cl, write_offs=wo,
                         **{f"{b}_accounts": st[:, i].sum() for i, b in enumerate(FROM)}, principal_live=pos.sum(), npa_principal=pos[:, 4].sum(), npa_additions_principal=add_pos,
                         stage1_principal=pos[:, :2].sum(), stage2_principal=pos[:, 2:4].sum(), stage3_principal=pos[:, 4].sum()))
    return pd.DataFrame(rows)
def run(q, lender, origin, fc, horizon=3, rate_col="fc_rate"):
    state, avg_pos = get_state(q, lender, origin); inflow, _ = get_inflow(q, lender, origin); M = matrices(fc, lender, horizon, rate_col)
    stock, flows = chain(state, M, inflow); out = outlook(stock, flows, avg_pos); out.insert(0, "lender_id", lender); out.insert(1, "origin", str(origin)[:7]); return out, (stock, flows)
