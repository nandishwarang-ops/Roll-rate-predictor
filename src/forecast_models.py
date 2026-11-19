"""Section 8: baseline forecasting models. Common interface:
    forecast(model, con, origin, horizon=3, level='segment') -> DataFrame
        [lender_id, product_type, region, bucket_from, bucket_to, month_date, h, fc_rate]
Only months <= origin are used (time cutoff). Models work in logit space on each transition cell's rate, then every
(segment, bucket_from, month) row is renormalised to sum to 1.
  ets      : damped-trend exponential smoothing per series (no exogenous inputs)
  sarimax  : ARIMA(1,0,0)+const with exogenous calendar regressors (festival share, fiscal year-end), no seasonal AR
  gbm      : ONE pooled gradient-boosting model across all series (sklearn HistGradientBoosting; LightGBM needs libomp
             which is not installed on this Mac) with direct multi-step targets and calendar features
  snaive / naive : reference baselines
"""
import duckdb, numpy as np, pandas as pd, pathlib, warnings, sys
from sklearn.ensemble import HistGradientBoostingRegressor
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.statespace.sarimax import SARIMAX
warnings.filterwarnings("ignore")
root = pathlib.Path(__file__).resolve().parent.parent
EPS = 1e-4
KEYS = ["lender_id", "product_type", "region", "bucket_from", "bucket_to"]
logit = lambda p: np.log(np.clip(p, EPS, 1 - EPS) / (1 - np.clip(p, EPS, 1 - EPS)))
expit = lambda z: 1 / (1 + np.exp(-z))
def month_range(start, end):
    return pd.date_range(start, end, freq="MS")
# ---------------- calendar exogenous inputs ----------------
def calendar_exog(con, regions, months, origin):
    """festival_share and fiscal flag per (region, month). Only events known_in_advance and announced <= origin."""
    ev = con.sql(f"select event_category, event_start_date, event_end_date, region from main.event_calendar where known_in_advance and announced_date <= date '{origin}'").df()
    out = []
    for r in regions:
        for m in months:
            ms, me = m, m + pd.offsets.MonthEnd(0); days = (me - ms).days + 1
            fest = fiscal = 0.0
            for e in ev.itertuples():
                if e.region not in (None, r) and not (pd.isna(e.region)): continue
                s, en = pd.Timestamp(e.event_start_date), pd.Timestamp(e.event_end_date) if pd.notna(e.event_end_date) else pd.Timestamp("2100-01-01")
                ov = (min(me, en) - max(ms, s)).days + 1
                if ov > 0:
                    if e.event_category == "FESTIVAL": fest += ov / days
                    if e.event_category == "FISCAL_PERIOD": fiscal = 1.0
            out.append((r, m, min(fest, 1.0), fiscal))
    return pd.DataFrame(out, columns=["region", "month_date", "festival", "fiscal"])
# ---------------- data ----------------
def history(con, origin, level="segment"):
    df = con.sql(f"select lender_id, product_type, region, month_date, bucket_from, bucket_to, rate_count, opening_accounts "
                 f"from mart.transitions_{level} where month_date <= date '{origin}'").df()
    df["month_date"] = pd.to_datetime(df["month_date"])
    return df
def _series_frames(df):
    piv = df.pivot_table(index="month_date", columns=KEYS, values="rate_count", aggfunc="sum").sort_index()
    return piv
def _renorm(fc):
    s = fc.groupby(["lender_id", "product_type", "region", "bucket_from", "month_date"])["fc_rate"].transform("sum")
    fc["fc_rate"] = np.where(s > 0, fc["fc_rate"] / s, 0.0)
    return fc
def _assemble(rows):
    fc = pd.DataFrame(rows, columns=KEYS + ["month_date", "h", "fc_rate"])
    return _renorm(fc)
# ---------------- per-series models ----------------
def _flat_or_short(y, horizon):
    return None if (y > EPS).sum() >= 12 else np.repeat(y[-6:].mean(), horizon)  # sparse series: recent mean (in rate space)
def forecast_ets(piv, horizon, **_):
    rows = []
    for col in piv.columns:
        y = piv[col].fillna(0).values
        f = _flat_or_short(y, horizon)
        if f is None:
            z = logit(y)
            try: f = expit(ExponentialSmoothing(z, trend="add", damped_trend=True).fit().forecast(horizon))
            except Exception: f = np.repeat(expit(z[-3:].mean()), horizon)
        rows.append((col, f))
    return rows
def forecast_sarimax(piv, horizon, exog=None, **_):
    rows = []
    idx = piv.index; fut = pd.date_range(idx[-1] + pd.offsets.MonthBegin(1), periods=horizon, freq="MS")
    for col in piv.columns:
        y = piv[col].fillna(0).values
        f = _flat_or_short(y, horizon)
        if f is None:
            region = col[2]; ex = exog[exog.region == region].set_index("month_date")[["festival", "fiscal"]]
            z = logit(y)
            try:
                r = SARIMAX(z, exog=ex.loc[idx].values, order=(1, 0, 0), trend="c").fit(disp=False, maxiter=100)
                f = expit(r.forecast(horizon, exog=ex.loc[fut].values))
            except Exception: f = np.repeat(expit(z[-3:].mean()), horizon)
        rows.append((col, f))
    return rows
def forecast_snaive(piv, horizon, **_):
    return [(c, np.array([piv[c].iloc[-12 + h] if len(piv) >= 12 else piv[c].iloc[-1] for h in range(horizon)])) for c in piv.columns]
def forecast_naive(piv, horizon, **_):
    return [(c, np.repeat(piv[c].iloc[-1], horizon)) for c in piv.columns]
# ---------------- pooled GBM ----------------
def forecast_gbm(piv, horizon, exog=None, hist=None, **_):
    cols = list(piv.columns); Z = logit(piv.fillna(0).values)              # T x S
    T, S = Z.shape
    ex = exog.set_index(["region", "month_date"])
    op = hist.pivot_table(index="month_date", columns=KEYS, values="opening_accounts", aggfunc="max").reindex(columns=cols).fillna(1).values
    cat = {k: pd.Series([c[i] for c in cols]).astype("category").cat.codes.values for i, k in enumerate(["lender", "product", "region", "bfrom", "bto"])}
    fut = pd.date_range(piv.index[-1] + pd.offsets.MonthBegin(1), periods=horizon, freq="MS")
    def feats(t, h, target_month):                    # features known at origin index t for target t+h
        z = Z[t]; l2 = Z[t - 1]; l3 = Z[t - 2]; m6 = Z[max(0, t - 5):t + 1].mean(0); s6 = Z[max(0, t - 5):t + 1].std(0)
        e = np.array([ex.loc[(c[2], target_month)][["festival", "fiscal"]].values if (c[2], target_month) in ex.index else [0, 0] for c in cols])
        return np.column_stack([z, l2, l3, m6, s6, z - l2, np.log(op[t]), e, cat["lender"], cat["product"], cat["region"], cat["bfrom"], cat["bto"], np.full(S, h)])
    preds = np.zeros((horizon, S)); idx = list(piv.index)
    for h in range(1, horizon + 1):
        X, Y = [], []
        for t in range(3, T - h):
            X.append(feats(t, h, idx[t + h])); Y.append(Z[t + h])
        X = np.vstack(X); Y = np.concatenate(Y)
        mdl = HistGradientBoostingRegressor(max_iter=250, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=40, l2_regularization=1.0,
                                            categorical_features=[False]*9 + [True]*5 + [False], random_state=0).fit(X, Y)
        preds[h - 1] = expit(mdl.predict(feats(T - 1, h, fut[h - 1])))
    return [(c, preds[:, i]) for i, c in enumerate(cols)]
MODELS = {"ets": forecast_ets, "sarimax": forecast_sarimax, "gbm": forecast_gbm, "snaive": forecast_snaive, "naive": forecast_naive}
def forecast(model, con, origin, horizon=3, level="segment"):
    hist = history(con, origin, level); piv = _series_frames(hist)
    regions = sorted(hist.region.unique()); fut = month_range(piv.index[-1] + pd.offsets.MonthBegin(1), piv.index[-1] + pd.offsets.MonthBegin(horizon))
    exog = calendar_exog(con, regions, list(piv.index) + list(fut), origin)
    res = MODELS[model](piv, horizon, exog=exog, hist=hist)
    rows = [tuple(c) + (fut[h], h + 1, float(v[h])) for c, v in res for h in range(horizon)]
    return _assemble(rows)
# ---------------- scoring ----------------
def score(con, fc, min_open=30):
    hist = con.sql("select lender_id, product_type, region, month_date, bucket_from, bucket_to, rate_count, opening_accounts from mart.transitions_segment").df()
    hist["month_date"] = pd.to_datetime(hist["month_date"])
    m = fc.merge(hist, on=KEYS[:3] + ["month_date", "bucket_from", "bucket_to"])
    k = m[(m.rate_count > 0) & (m.opening_accounts >= min_open)]
    mape = (abs(k.fc_rate - k.rate_count) / k.rate_count).mean()
    wape = (abs(m.fc_rate - m.rate_count) * m.opening_accounts).sum() / (m.rate_count * m.opening_accounts).sum()
    return len(k), mape, wape
if __name__ == "__main__":
    import time
    con = duckdb.connect(str(root / "rollrate.duckdb"), read_only=True)
    origin = sys.argv[1] if len(sys.argv) > 1 else "2025-06-01"
    print(f"origin {origin}, horizon 3 (single-origin sanity check; full bake-off is section 9)")
    print(f"{'model':8}{'cells':>8}{'MAPE':>9}{'WAPE':>9}{'secs':>7}")
    for m in ["snaive", "naive", "ets", "sarimax", "gbm"]:
        t = time.time(); fc = forecast(m, con, origin); n, mape, wape = score(con, fc)
        print(f"{m:8}{n:>8,}{mape:>9.1%}{wape:>9.1%}{time.time()-t:>7.1f}")
