"""Section 23: chart generation for the review pack (static PNG for PDF/Markdown) following the dataviz method:
fixed-order categorical hues (slot 1 blue = actuals, slot 2 orange = adjusted forecast, neutral gray = unadjusted baseline), 2px lines, >=8px end dots with a surface ring,
hairline recessive grid, legend for >=2 series plus selective direct labels, text in text tokens never the series colour, one y-axis, takeaway titles.
Every chart also writes a CSV (the 'table view') and an alt-text file, and every number printed on a chart is computed from that table - nothing is typed in.
The palette values are the documented, pre-validated slot 1/2 (adjacent-pair CVD dE 9.1, normal-vision dE 19.6). The runnable validator needs node, which is not installed here."""
import pathlib, json
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter
root = pathlib.Path(__file__).resolve().parent.parent
INK, INK2, INK3, GRID, SURF = "#0b0b0b", "#52514e", "#82817c", "#e6e5e1", "#fcfcfb"
BLUE, ORANGE, GRAY = "#2a78d6", "#eb6834", "#8a8984"
LW = 1.6          # ~2px at 96 dpi
def _style(ax):
    ax.set_facecolor(SURF); [ax.spines[s].set_visible(False) for s in ("top", "right", "left")]; ax.spines["bottom"].set_color(GRID)
    ax.grid(axis="y", color=GRID, linewidth=0.8); ax.set_axisbelow(True); ax.tick_params(colors=INK2, labelsize=8.5, length=0)
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3)); ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
def _fig(w=8.4, h=4.3):
    fig, ax = plt.subplots(figsize=(w, h), dpi=200); fig.patch.set_facecolor(SURF); _style(ax); return fig, ax
def _dot(ax, x, y, color):
    ax.plot([x], [y], "o", ms=6.5, color=color, mec=SURF, mew=1.6, zorder=6)
def _title(fig, title, sub=None):
    import textwrap; lines = textwrap.wrap(title, 78)[:2]; fig.text(0.015, 0.975, "\n".join(lines), fontsize=11.5, fontweight="semibold", color=INK, ha="left", va="top", linespacing=1.25)
    if sub: fig.text(0.015, 0.975 - 0.075 * len(lines) - 0.02, sub, fontsize=8.5, color=INK2, ha="left", va="top")
def _legend(ax, handles):
    ax.legend(handles=handles, loc="upper center", frameon=False, fontsize=8.5, labelcolor=INK2, ncol=len(handles), handlelength=1.6, bbox_to_anchor=(0.5, -0.09))
def _save(fig, ax, path, table, alt):
    path = pathlib.Path(path); path.parent.mkdir(parents=True, exist_ok=True); fig.subplots_adjust(left=0.075, right=0.86, top=0.77, bottom=0.17)
    fig.savefig(path, facecolor=SURF); plt.close(fig); table.to_csv(path.with_suffix(".csv"), index=False); path.with_suffix(".alt.txt").write_text(alt); return str(path)
def _events(ax, events, xmin, xmax, ymax):
    shown = []
    for d, t in sorted(((pd.Timestamp(d), t) for d, t in events if xmin <= pd.Timestamp(d) <= xmax), key=lambda x: x[0]):
        if not shown or (d - shown[-1][0]).days >= 75: shown.append((d, t))
    shown = shown[:3]
    for i, (d, t) in enumerate(shown):
        ax.axvline(d, color=INK3, linewidth=0.8, linestyle=(0, (2, 3)), zorder=1); ax.text(d, ymax, " " + t[:26], rotation=90, fontsize=7, color=INK2, va="top", ha="right", zorder=2)
    return shown
pct = FuncFormatter(lambda v, _: f"{v:.0f}%")
# ------------------------------------------------------------------ 1. rate with forecast, baseline and range band
def rate_forecast(hist, baseline, adjusted, band, path, node, metric_label, events=(), origin=None):
    """hist: Series (month->rate fraction); baseline/adjusted: Series for forecast months; band: DataFrame[p10,p90] indexed by forecast month. Rates in 0-1."""
    fig, ax = _fig(); h = 100 * hist; b = 100 * baseline; a = 100 * adjusted; lo, hi = 100 * band.p10, 100 * band.p90
    ax.plot(h.index, h.values, color=BLUE, lw=LW, solid_capstyle="round", zorder=4); anchor = h.index[-1]
    ax.fill_between(a.index, lo.values, hi.values, color=ORANGE, alpha=0.16, linewidth=0, zorder=2)
    ax.plot([anchor] + list(b.index), [h.iloc[-1]] + list(b.values), color=GRAY, lw=LW, linestyle=(0, (4, 3)), zorder=3)
    ax.plot([anchor] + list(a.index), [h.iloc[-1]] + list(a.values), color=ORANGE, lw=LW, zorder=5)
    _dot(ax, h.index[-1], h.iloc[-1], BLUE); _dot(ax, a.index[-1], a.iloc[-1], ORANGE); ax.axvline(anchor, color=GRID, lw=1, zorder=0)
    ymin, ymax = min(h.min(), lo.min(), b.min()), max(h.max(), hi.max(), b.max()); pad = (ymax - ymin) * 0.12; ax.set_ylim(ymin - pad, ymax + pad * 1.8)
    ax.set_xlim(h.index[0] - pd.Timedelta(days=10), a.index[-1] + pd.Timedelta(days=95)); ax.yaxis.set_major_formatter(pct)
    sh = _events(ax, events, h.index[0], a.index[-1], ymax + pad * 1.7)
    ax.annotate(f"Adjusted {a.iloc[-1]:.1f}%", (a.index[-1], a.iloc[-1]), xytext=(8, 0), textcoords="offset points", fontsize=8.5, color=INK, va="center", fontweight="semibold")
    ax.annotate(f"Unadjusted {b.iloc[-1]:.1f}%", (b.index[-1], b.iloc[-1]), xytext=(8, -14 if b.iloc[-1] < a.iloc[-1] else 14), textcoords="offset points", fontsize=8.5, color=INK2, va="center")
    from matplotlib.lines import Line2D; from matplotlib.patches import Patch
    _legend(ax, [Line2D([0], [0], color=BLUE, lw=LW, label="Actual"), Line2D([0], [0], color=GRAY, lw=LW, ls=(0, (4, 3)), label="Unadjusted forecast"), Line2D([0], [0], color=ORANGE, lw=LW, label="Adjusted forecast"), Patch(color=ORANGE, alpha=0.16, label="80% range")])
    last = a.index[-1]; t = f"{node}: {metric_label} forecast {a.iloc[-1]:.1f}% in {last:%b %Y} (80% range {lo.iloc[-1]:.1f}-{hi.iloc[-1]:.1f}%)"
    _title(fig, t, f"{metric_label} by month; forecast from {anchor:%b %Y}" + (f"; dotted lines mark known events" if sh else ""))
    table = pd.concat([pd.DataFrame({"month": h.index, "series": "actual", "value_pct": h.values}), pd.DataFrame({"month": b.index, "series": "unadjusted", "value_pct": b.values}),
                       pd.DataFrame({"month": a.index, "series": "adjusted", "value_pct": a.values}), pd.DataFrame({"month": lo.index, "series": "p10", "value_pct": lo.values}), pd.DataFrame({"month": hi.index, "series": "p90", "value_pct": hi.values})])
    return _save(fig, ax, path, table, t + ". Lines: actual, unadjusted forecast, adjusted forecast with 80% range band. Full values in the adjacent CSV.")
# ------------------------------------------------------------------ 2. NPA stock outlook with scenarios
def npa_outlook(hist, weighted, band, path, node, scenarios=None):
    """hist: Series (month->NPA accounts, actual); weighted: Series forecast; band DataFrame[p10,p90]; scenarios: {name: Series} (e.g. blip, lasting)."""
    fig, ax = _fig(); ax.plot(hist.index, hist.values, color=BLUE, lw=LW, zorder=4); anchor = hist.index[-1]
    ax.fill_between(weighted.index, band.p10.values, band.p90.values, color=ORANGE, alpha=0.16, linewidth=0, zorder=2)
    for name, s in (scenarios or {}).items(): ax.plot([anchor] + list(s.index), [hist.iloc[-1]] + list(s.values), color=GRAY, lw=1.2, ls=(0, (4, 3)) if name == "blip" else (0, (1, 2)), zorder=3)
    ax.plot([anchor] + list(weighted.index), [hist.iloc[-1]] + list(weighted.values), color=ORANGE, lw=LW, zorder=5); _dot(ax, hist.index[-1], hist.iloc[-1], BLUE); _dot(ax, weighted.index[-1], weighted.iloc[-1], ORANGE)
    ax.axvline(anchor, color=GRID, lw=1); lo = min(hist.min(), band.p10.min()); hi = max(hist.max(), band.p90.max()); pad = (hi - lo) * 0.15; ax.set_ylim(lo - pad, hi + pad)
    ax.set_xlim(hist.index[0] - pd.Timedelta(days=10), weighted.index[-1] + pd.Timedelta(days=95)); ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.annotate(f"{weighted.iloc[-1]:,.0f}", (weighted.index[-1], weighted.iloc[-1]), xytext=(8, 0), textcoords="offset points", fontsize=8.5, color=INK, va="center", fontweight="semibold")
    from matplotlib.lines import Line2D; from matplotlib.patches import Patch
    hd = [Line2D([0], [0], color=BLUE, lw=LW, label="Actual"), Line2D([0], [0], color=ORANGE, lw=LW, label="Forecast (scenario-weighted)"), Patch(color=ORANGE, alpha=0.16, label="80% range")]
    if scenarios: hd += [Line2D([0], [0], color=GRAY, lw=1.2, ls=(0, (4, 3)), label="Blip case"), Line2D([0], [0], color=GRAY, lw=1.2, ls=(0, (1, 2)), label="Lasting case")]
    _legend(ax, hd); chg = weighted.iloc[-1] - hist.iloc[-1]; t = f"{node}: NPA accounts forecast {weighted.iloc[-1]:,.0f} by {weighted.index[-1]:%b %Y} ({chg:+,.0f} vs {anchor:%b %Y}; 80% range {band.p10.iloc[-1]:,.0f}-{band.p90.iloc[-1]:,.0f})"
    _title(fig, t, "Accounts more than 90 days past due (Ind-AS Stage 3)")
    rows = [pd.DataFrame({"month": hist.index, "series": "actual", "accounts": hist.values}), pd.DataFrame({"month": weighted.index, "series": "forecast", "accounts": weighted.values}), pd.DataFrame({"month": band.index, "series": "p10", "accounts": band.p10.values}), pd.DataFrame({"month": band.index, "series": "p90", "accounts": band.p90.values})]
    rows += [pd.DataFrame({"month": s.index, "series": n, "accounts": s.values}) for n, s in (scenarios or {}).items()]
    return _save(fig, ax, path, pd.concat(rows), t + ". Actual line, scenario-weighted forecast with 80% range, blip and lasting cases. Full values in the adjacent CSV.")
# ------------------------------------------------------------------ 3. what moved: segment contributions to a lender-level change
def what_moved(ss, total_pp, path, node, metric_label, month, top=8):
    """ss: DataFrame indexed by segment with total_pp (shift-share). Horizontal bars from a zero baseline; orange = pushes the rate up, blue = down."""
    d = ss.head(top).iloc[::-1]; fig, ax = plt.subplots(figsize=(8.4, 4.3), dpi=200); fig.patch.set_facecolor(SURF); ax.set_facecolor(SURF)
    [ax.spines[s].set_visible(False) for s in ("top", "right", "left", "bottom")]; ax.tick_params(colors=INK2, labelsize=8.5, length=0); ax.grid(axis="x", color=GRID, lw=0.8); ax.set_axisbelow(True)
    cols = [ORANGE if v > 0 else BLUE for v in d.total_pp]; ax.barh([s.replace("|", " / ").replace("_", " ").title() for s in d.index], d.total_pp.values, color=cols, height=0.55, zorder=3); ax.axvline(0, color=INK3, lw=1, zorder=4)
    span = max(abs(d.total_pp).max(), 1e-9)
    for i, v in enumerate(d.total_pp.values): ax.text(v + (0.02 * span if v >= 0 else -0.02 * span), i, f"{v:+.2f}", va="center", ha="left" if v >= 0 else "right", fontsize=8.5, color=INK)
    ax.set_xlim(-span * 1.25, span * 1.25); ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:+.1f}"))
    from matplotlib.patches import Patch; ax.legend(handles=[Patch(color=ORANGE, label="Raised the rate"), Patch(color=BLUE, label="Lowered the rate")], loc="lower right", frameon=False, fontsize=8.5, labelcolor=INK2)
    t = f"{node}: {metric_label} {'rose' if total_pp > 0 else 'fell'} {abs(total_pp):.2f} points in {month:%b %Y}; {d.index[-1].replace('|', ' / ').replace('_', ' ').title()} moved it most"
    _title(fig, t, "Contribution of each segment to the lender-level change, percentage points (mix + rate effects)"); fig.subplots_adjust(left=0.27, right=0.95, top=0.77, bottom=0.10)
    p = pathlib.Path(path); p.parent.mkdir(parents=True, exist_ok=True); fig.savefig(p, facecolor=SURF); plt.close(fig)
    tab = ss.head(top).reset_index().rename(columns={"index": "segment"}); tab.to_csv(p.with_suffix(".csv"), index=False); p.with_suffix(".alt.txt").write_text(t + ". Horizontal bars of per-segment contribution in percentage points. Values in the adjacent CSV."); return str(p)
# ------------------------------------------------------------------ 4. lender overview: four buckets as small multiples
def bucket_panels(hists, fcs, bands, path, lender, metric_label):
    """hists/fcs/bands: dicts bucket -> Series / Series / DataFrame(p10,p90)."""
    keys = list(hists); fig, axes = plt.subplots(1, len(keys), figsize=(11, 3.6), dpi=200, sharex=True); fig.patch.set_facecolor(SURF); rows = []
    for ax, k in zip(np.atleast_1d(axes), keys):
        _style(ax); ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6)); h, f, b = 100 * hists[k], 100 * fcs[k], 100 * bands[k]
        ax.plot(h.index, h.values, color=BLUE, lw=LW); ax.fill_between(f.index, b.p10.values, b.p90.values, color=ORANGE, alpha=0.16, lw=0); ax.plot([h.index[-1]] + list(f.index), [h.iloc[-1]] + list(f.values), color=ORANGE, lw=LW)
        _dot(ax, f.index[-1], f.iloc[-1], ORANGE); ax.yaxis.set_major_formatter(pct); ax.set_title(f"{k} bucket", fontsize=9.5, color=INK, loc="left", fontweight="semibold"); ax.annotate(f"{f.iloc[-1]:.1f}%", (f.index[-1], f.iloc[-1]), xytext=(4, 6), textcoords="offset points", fontsize=8.5, color=INK, ha="right")
        rows += [pd.DataFrame({"bucket": k, "month": h.index, "series": "actual", "value_pct": h.values}), pd.DataFrame({"bucket": k, "month": f.index, "series": "forecast", "value_pct": f.values})]
    from matplotlib.lines import Line2D; fig.legend(handles=[Line2D([0], [0], color=BLUE, lw=LW, label="Actual"), Line2D([0], [0], color=ORANGE, lw=LW, label="Forecast (shaded: 80% range)")], loc="lower center", ncol=2, frameon=False, fontsize=8.5, labelcolor=INK2)
    t = f"{lender}: {metric_label} by starting bucket, forecast to {f.index[-1]:%b %Y}"; fig.text(0.012, 0.975, t, fontsize=11.5, fontweight="semibold", color=INK, va="top"); fig.subplots_adjust(left=0.05, right=0.99, top=0.78, bottom=0.2, wspace=0.28)
    p = pathlib.Path(path); p.parent.mkdir(parents=True, exist_ok=True); fig.savefig(p, facecolor=SURF); plt.close(fig); pd.concat(rows).to_csv(p.with_suffix(".csv"), index=False); p.with_suffix(".alt.txt").write_text(t + ". One panel per starting bucket; values in the adjacent CSV."); return str(p)
