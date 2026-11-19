import sys, pathlib, numpy as np, pandas as pd; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from attribution import attribute, shift_share
ok = lambda n, c: print(("PASS " if c else "FAIL ") + n) or c
rng = np.random.default_rng(1); r = []
def make(nT, nB, p_slice_T, p_slice_B, p_rest_T, p_rest_B, share_T=0.2, share_B=0.2):
    rows = []
    for is_T, n, sh, ps, pr in [(True, nT, share_T, p_slice_T, p_rest_T), (False, nB, share_B, p_slice_B, p_rest_B)]:
        s = rng.random(n) < sh; y = np.where(s, rng.random(n) < ps, rng.random(n) < pr)
        rows.append(pd.DataFrame({"is_T": is_T, "grp": np.where(s, "S", "R"), "roll_forward": y}))
    return pd.concat(rows, ignore_index=True)
# (a) planted: slice +10pp, rest +2pp background -> truth contribution = 0.2*(0.10-0.02)=1.6pp of 3.6pp change
df = make(20000, 100000, 0.40, 0.30, 0.322, 0.302)
a = attribute(df, "roll_forward", {"slice": {"dimension": "grp", "values": ["S"]}})
c = a["causes"]["slice"]; truth_c, truth_total = 1.6, 0.2 * 10 + 0.8 * 2
r += [ok(f"planted effect recovered: contribution {c['contribution_pp']:.2f}pp vs truth {truth_c}", abs(c["contribution_pp"] - truth_c) < 0.5)]
r += [ok(f"80% range covers truth {c['contribution_pp_80']}", c["contribution_pp_80"][0] <= truth_c <= c["contribution_pp_80"][1])]
r += [ok(f"share of change {c['share_of_change']:.0%} ~ truth {truth_c/truth_total:.0%}; remainder reported as unexplained {a['unexplained_share']:.0%}", abs(c["share_of_change"] - truth_c / truth_total) < 0.15)]
# (b) mix only: slice has higher base rate and grows in share, nobody's behaviour changes
df = make(20000, 100000, 0.60, 0.60, 0.20, 0.20, share_T=0.40, share_B=0.20)
a = attribute(df, "roll_forward", {"slice": {"dimension": "grp", "values": ["S"]}}, partition="grp"); ss = a["shift_share"]
r += [ok(f"mix-only: mix {ss['mix_total_pp']:.2f}pp ~ change {a['observed_change_pp']:.2f}pp, rate {ss['rate_total_pp']:.2f}pp ~ 0", abs(ss["mix_total_pp"] - a["observed_change_pp"]) < 0.6 and abs(ss["rate_total_pp"]) < 0.6)]
r += [ok("mix-only: slice excess ~ 0 (no behaviour change)", abs(a["causes"]["slice"]["contribution_pp"]) < 0.6)]
# (c) mix + rate add up exactly
r += [ok("shift-share is exactly additive", abs(ss["mix_total_pp"] + ss["rate_total_pp"] - a["observed_change_pp"]) < 1e-6)]
# (d) refusal + warnings
df = make(20000, 100000, 0.4, 0.3, 0.3, 0.3, share_T=0.001, share_B=0.2)
r += [ok("slice too small is refused", attribute(df, "roll_forward", {"s": {"dimension": "grp", "values": ["S"]}})["causes"]["s"]["status"] == "too_small_to_attribute")]
df = make(20000, 100000, 0.4, 0.3, 0.3, 0.3)
a = attribute(df, "roll_forward", {"x": {"dimension": "grp", "values": ["S"]}, "y": {"dimension": "grp", "values": ["S", "R"]}})
r += [ok("overlapping causes flagged", any("overlap" in w for w in a["warnings"]))]
df = make(20000, 100000, 0.30, 0.30, 0.30, 0.30)
a = attribute(df, "roll_forward", {"s": {"dimension": "grp", "values": ["S"]}})
r += [ok("no real change -> shares withheld", a["unexplained_share"] is None and a["causes"]["s"]["share_of_change"] is None)]
# (e) real data through the tool
from attribution import AttributionTool
t = AttributionTool("LENDER_A", "2025-05-01", run_id="test_attr")
x = t("2025-05-01", "31-60", "roll_forward", {"agency_attrition": {"dimension": "agency_id", "values": ["AG_W_TELE_02"]}}, region="WEST", recent_months=3, baseline_lag=3, partition_dimension="agency_id")
c = x["causes"]["agency_attrition"]
print(f"   real: AG_W_TELE_02 pool change {x['observed_change_pp']:.2f}pp, cause contribution {c['contribution_pp']:.2f}pp (80% {c['contribution_pp_80'][0]:.2f}..{c['contribution_pp_80'][1]:.2f}), share {c['share_of_change']}, unexplained {x['unexplained_share']}")
r += [ok("real case returns an id and contribution", x["ok"] and x["attribution_id"] == "A001" and c["status"] == "ok")]
r += [ok("unknown dimension returned as error result", not t("2025-05-01", "31-60", "roll_forward", {"z": {"dimension": "nope", "values": ["a"]}})["ok"])]
sys.exit(0 if all(r) else 1)
