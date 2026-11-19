"""
PS-03 Roll-Rate Forecaster - realistic synthetic collections dataset generator.

Simulates three lenders' retail/SME loan books month by month (account-level Markov
process whose transition probabilities are driven by borrower risk, seasonality,
collection activity and seeded real-world events), then writes:
  dim_lender, dim_product, dim_geography, dim_agency, dim_bucket,
  d1_account_monthly, d3_collection_events, bucket_flow_history, event_calendar
split into public (24 months) and hidden (3 months) periods, plus an answer key.
"""
import numpy as np, pandas as pd, os, calendar as cal
from scipy.special import expit, logit
pd.set_option("future.infer_string", False)

rng = np.random.default_rng(20251119)
os.makedirs("/home/claude/tmp", exist_ok=True)
OUT = "/home/claude/rollrate_dataset"

SIM_START, OUT_START = pd.Timestamp("2022-10-01"), pd.Timestamp("2023-10-01")
HID_START, END = pd.Timestamp("2025-10-01"), pd.Timestamp("2025-12-01")
MONTHS = pd.date_range(SIM_START, END, freq="MS")
T = len(MONTHS)
def mi(s): return MONTHS.get_loc(pd.Timestamp(s).to_period("M").to_timestamp())

REGIONS = ["NORTH", "SOUTH", "EAST", "WEST"]
RC = {"NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W"}
PRODUCTS = ["PERSONAL_LOAN", "TWO_WHEELER", "BUSINESS_LOAN"]
PC = {"PERSONAL_LOAN": "PL", "TWO_WHEELER": "TW", "BUSINESS_LOAN": "BL"}

# ---------------------------------------------------------------- geography
GEO = [
 ("NORTH","Delhi","New Delhi","110",.28),("NORTH","Uttar Pradesh","Lucknow","226",.16),
 ("NORTH","Uttar Pradesh","Kanpur","208",.10),("NORTH","Haryana","Gurugram","122",.14),
 ("NORTH","Punjab","Ludhiana","141",.12),("NORTH","Rajasthan","Jaipur","302",.20),
 ("SOUTH","Karnataka","Bengaluru","560",.26),("SOUTH","Karnataka","Mangaluru","575",.06),
 ("SOUTH","Tamil Nadu","Chennai","600",.18),("SOUTH","Tamil Nadu","Coimbatore","641",.09),
 ("SOUTH","Tamil Nadu","Madurai","625",.06),("SOUTH","Kerala","Kochi","682",.08),
 ("SOUTH","Kerala","Kozhikode","673",.05),("SOUTH","Telangana","Hyderabad","500",.16),
 ("SOUTH","Andhra Pradesh","Vijayawada","520",.06),
 ("EAST","West Bengal","Kolkata","700",.38),("EAST","Odisha","Bhubaneswar","751",.16),
 ("EAST","Bihar","Patna","800",.20),("EAST","Jharkhand","Ranchi","834",.12),("EAST","Assam","Guwahati","781",.14),
 ("WEST","Maharashtra","Mumbai","400",.24),("WEST","Maharashtra","Pune","411",.18),
 ("WEST","Maharashtra","Nagpur","440",.08),("WEST","Gujarat","Ahmedabad","380",.16),
 ("WEST","Gujarat","Surat","395",.16),("WEST","Gujarat","Vadodara","390",.07),("WEST","Madhya Pradesh","Indore","452",.11),
]
geo_rows = []
for reg, st, city, p3, w in GEO:
    suffixes = sorted(rng.choice(np.arange(1, 99), 22, replace=False))
    for s in suffixes:
        geo_rows.append(dict(pin_code=f"{p3}{s:03d}", city=city, state=st, region=reg,
                             city_weight=w / 22, coastal_flood_zone=p3 in ("575", "673", "682")))
dim_geo = pd.DataFrame(geo_rows)

# ---------------------------------------------------------------- lenders
LENDERS = {
 "LENDER_A": dict(name="Sahyadri Finserv Ltd", prefix="SFS", lender_type="Diversified NBFC",
                  hq="Pune", init=100000, disb=4400, growth=0.0,
                  prod={"PERSONAL_LOAN": .40, "TWO_WHEELER": .30, "BUSINESS_LOAN": .30},
                  reg={"NORTH": .20, "SOUTH": .30, "EAST": .15, "WEST": .35}),
 "LENDER_B": dict(name="Kaveri Auto & Personal Finance Ltd", prefix="KAF", lender_type="Vehicle & Consumer NBFC",
                  hq="Chennai", init=65000, disb=3250, growth=0.007,
                  prod={"TWO_WHEELER": .58, "PERSONAL_LOAN": .27, "BUSINESS_LOAN": .15},
                  reg={"NORTH": .25, "SOUTH": .35, "EAST": .20, "WEST": .20}),
 "LENDER_C": dict(name="Nimbus Digital Lending Pvt Ltd", prefix="NDL", lender_type="Digital NBFC (Fintech)",
                  hq="Bengaluru", init=50000, disb=2900, growth=0.004,
                  prod={"PERSONAL_LOAN": .60, "BUSINESS_LOAN": .22, "TWO_WHEELER": .18},
                  reg={"NORTH": .35, "SOUTH": .30, "EAST": .10, "WEST": .25}),
}
LIDS = list(LENDERS)

PROD = {
 "PERSONAL_LOAN": dict(med=150000, sig=.55, lo=30000, hi=1000000, ten=([12,24,36,48],[.15,.35,.35,.15]),
                       rate=(13,24), emp=(["SALARIED","SELF_EMPLOYED","GIG_WORKER"],[.70,.22,.08]),
                       ntc=.10, bounce=.060, prepay=.013),
 "TWO_WHEELER":  dict(med=95000, sig=.25, lo=55000, hi=250000, ten=([12,18,24,30,36],[.08,.17,.35,.15,.25]),
                       rate=(10,19), emp=(["SALARIED","SELF_EMPLOYED","GIG_WORKER"],[.50,.30,.20]),
                       ntc=.18, bounce=.076, prepay=.010),
 "BUSINESS_LOAN":dict(med=500000, sig=.60, lo=150000, hi=3000000, ten=([12,24,36],[.2,.45,.35]),
                       rate=(16,26), emp=(["SELF_EMPLOYED","SALARIED"],[.95,.05]),
                       ntc=.08, bounce=.055, prepay=.008),
}
EMP_RISK = {"SALARIED": 1.0, "SELF_EMPLOYED": 1.15, "GIG_WORKER": 1.35}
REG_RISK = {"NORTH": 1.0, "SOUTH": .90, "EAST": 1.15, "WEST": 1.0}
DUE_DAYS, DUE_P = np.array([2,3,5,7,10,15]), np.array([.18,.08,.30,.18,.16,.10])

# ---------------------------------------------------------------- agencies
AG_NAMES = {
 "N": ["Pragati Recovery Services","Sankalp Credit Solutions","Vishwas Field Collections","Uttam Recovery Associates","Nyaya Legal Associates"],
 "S": ["Sri Lakshmi Credit Services","Dakshin Recovery Solutions","Kaveri Field Force Pvt Ltd","Anugraha Collections","Satyam & Co Advocates"],
 "E": ["Purbasha Credit Management","Ganga Recovery Services","Ekta Field Associates","Swastik Collections","Mitra Legal Chambers"],
 "W": ["Sahyog Credit Management","Disha Tele Recovery Pvt Ltd","Marathwada Field Services","Shree Ganesh Recovery Agency","Kulkarni & Shah Legal LLP"],
}
ag_rows, AGQ, AGPOOL = [], {}, {}
for reg, r in RC.items():
    nm = AG_NAMES[r]
    for aid, n, typ, q, pool in [
        (f"CN_{r}_DIGI", f"CN Digital Collections Desk - {reg.title()}", "IN_HOUSE_DIGITAL_TELE", 1.00, 60),
        (f"AG_{r}_TELE_01", nm[0], "TELE_AGENCY", rng.uniform(.97, 1.06), 40),
        (f"AG_{r}_TELE_02", nm[1], "TELE_AGENCY", rng.uniform(.95, 1.04), 38),
        (f"AG_{r}_FLD_01", nm[2], "FIELD_AGENCY", rng.uniform(.95, 1.05), 30),
        (f"AG_{r}_FLD_02", nm[3], "FIELD_AGENCY", rng.uniform(.93, 1.04), 26),
        (f"LGL_{r}_01", nm[4], "LEGAL_PARTNER", 1.0, 6)]:
        ag_rows.append(dict(agency_id=aid, agency_name=n, agency_type=typ, region=reg,
                            empanelled_since=str(rng.choice(["2019-04-01","2020-07-01","2021-01-01","2021-10-01","2022-04-01"])),
                            contract_status="ACTIVE"))
        AGQ[aid], AGPOOL[aid] = q, pool
dim_agency = pd.DataFrame(ag_rows)

# ---------------------------------------------------------------- calendar (dates) and effects
DIWALI = {"2022-10-24": None, "2023-11-12": None, "2024-11-01": None, "2025-10-20": None}
DURGA = ["2022-10-05", "2023-10-24", "2024-10-12", "2025-10-02"]       # Vijaya Dashami (East)
PONGAL = ["2023-01-15", "2024-01-15", "2025-01-14"]                    # South
ONAM = ["2023-08-29", "2024-09-15", "2025-09-05"]                      # Kerala cities
GANESH = ["2023-09-19", "2024-09-07", "2025-08-27"]                    # West
HOLI = ["2023-03-08", "2024-03-25", "2025-03-14"]                      # North
EID = ["2023-04-22", "2024-04-11", "2025-03-31"]

# fest_bad[t, region] : adds to bounce/roll-forward logit; catch[t, region] : catch-up in following month
fest_bad = np.zeros((T, 4)); catch = np.zeros((T, 4)); fest_field = np.ones((T, 4))
def add(dates, regs, bad, catchup=0.0, field=1.0):
    for d in dates:
        t = mi(d) if pd.Timestamp(d) >= SIM_START else None
        if t is None: continue
        for g in regs:
            k = REGIONS.index(g); fest_bad[t, k] += bad; fest_field[t, k] *= field
            if t + 1 < T: catch[t + 1, k] += catchup
add(list(DIWALI), REGIONS, .26, .20, .80)
add(DURGA, ["EAST"], .17, .08, .85)
add(PONGAL, ["SOUTH"], .08, .04)
add(GANESH, ["WEST"], .07, .03)
add(HOLI, ["NORTH"], .05)
add(EID, REGIONS, .03)
for y in (2022, 2023, 2024, 2025):                       # year-end holidays
    t = mi(f"{y}-12-01"); fest_bad[t, :] += .05
march_push = np.zeros(T)
for y in (2023, 2024, 2025): march_push[mi(f"{y}-03-01")] = .25   # fiscal year-end collection drive

# seeded events --------------------------------------------------------------
REG_START = mi("2024-04-01")                      # recovery-agent conduct norms (STEP, small)
OUTAGE_T = mi("2024-06-01")                       # Lender A UPI payment-link gateway outage 18-27 Jun (DOT, silent)
FLOOD_T = mi("2024-07-01")                        # coastal South flooding (DOT, calendar)
SURAT_TS = {mi("2024-08-01"): .55, mi("2024-09-01"): 1.0, mi("2024-10-01"): .55, mi("2024-11-01"): .2}  # silent borrower shock
LOOSE = (mi("2024-11-01"), mi("2025-02-01"))     # Lender C PL eligibility expansion (lagged cohort STEP)
AUTOPAY_T = mi("2025-01-01")                      # Lender B UPI Autopay + WhatsApp pay-link (improvement STEP)
ATTR_T = mi("2025-03-01")                         # AG_W_TELE_02 attrition (silent STEP), serves A & C
BPOL_T = mi("2025-11-01")                         # HIDDEN: Lender B no field visits if EMI < 10,000 (STEP)
CTECH_T = mi("2025-12-01")                        # HIDDEN: Lender C sponsor-bank NACH tech failure 3-6 Dec (DOT, silent)

# ---------------------------------------------------------------- account book
cols = {k: [] for k in ["disb_day","account_id","lender_id","product_type","region","state","city","pin_code",
                        "disb_t","loan_amount","tenure","rate","emi","due_day","employment_type",
                        "bureau_score","ntc","risk","phone_invalid","u_tele","u_field"]}
seq = {l: 0 for l in LIDS}
geo_by_reg = {g: dim_geo[dim_geo.region == g].reset_index(drop=True) for g in REGIONS}

def new_accounts(lid, n, t, mob_init=None):
    L = LENDERS[lid]
    prods = rng.choice(list(L["prod"]), n, p=list(L["prod"].values()))
    regs = rng.choice(list(L["reg"]), n, p=list(L["reg"].values()))
    loose = lid == "LENDER_C" and LOOSE[0] <= t <= LOOSE[1]
    for p in PRODUCTS:
        for g in REGIONS:
            idx = np.where((prods == p) & (regs == g))[0]; k = len(idx)
            if k == 0: continue
            P, G = PROD[p], geo_by_reg[g]
            gi = rng.choice(len(G), k, p=(G.city_weight / G.city_weight.sum()).values)
            amt = np.clip(np.exp(np.log(P["med"]) + P["sig"] * rng.standard_normal(k)), P["lo"], P["hi"])
            if loose and p == "PERSONAL_LOAN": amt *= 1.18
            amt = np.round(amt / 1000) * 1000
            ten = rng.choice(P["ten"][0], k, p=P["ten"][1])
            rate = np.round(rng.uniform(*P["rate"], k) + (2.0 if loose and p == "PERSONAL_LOAN" else 0), 2)
            r = rate / 1200; emi = np.round(amt * r * (1 + r) ** ten / ((1 + r) ** ten - 1))
            emp = rng.choice(P["emp"][0], k, p=P["emp"][1])
            ntc_p = .36 if (loose and p == "PERSONAL_LOAN") else P["ntc"]
            ntc = rng.random(k) < ntc_p
            bmean = 705 if (loose and p == "PERSONAL_LOAN") else 748
            bureau = np.clip(np.round(rng.normal(bmean, 42, k)), 600, 890).astype(float); bureau[ntc] = np.nan
            bf = np.exp(-(np.nan_to_num(bureau, nan=700) - 745) / 60 * .40) * np.where(ntc, 1.30, 1.0)
            risk = np.exp(.38 * rng.standard_normal(k)) * bf * np.array([EMP_RISK[e] for e in emp]) * REG_RISK[g]
            if loose and p == "PERSONAL_LOAN": risk *= 1.95
            if mob_init is not None:
                dt_ = t - rng.integers(1, np.maximum(ten, 2))
            else:
                dt_ = np.full(k, t)
            seq[lid] += k
            dmonths = [MONTHS[0] + pd.DateOffset(months=int(x)) if x >= 0 else MONTHS[0] - pd.DateOffset(months=int(-x)) for x in dt_]
            ids = [f"{L['prefix']}{PC[p]}{dm.strftime('%y%m')}{s:06d}" for dm, s in zip(dmonths, range(seq[lid] - k + 1, seq[lid] + 1))]
            cols["account_id"] += ids; cols["lender_id"] += [lid] * k; cols["product_type"] += [p] * k
            cols["region"] += [g] * k; cols["state"] += list(G.state.values[gi]); cols["city"] += list(G.city.values[gi])
            cols["pin_code"] += list(G.pin_code.values[gi]); cols["disb_t"] += list(dt_)
            cols["loan_amount"] += list(amt); cols["tenure"] += list(ten); cols["rate"] += list(rate); cols["emi"] += list(emi)
            cols["due_day"] += list(rng.choice(DUE_DAYS, k, p=DUE_P)); cols["employment_type"] += list(emp)
            cols["bureau_score"] += list(bureau); cols["ntc"] += list(ntc); cols["risk"] += list(risk)
            cols["phone_invalid"] += list(rng.random(k) < np.where(ntc, .11, .05))
            cols["disb_day"] += list(rng.integers(1, 29, k))
            cols["u_tele"] += list(rng.random(k)); cols["u_field"] += list(rng.random(k))

for lid in LIDS:
    new_accounts(lid, LENDERS[lid]["init"], 0, mob_init=True)

def book():
    A = pd.DataFrame(cols)
    return A

# mutable state arrays (grow as accounts are added)
state = dict(m=np.zeros(0, int), status=np.zeros(0, int), dpd=np.zeros(0, int), pos=np.zeros(0))
def grow(n):
    for k, v in state.items():
        state[k] = np.concatenate([v, np.zeros(n - len(v), v.dtype)])

_P0 = pd.Period(SIM_START, "M")
def disb_dates(dt_arr, day_arr):
    dt_arr = np.asarray(dt_arr); day_arr = np.asarray(day_arr); out = np.empty(len(dt_arr), dtype=object)
    for v in np.unique(dt_arr):
        p = _P0 + int(v); mk = dt_arr == v
        out[mk] = [pd.Timestamp(p.year, p.month, int(min(d, p.days_in_month))).date() for d in day_arr[mk]]
    return out

def dpd_from(m, due_day, dim):
    return np.where(m == 0, 0, 30 * (m - 1) + np.maximum(dim - due_day, 1))
def bucket_of(m):
    return np.select([m == 0, m == 1, m == 2, m == 3], ["CURRENT", "1-30", "31-60", "61-90"], "90+")

BOUNCE_REASONS = np.array(["INSUFFICIENT_FUNDS","AMOUNT_EXCEEDS_MANDATE_LIMIT","MANDATE_CANCELLED_BY_CUSTOMER",
                           "PAYMENT_STOPPED_BY_DRAWER","ACCOUNT_FROZEN_BLOCKED","ACCOUNT_CLOSED","TECH_ERROR_BANK_NPCI"])
BOUNCE_P = np.array([.70,.06,.05,.04,.04,.03,.08])

d1_parts, d3_parts = [], []
ev_counter = 0
A = None

for t in range(T):
    month = MONTHS[t]; dim = cal.monthrange(month.year, month.month)[1]; out = month >= OUT_START
    # ---- new disbursals this month
    for lid in LIDS:
        L = LENDERS[lid]; n = L["disb"] * (1 + L["growth"]) ** t
        if lid == "LENDER_C" and LOOSE[0] <= t <= LOOSE[1]: n *= 1.45
        n = int(rng.poisson(n)); new_accounts(lid, n, t)
    A = book(); N = len(A); grow(N)
    disb_t = A.disb_t.values
    act = (state["status"] == 0) & (disb_t < t)
    newm = disb_t == t
    idx = np.where(act)[0]
    lender = A.lender_id.values[idx]; prod = A.product_type.values[idx]; reg = A.region.values[idx]
    regk = np.array([REGIONS.index(x) for x in reg]); city = A.city.values[idx]; pin = A.pin_code.values[idx]
    emi = A.emi.values[idx]; due = A.due_day.values[idx]; ten = A.tenure.values[idx]; risk = A.risk.values[idx]
    emp = A.employment_type.values[idx]
    mob = t - disb_t[idx]; m0 = state["m"][idx].copy(); n = len(idx)
    lr = np.log(risk)

    # ---- event modifiers (vectorised)
    fb = fest_bad[t, regk] + 0.0; cu = catch[t, regk] + march_push[t]
    surat = (np.char.startswith(pin.astype(str), "395")) & ((prod == "BUSINESS_LOAN") | (emp == "SELF_EMPLOYED")) & (t in SURAT_TS)
    shock = np.where(surat, SURAT_TS.get(t, 0) * .85, 0.0)
    flood = (t == FLOOD_T) & np.isin(A.city.values[idx], ["Mangaluru", "Kochi", "Kozhikode"])
    fb = fb + np.where(flood, .35, 0)
    outage = (t == OUTAGE_T) & (lender == "LENDER_A")
    autopay = (t >= AUTOPAY_T) & (lender == "LENDER_B")
    reg_mult = .86 if t >= REG_START else 1.0
    mob_eff = np.where(mob <= 3, .45, np.where(mob <= 6, .20, 0))

    # ---- allocation (based on opening bucket)
    tele_ag = np.where(lender == "LENDER_B", np.where(reg == "WEST", True, A.u_tele.values[idx] < .5),
                       A.u_tele.values[idx] < np.where(lender == "LENDER_A", .55, .50))
    tele_id = np.array([f"AG_{RC[g]}_TELE_0{1 if x else 2}" for g, x in zip(reg, tele_ag)])
    fld_id = np.array([f"AG_{RC[g]}_FLD_0{1 if u < .5 else 2}" for g, u in zip(reg, A.u_field.values[idx])])
    digi_id = np.array([f"CN_{RC[g]}_DIGI" for g in reg])
    attr = (t >= ATTR_T) & (tele_id == "AG_W_TELE_02")
    bpol = (t >= BPOL_T) & (lender == "LENDER_B") & (emi < 10000)

    # ---- maturity / prepayment for current accounts
    cur = m0 == 0
    matured = cur & (mob >= ten)
    prepay = cur & ~matured & (rng.random(n) < np.array([PROD[p]["prepay"] for p in prod]))
    # ---- NACH presentation / bounce for current
    bb = np.array([PROD[p]["bounce"] for p in prod])
    tech = (t == CTECH_T) & (lender == "LENDER_C") & np.isin(due, [3, 5, 7])
    Lb_cur = logit(bb) + lr + mob_eff + fb + shock * 1.1 + np.where(tech, .75, 0)
    bounce = cur & ~matured & ~prepay & (rng.random(n) < expit(Lb_cur))
    reason = np.full(n, None, dtype=object)
    rsn = rng.choice(BOUNCE_REASONS, n, p=BOUNCE_P)
    rsn = np.where((shock > 0) & (rng.random(n) < .6), "INSUFFICIENT_FUNDS", rsn)
    rsn = np.where(tech & (rng.random(n) < .55), "TECH_ERROR_BANK_NPCI", rsn)
    reason[bounce] = rsn[bounce]

    # ---- collections activity (bounced-current and delinquent)
    coll = bounce | (m0 >= 1)
    bk = np.where(m0 >= 4, 4, m0)
    lam = np.select([bk == 0, bk == 1, bk == 2, bk == 3, bk == 4], [3.0, 6.5, 9.0, 8.0, 5.0]) * reg_mult
    call_ag = np.select([bk <= 1, bk == 2], [digi_id, tele_id], fld_id)
    attr_c = attr & (bk == 2)
    lam = lam * np.where(attr_c, .40, 1) * np.where(flood, .7, 1) * np.where(fest_bad[t, regk] > .2, .92, 1)
    n_calls = np.where(coll, rng.poisson(lam), 0)
    q = np.array([AGQ[a] for a in call_ag])
    pc = .27 * q * risk ** -.30 * np.where(attr_c, .52, 1) * np.where(flood, .6, 1)
    inval = A.phone_invalid.values[idx]
    n_conn = np.where(inval, 0, rng.binomial(n_calls, np.clip(pc, .02, .9)))
    rpc = (n_conn > 0) & (rng.random(n) < .9)
    ptp = rpc & (rng.random(n) < np.clip(.48 * risk ** -.3, .05, .9))
    lamf = np.select([bk == 2, bk == 3, bk == 4], [np.where(prod == "TWO_WHEELER", .8, .35), 1.7, 1.3], 0) \
           * fest_field[t, regk] * np.where(flood, .3, 1) * np.where(bpol, 0, 1)
    n_field = np.where(coll, rng.poisson(lamf), 0)
    field_met = (n_field > 0) & (rng.random(n) < 1 - .45 ** np.maximum(n_field, 1))
    act_eff = np.where(rpc, .50, -.38) + np.where(ptp, .42 * np.where(shock > 0, .4, 1), 0)
    fld_eff = np.where(field_met, np.select([bk == 2, bk >= 3], [.50, .85], 0) + np.where(prod == "TWO_WHEELER", .35, 0), 0)

    # ---- outcomes
    new_m = m0.copy(); outcome = np.full(n, "", dtype=object)
    # bounced current -> resolve within month?
    Lr = logit(np.where(prod == "BUSINESS_LOAN", .55, .58)) + act_eff - .55 * lr - .8 * fb - shock * 1.1 \
         + cu + np.where(autopay, .50, 0) - np.where(outage, .75, 0) \
         + np.where(reason == "TECH_ERROR_BANK_NPCI", 1.3, 0)
    res = bounce & (rng.random(n) < expit(Lr))
    new_m[bounce & ~res] = 1
    outcome[cur] = "STAY"; outcome[bounce & res] = "RESOLVED"; outcome[bounce & ~res] = "FWD"
    # delinquent
    dl = m0 >= 1
    base = {1: (.50, 0, .33), 2: (.13, .14, .50), 3: (.05, .09, .66), 4: (.012, .025, .93)}
    cure_b = np.select([bk == 1, bk == 2, bk == 3], [.50, .13, .05], .012)
    back_b = np.select([bk == 1, bk == 2, bk == 3], [1e-6, .14, .09], .025)
    fwd_b = np.select([bk == 1, bk == 2, bk == 3], [.29, .48, .64], .93)
    Lb = lr * .8 + np.where(prod == "TWO_WHEELER", .08, 0) + fb + shock * 1.0
    Lg = act_eff + fld_eff + cu - np.where(attr_c, .50, 0) + np.where(autopay & (bk == 1), .45, 0) - np.where(outage & (bk == 1), .6, 0)
    pf = expit(logit(fwd_b) + Lb - .5 * Lg); pcu = expit(logit(cure_b) - .9 * Lb + Lg)
    pba = np.where(bk >= 2, expit(logit(back_b) - .6 * Lb + .6 * Lg), 0)
    tot = pf + pcu + pba; sc = np.where(tot > .97, .97 / tot, 1); pf, pcu, pba = pf * sc, pcu * sc, pba * sc
    u = rng.random(n)
    o_cure = dl & (u < pcu); o_back = dl & (u >= pcu) & (u < pcu + pba)
    o_fwd = dl & (u >= pcu + pba) & (u < pcu + pba + pf); o_stay = dl & ~(o_cure | o_back | o_fwd)
    new_m[o_cure] = 0; new_m[o_back] -= 1; new_m[o_fwd] += 1
    outcome[o_cure], outcome[o_back], outcome[o_fwd], outcome[o_stay] = "CURE", "BACK", "FWD", "STAY_PAID"
    # 90+ terminal events
    settle = (m0 >= 4) & (rng.random(n) < .012 + .02 * field_met)
    wo = (m0 >= 7) & ~settle & (rng.random(n) < .22)
    status_new = np.zeros(n, int)
    status_new[matured | prepay | settle] = 1; status_new[wo] = 2
    new_m[matured | prepay] = 0
    # delinquent NACH status
    nach = np.where(cur, np.where(bounce, "BOUNCED", "SUCCESS"), "")
    paid_nach = dl & (o_cure | o_back | o_stay) & (rng.random(n) < .30)
    nach = np.where(dl, np.where(paid_nach, "SUCCESS", "BOUNCED"), nach)
    dreason = rng.choice(BOUNCE_REASONS, n, p=[.82, .03, .07, .03, .02, .02, .01])
    reason = np.where(dl & (nach == "BOUNCED"), dreason, reason)

    # ---- positions
    r = A.rate.values[idx] / 1200; P = A.loan_amount.values[idx]
    paid_inst = np.clip(mob - new_m, 0, ten)
    pos = np.where(paid_inst >= ten, 0, P * ((1 + r) ** ten - (1 + r) ** paid_inst) / ((1 + r) ** ten - 1))
    pos_open = state["pos"][idx].copy()
    pos_open = np.where(pos_open == 0, P * ((1 + r) ** ten - (1 + r) ** np.clip(mob - 1 - m0, 0, ten)) / ((1 + r) ** ten - 1), pos_open)
    dpd_prev = state["dpd"][idx].copy()
    dpd_new = dpd_from(new_m, due, dim)

    # ---- write state
    state["m"][idx] = new_m; state["status"][idx] = status_new; state["dpd"][idx] = dpd_new; state["pos"][idx] = pos
    newi = np.where(newm)[0]
    state["pos"][newi] = A.loan_amount.values[newi]

    if not out:
        continue
    # ================= D1 rows
    b_prev = bucket_of(m0)
    b_curr = np.where(status_new == 1, "CLOSED", np.where(status_new == 2, "WRITTEN_OFF", bucket_of(new_m)))
    closure = np.select([matured, prepay, settle, wo], ["MATURED", "FORECLOSED", "SETTLED", "WRITTEN_OFF"], None)
    alloc = np.select([~coll, bk <= 1, bk == 2, bk == 3], ["NONE", "DIGITAL_TELE", "TELE", "FIELD"], "FIELD_LEGAL")
    alloc = np.where(coll & bpol & (bk >= 2), "DIGITAL_TELE", alloc)
    alloc_ag = np.where(~coll, None, np.select([bk <= 1, bk == 2], [digi_id, tele_id], fld_id))
    alloc_ag = np.where(coll & bpol & (bk >= 2), tele_id, alloc_ag)
    overdue = np.where(new_m > 0, np.round(new_m * emi * 1.02), 0)
    d1 = pd.DataFrame(dict(
        month_date=month.date(), account_id=A.account_id.values[idx], lender_id=lender, product_type=prod,
        region=reg, state=A.state.values[idx], city=city, pin_code=pin,
        disbursement_date=disb_dates(disb_t[idx], A.disb_day.values[idx]),
        loan_amount=P, tenure_months=ten, interest_rate=A.rate.values[idx], emi_amount=emi, emi_due_day=due, mob=mob,
        employment_type=emp, bureau_score=A.bureau_score.values[idx], ntc_flag=A.ntc.values[idx],
        pos_opening=np.round(pos_open), pos_closing=np.where(status_new > 0, 0, np.round(pos)), overdue_amount=overdue,
        dpd_prev=dpd_prev, dpd_curr=np.where(status_new > 0, 0, dpd_new), bucket_prev=b_prev, bucket_curr=b_curr,
        nach_status=nach, bounce_reason=reason, agency_id=alloc_ag, allocation_channel=alloc,
        account_status=np.select([status_new == 1, status_new == 2], ["CLOSED", "WRITTEN_OFF"], "ACTIVE"),
        closure_reason=closure))
    # new disbursals rows
    nd = A.iloc[newi]
    d1n = pd.DataFrame(dict(
        month_date=month.date(), account_id=nd.account_id.values, lender_id=nd.lender_id.values, product_type=nd.product_type.values,
        region=nd.region.values, state=nd.state.values, city=nd.city.values, pin_code=nd.pin_code.values,
        disbursement_date=disb_dates(nd.disb_t.values, nd.disb_day.values), loan_amount=nd.loan_amount.values, tenure_months=nd.tenure.values,
        interest_rate=nd.rate.values, emi_amount=nd.emi.values, emi_due_day=nd.due_day.values, mob=0,
        employment_type=nd.employment_type.values, bureau_score=nd.bureau_score.values, ntc_flag=nd.ntc.values,
        pos_opening=np.nan, pos_closing=nd.loan_amount.values, overdue_amount=0.0, dpd_prev=np.nan, dpd_curr=0,
        bucket_prev="NEW", bucket_curr="CURRENT", nach_status="NOT_DUE", bounce_reason=None, agency_id=None,
        allocation_channel="NONE", account_status="ACTIVE", closure_reason=None))
    d1m = pd.concat([d1, d1n], ignore_index=True)
    for c in ["dpd_prev", "dpd_curr", "bureau_score"]: d1m[c] = d1m[c].astype("Int64")
    d1m["ntc_flag"] = d1m.ntc_flag.astype(bool)
    d1m.to_parquet(f"/home/claude/tmp/d1_{month.strftime('%Y%m')}.parquet", index=False)
    n_d1 = len(d1m); del d1m

    # ================= D3 events (vectorised explosion)
    ci = np.where(coll)[0]
    acc_id = A.account_id.values[idx]
    start_day = np.where(m0 == 0, due, 1)
    pre_reg = t < REG_START
    evs = []
    def stamps(rows, sd, hour_lo=9, hour_hi=19, spread=True):
        k = len(rows)
        day = np.minimum(sd + (rng.random(k) * (dim - sd + 1)).astype(int), dim)
        hr = rng.integers(hour_lo, hour_hi, k)
        if pre_reg:
            off = rng.random(k) < .06; hr = np.where(off, rng.choice([7, 20], k), hr)
        mn = rng.integers(0, 60, k); sc = rng.integers(0, 60, k)
        return pd.to_datetime(dict(year=month.year, month=month.month, day=day, hour=hr, minute=mn, second=sc))
    # calls
    nc = n_calls[ci]; rep = np.repeat(ci, nc)
    if len(rep):
        st = np.cumsum(nc) - nc; k = np.arange(len(rep)) - np.repeat(st, nc)
        conn = k < n_conn[rep]
        nonc = rng.choice(["NO_ANSWER", "SWITCHED_OFF", "BUSY", "NOT_REACHABLE"], len(rep), p=[.55, .22, .11, .12])
        status = np.where(inval[rep], "INVALID_NUMBER", np.where(conn, "CONNECTED", nonc))
        sh = shock[rep] > 0
        dpool = rng.choice(["CALLBACK_REQUESTED", "FOLLOW_UP_REMINDER", "REFUSED_TO_PAY", "THIRD_PARTY_CONTACT",
                            "FINANCIAL_DIFFICULTY", "DISPUTE_RAISED", "ALREADY_PAID_CLAIM"], len(rep),
                           p=[.30, .24, .10, .12, .15, .03, .06])
        dpool = np.where(sh & (rng.random(len(rep)) < .55), rng.choice(["BUSINESS_LOSS", "FINANCIAL_DIFFICULTY"], len(rep)), dpool)
        dpool = np.where(~rpc[rep] & conn, "THIRD_PARTY_CONTACT", dpool)
        ptp_call = conn & (k == 0) & ptp[rep]
        nonc_disp = pd.Series(status).map({"NO_ANSWER": "RNR", "SWITCHED_OFF": "SW_OFF", "BUSY": "BUSY",
                                            "NOT_REACHABLE": "NOT_REACHABLE", "INVALID_NUMBER": "WRONG_NUMBER"}).values
        disp = np.where(conn, np.where(ptp_call, "PTP", dpool), nonc_disp)
        dur = np.where(conn, rng.gamma(2.2, 85, len(rep)).astype(int) + 25, rng.integers(0, 38, len(rep)))
        ag = call_ag[rep]
        pool = np.array([AGPOOL[a] if not (a == "AG_W_TELE_02" and t >= ATTR_T) else 14 for a in ag])
        agent = np.array([f"{a}-A{(x % p) + 1:03d}" for a, x, p in zip(ag, rng.integers(0, 10000, len(rep)), pool)])
        ts = stamps(rep, start_day[rep])
        ptp_amt = np.where(ptp_call, np.where(m0[rep] == 0, emi[rep], np.round(np.maximum(m0[rep], 1) * emi[rep])), np.nan)
        ptp_dt = np.where(ptp_call, (ts + pd.to_timedelta(rng.integers(1, 9, len(rep)), "D")).dt.date, None)
        evs.append(pd.DataFrame(dict(account_id=acc_id[rep], lender_id=lender[rep], event_timestamp=ts,
                   channel="VOICE_CALL", agency_id=ag, agent_id=agent, attempt_status=status, disposition_code=disp,
                   call_duration_sec=dur, ptp_amount=ptp_amt, ptp_date=ptp_dt)))
    # SMS & WhatsApp
    for chn, base_n, fail, lamx in [("SMS", 1, .045, 1.0), ("WHATSAPP", 1, .07, .6 + .3 * (t >= mi("2024-07-01")))]:
        cnt = base_n + rng.poisson(lamx, len(ci)); rep = np.repeat(ci, cnt)
        st_ = np.where(rng.random(len(rep)) < fail, "FAILED_DELIVERY",
                       "DELIVERED" if chn == "SMS" else np.where(rng.random(len(rep)) < .62, "READ", "DELIVERED"))
        evs.append(pd.DataFrame(dict(account_id=acc_id[rep], lender_id=lender[rep], event_timestamp=stamps(rep, start_day[rep], 8, 20),
                   channel=chn, agency_id=digi_id[rep], agent_id=None, attempt_status=st_,
                   disposition_code="PAYMENT_LINK_SENT" if chn == "WHATSAPP" else "REMINDER_SENT")))
    # field visits
    nf = n_field[ci]; rep = np.repeat(ci, nf)
    if len(rep):
        st = np.cumsum(nf) - nf; k = np.arange(len(rep)) - np.repeat(st, nf)
        met = (k == 0) & field_met[rep]
        miss = rng.choice(["DOOR_LOCKED", "CUSTOMER_NOT_AVAILABLE", "CUSTOMER_SHIFTED"], len(rep), p=[.45, .38, .17])
        stt = np.where(met, "VISITED_MET", miss)
        dmet = np.where(ptp[rep], "PTP", rng.choice(["REFUSED_TO_PAY", "FINANCIAL_DIFFICULTY", "PARTIAL_COMMITMENT", "VEHICLE_INSPECTED"], len(rep), p=[.3, .35, .25, .1]))
        disp = np.where(met, dmet, np.where(stt == "CUSTOMER_SHIFTED", "SKIP_TRACE_REQUIRED", "REVISIT_PLANNED"))
        ag = fld_id[rep]
        agent = np.array([f"{a}-F{x:03d}" for a, x in zip(ag, rng.integers(1, 30, len(rep)))])
        evs.append(pd.DataFrame(dict(account_id=acc_id[rep], lender_id=lender[rep], event_timestamp=stamps(rep, start_day[rep], 10, 18),
                   channel="FIELD_VISIT", agency_id=ag, agent_id=agent, attempt_status=stt, disposition_code=disp)))
    # legal notices for 90+
    lg = ci[(bk[ci] == 4) & (rng.random(len(ci)) < .35)]
    if len(lg):
        evs.append(pd.DataFrame(dict(account_id=acc_id[lg], lender_id=lender[lg], event_timestamp=stamps(lg, np.full(len(lg), 1), 10, 17),
                   channel="LEGAL_NOTICE", agency_id=np.array([f"LGL_{RC[g]}_01" for g in reg[lg]]), agent_id=None,
                   attempt_status="NOTICE_DISPATCHED", disposition_code=rng.choice(["SEC_138_NOTICE", "ARBITRATION_NOTICE", "PRE_LITIGATION_NOTICE"], len(lg)))))
    # payments
    pay = ci[np.isin(outcome[ci], ["RESOLVED", "CURE", "BACK", "STAY_PAID"]) | settle[ci]]
    if len(pay):
        mm = m0[pay]
        amt = np.select([outcome[pay] == "RESOLVED", outcome[pay] == "CURE", settle[pay]],
                        [emi[pay] + 590, np.round(mm * emi[pay] * 1.02), np.round(.55 * pos_open[pay])], emi[pay])
        mode = np.where(nach[pay] == "SUCCESS", "NACH_REPRESENTATION",
               np.where(field_met[pay] & (rng.random(len(pay)) < .45), "CASH_FIELD",
               rng.choice(["UPI_PAYMENT_LINK", "UPI_PAYMENT_LINK", "NEFT_IMPS", "BRANCH_DEPOSIT", "UPI_AUTOPAY"], len(pay))))
        mode = np.where((mode == "UPI_AUTOPAY") & (lender[pay] != "LENDER_B"), "UPI_PAYMENT_LINK", mode)
        ts = stamps(pay, np.maximum(start_day[pay], 3))
        if t == OUTAGE_T:   # payments that succeeded after gateway outage ended
            o = (lender[pay] == "LENDER_A") & (mode == "UPI_PAYMENT_LINK")
            ts = pd.Series(ts); ts[o] = ts[o].apply(lambda x: x.replace(day=min(max(x.day, 28), dim)))
        evs.append(pd.DataFrame(dict(account_id=acc_id[pay], lender_id=lender[pay], event_timestamp=ts,
                   channel=np.where(mode == "CASH_FIELD", "FIELD_COLLECTION", "PAYMENT"), agency_id=np.where(mode == "CASH_FIELD", fld_id[pay], None),
                   agent_id=None, attempt_status="COMPLETED", disposition_code=np.where(settle[pay], "SETTLEMENT_PAYMENT", "PAYMENT_RECEIVED"),
                   payment_mode=mode, payment_status="SUCCESS", payment_amount=amt, failure_reason=None)))
    # failed payment attempts (baseline ~3%, Lender A outage window, Lender C tech issue)
    fp = ci[rng.random(len(ci)) < .03]
    fr = rng.choice(["BANK_DECLINE", "GATEWAY_TIMEOUT", "INSUFFICIENT_BALANCE"], len(fp), p=[.4, .25, .35])
    fps = [(fp, fr, None)]
    if t == OUTAGE_T:
        oa = ci[(lender[ci] == "LENDER_A") & (bk[ci] <= 1) & (rng.random(len(ci)) < .38)]
        oa = np.repeat(oa, rng.integers(1, 4, len(oa)))
        fps.append((oa, np.full(len(oa), "GATEWAY_TIMEOUT"), (18, 27)))
    for rows, frs, win in fps:
        if not len(rows): continue
        ts = stamps(rows, start_day[rows])
        if win:
            ts = pd.Series(ts).apply(lambda x: x.replace(day=int(rng.integers(win[0], win[1] + 1))))
        evs.append(pd.DataFrame(dict(account_id=acc_id[rows], lender_id=lender[rows], event_timestamp=ts, channel="PAYMENT",
                   agency_id=None, agent_id=None, attempt_status="ATTEMPTED", disposition_code="PAYMENT_FAILED",
                   payment_mode="UPI_PAYMENT_LINK", payment_status="FAILED", payment_amount=np.round(emi[rows]), failure_reason=frs)))
    ev = pd.concat(evs, ignore_index=True)
    ev = ev.sort_values("event_timestamp").reset_index(drop=True)
    ev.insert(0, "event_id", [f"EV{month.strftime('%y%m')}{i:07d}" for i in range(len(ev))])
    for c in ["call_duration_sec", "ptp_amount", "ptp_date", "payment_mode", "payment_status", "payment_amount", "failure_reason", "agent_id", "agency_id"]:
        if c not in ev: ev[c] = None
    ev["month_date"] = month.date()
    ev = ev[["event_id","account_id","lender_id","month_date","event_timestamp","channel","agency_id","agent_id",
             "attempt_status","disposition_code","call_duration_sec","ptp_amount","ptp_date",
             "payment_mode","payment_status","payment_amount","failure_reason"]]
    ev["call_duration_sec"] = pd.to_numeric(ev.call_duration_sec).astype("Int64")
    ev["ptp_amount"] = pd.to_numeric(ev.ptp_amount); ev["payment_amount"] = pd.to_numeric(ev.payment_amount)
    ev["ptp_date"] = pd.to_datetime(ev.ptp_date).dt.date
    for c in ["agency_id","agent_id","payment_mode","payment_status","failure_reason"]: ev[c] = ev[c].astype(object).where(ev[c].notna(), None)
    ev.to_parquet(f"/home/claude/tmp/d3_{month.strftime('%Y%m')}.parquet", index=False)
    print(month.date(), "accounts", n, "d1", n_d1, "d3", len(ev), flush=True)
    del ev, evs

# ---------------------------------------------------------------- dims
dim_geo.drop(columns=["city_weight"]).to_parquet("/home/claude/tmp/dim_geography.parquet", index=False)
dim_agency.to_parquet("/home/claude/tmp/dim_agency.parquet", index=False)
print("DONE")
