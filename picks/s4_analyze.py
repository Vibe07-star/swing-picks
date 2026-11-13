"""STEP 4 — all quantitative checks for the shortlist -> master.json + printed tables.
Usage: python3 s4_analyze.py WORKDIR [capital_in_rupees=1000000]"""
import json, glob, os, re, sys, warnings
from xml.etree import ElementTree as ET
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
W = sys.argv[1]; CAP = float(sys.argv[2]) if len(sys.argv) > 2 else 1_000_000
os.chdir(W); IST = "Asia/Kolkata"; pd.set_option("display.width", 260); pd.set_option("display.max_columns", 60)
SL = pd.read_csv("shortlist.csv"); S = list(SL.symbol); REG = json.load(open("regime.json"))
fn = lambda s: s.replace("&", "_")
def jload(p, default=None):
    try: return json.load(open(p))
    except Exception: return default
def num(x):
    try: return float(str(x).replace(",", ""))
    except Exception: return None

# ---------------- A. technicals + trade plan ----------------
def load_px(path):
    r = json.load(open(path))["chart"]["result"][0]; q = r["indicators"]["quote"][0]
    idx = pd.to_datetime(r["timestamp"], unit="s").tz_localize("UTC").tz_convert(IST).normalize().tz_localize(None)
    df = pd.DataFrame({k: q[k] for k in ["open", "high", "low", "close", "volume"]}, index=idx).dropna(subset=["close"])
    return df[~df.index.duplicated(keep="last")], r["meta"]
def ind(df):
    c, h, l = df.close, df.high, df.low
    df["sma20"], df["sma50"], df["sma200"] = c.rolling(20).mean(), c.rolling(50).mean(), c.rolling(200).mean()
    d = c.diff(); au = d.clip(lower=0).ewm(alpha=1/14, adjust=False).mean(); ad = (-d.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    df["rsi"] = 100 - 100/(1 + au/ad)
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1/14, adjust=False).mean(); df["low10"] = l.rolling(10).min(); df["hi252"] = h.rolling(252, min_periods=150).max()
    return df
def rnd(x, p): step = 5 if p > 2000 else (1 if p > 300 else 0.5); return float(round(round(x/step)*step, 2))
def plan(r, p):
    a, s20 = r.atr, r.sma20; stretched = (r.rsi > 70) or ((p - s20)/s20 > 0.06)
    lo, hi = (max(s20, p-2*a), p-a) if stretched else (p-0.75*a, p)
    em = (lo+hi)/2; stop = min(max(r.low10-0.25*a, em-2.5*a), em-1.5*a); R = em-stop
    return dict(style="Buy on dip" if stretched else "Near CMP", lo=lo, hi=min(hi, p), em=em, stop=stop, t1=em+2*R, t2=em+3*R, R=R)
nifty, nmeta = load_px("px/_NSEI.json")
NOW = pd.Timestamp.now(tz=IST); TODAY = NOW.normalize().tz_localize(None)          # calendar date (events)
CUT = TODAY + (pd.Timedelta(days=1) if NOW.hour >= 16 else pd.Timedelta(0))            # bars before CUT are completed sessions
n_done = nifty[nifty.index < CUT].close
T, RET = {}, {}
for s in S:
    df, meta = load_px(f"px/{fn(s)}.json"); live = meta["regularMarketPrice"]
    d = ind(df[df.index < CUT].copy()); r = d.iloc[-1]; p = plan(r, live)
    RET[s] = d.close.pct_change().tail(250)
    T[s] = dict(live=live, prev_close=round(d.close.iloc[-1], 2), day_chg=round((live/d.close.iloc[-1]-1)*100, 2),
        sma20=round(r.sma20, 1), sma50=round(r.sma50, 1), sma200=round(r.sma200, 1), golden=bool(r.sma50 > r.sma200), rsi=round(r.rsi, 1),
        atr_pct=round(r.atr/live*100, 1), ext20=round((live/r.sma20-1)*100, 1), from_hi52=round((live/r.hi252-1)*100, 1),
        trend="UP" if live > r.sma50 > r.sma200 else ("DOWN" if live < r.sma50 < r.sma200 else "MIXED"), style=p["style"],
        buy_lo=rnd(p["lo"], live), buy_hi=rnd(p["hi"], live), stop=rnd(p["stop"], live), t1=rnd(p["t1"], live), t2=rnd(p["t2"], live),
        risk_pct=round(p["R"]/p["em"]*100, 1))
    em = (T[s]["buy_lo"] + T[s]["buy_hi"])/2; rps = em - T[s]["stop"]
    T[s]["qty"] = min(int(CAP*REG["risk_per_trade_pct"]/100/rps), int(0.25*CAP/em)) if rps > 0 else 0   # risk-based, capped at 25% of capital
    T[s]["position_value"] = round(T[s]["qty"]*em)
    T[s]["rr_t1"] = round((T[s]["t1"]-em)/rps, 2) if rps > 0 else None
NRET = n_done.pct_change().tail(250)

# ---------------- B. F&O ----------------
FO = {}
fo_files = sorted(glob.glob("fo/BhavCopy_NSE_FO_0_0_0_*_F_0000.csv"))[-4:]
eod = []
for f in fo_files:
    x = pd.read_csv(f, usecols=["TradDt", "FinInstrmTp", "TckrSymb", "XpryDt", "ClsPric", "OpnIntrst"]); eod.append(x[x.TckrSymb.isin(S) & (x.FinInstrmTp == "STF")])
eod = pd.concat(eod) if eod else pd.DataFrame()
sp = jload("nse/spurts.json", {}); spd = pd.DataFrame(sp.get("data", []))
if len(spd): spd = spd.set_index("symbol"); spd["chg"] = spd.changeInOI/spd.prevOI*100; spd["pct"] = spd.chg.rank(pct=True)*100
mw = None
mf = glob.glob("fo/mwpl/*.csv")
if mf:
    mw = pd.read_csv(mf[0], skipinitialspace=True); mw.columns = [c.strip() for c in mw.columns]
    mw = mw.set_index("NSE Symbol"); mw["pct"] = mw["Future Equivalent Open Interest"]/mw["MWPL"]*100
def tag(dp, doi): return ("Long build-up" if doi > 0 else "Short covering") if dp > 0 else ("Short build-up" if doi > 0 else "Long unwinding")
def chain(path):
    j = jload(path, {}); rec = j.get("records", {}); rows = []
    for r in rec.get("data", []):
        ce, pe = r.get("CE") or {}, r.get("PE") or {}
        k = r.get("strikePrice") or ce.get("strikePrice") or pe.get("strikePrice")
        rows.append(dict(k=k, ceOI=ce.get("openInterest", 0), ceChg=ce.get("changeinOpenInterest", 0), ceIV=ce.get("impliedVolatility", 0), ceLTP=ce.get("lastPrice", 0),
                         peOI=pe.get("openInterest", 0), peChg=pe.get("changeinOpenInterest", 0), peIV=pe.get("impliedVolatility", 0), peLTP=pe.get("lastPrice", 0)))
    df = pd.DataFrame(rows)
    if df.empty: return None, None, None
    return df[df.k > 0], rec.get("underlyingValue"), rec.get("timestamp")
for s in S:
    if not os.path.exists(f"nse/oc/{s}_m.json"): FO[s] = dict(in_fo=False); continue
    rec = dict(in_fo=True)
    if len(eod):
        g = eod[eod.TckrSymb == s]; days = sorted(g.TradDt.unique()); seq = []
        for a, b in zip(days[:-1], days[1:]):
            ga, gb = g[g.TradDt == a], g[g.TradDt == b]
            common = sorted(set(ga.XpryDt) & set(gb.XpryDt))                # same contracts only -> expiry rollover can't distort
            if not common: continue
            near = common[0]; dp = gb[gb.XpryDt == near].ClsPric.iloc[0]/ga[ga.XpryDt == near].ClsPric.iloc[0]-1
            doi = gb[gb.XpryDt.isin(common)].OpnIntrst.sum()/ga[ga.XpryDt.isin(common)].OpnIntrst.sum()-1
            seq.append(f"{b[5:]}: {tag(dp, doi)} (px {dp*100:+.1f}%, OI {doi*100:+.1f}%)")
        rec["eod"] = " | ".join(seq[-3:])
    if len(spd) and s in spd.index:
        rec["live_oi_chg"] = round(spd.loc[s, "chg"], 1); rec["live_oi_pctile"] = round(spd.loc[s, "pct"]); rec["today"] = tag(T[s]["day_chg"], spd.loc[s, "chg"])
    ch, und, ts = chain(f"nse/oc/{s}_m.json")
    if ch is not None and und:
        a = ch.iloc[(ch.k-und).abs().argsort()[:1]].iloc[0]
        rec.update(pcr=round(ch.peOI.sum()/max(ch.ceOI.sum(), 1), 2), max_call_oi=ch.loc[ch.ceOI.idxmax(), "k"], max_put_oi=ch.loc[ch.peOI.idxmax(), "k"],
                   ce_added=int(ch.ceChg.sum()), pe_added=int(ch.peChg.sum()), atm_iv=round((a.ceIV+a.peIV)/2, 1),
                   straddle_move_pct=round((a.ceLTP+a.peLTP)/und*100, 1), chain_time=ts)
    if mw is not None and s in mw.index: rec["mwpl_pct"] = round(mw.loc[s, "pct"], 1); rec["ban_risk"] = bool(mw.loc[s, "pct"] >= 80)
    FO[s] = rec
MKT = dict(regime=REG)
for nm in ["w", "m"]:
    ch, und, ts = chain(f"nse/oc/NIFTY_{nm}.json")
    if ch is not None: MKT[f"nifty_{nm}"] = dict(spot=und, time=ts, pcr=round(ch.peOI.sum()/ch.ceOI.sum(), 2), max_call=ch.loc[ch.ceOI.idxmax(), "k"], max_put=ch.loc[ch.peOI.idxmax(), "k"])
parts = sorted(glob.glob("fo/part_*.csv"), key=lambda p: pd.to_datetime(p[-12:-4], format="%d%m%Y"))
MKT["fii_participant"] = []
for p in parts[-3:]:
    try:
        x = pd.read_csv(p, skiprows=1); x.columns = [c.strip() for c in x.columns]; f = x[x["Client Type"].str.strip() == "FII"].iloc[0]
        MKT["fii_participant"].append(dict(date=p[-12:-4], index_fut_long_pct=round(f["Future Index Long"]/(f["Future Index Long"]+f["Future Index Short"])*100, 1),
                                           stock_fut_long_pct=round(f["Future Stock Long"]/(f["Future Stock Long"]+f["Future Stock Short"])*100, 1)))
    except Exception: pass
MKT["fii_dii_cash"] = jload("nse/fiidii.json", [])
ai = jload("nse/allIndices.json", {})
MKT["indices"] = {d["index"]: (d["last"], d["percentChange"]) for d in ai.get("data", []) if d["index"] in ("NIFTY 50", "NIFTY BANK", "INDIA VIX", "NIFTY MIDCAP 100", "NIFTY SMALLCAP 100", "NIFTY IT", "NIFTY PHARMA", "NIFTY AUTO", "NIFTY FMCG", "NIFTY METAL", "NIFTY REALTY", "NIFTY PSU BANK")}

# ---------------- C. delivery (NSE bhavcopy) ----------------
fr = []
for f in sorted(glob.glob("bhav/*.csv")):
    try: d = pd.read_csv(f, skipinitialspace=True); d.columns = [c.strip() for c in d.columns]
    except Exception: continue
    if "SYMBOL" not in d.columns: continue
    fr.append(d[(d.SERIES.str.strip() == "EQ") & d.SYMBOL.isin(S)])
b = pd.concat(fr)
for c in ["DELIV_PER", "DELIV_QTY", "CLOSE_PRICE", "PREV_CLOSE", "TTL_TRD_QNTY"]: b[c] = pd.to_numeric(b[c], errors="coerce")
b["DATE"] = pd.to_datetime(b.DATE1.str.strip(), format="%d-%b-%Y"); b["chg"] = b.CLOSE_PRICE/b.PREV_CLOSE-1
DL = {}
for s, g in b.sort_values("DATE").groupby("SYMBOL"):
    up, dn = g[g.chg > 0], g[g.chg < 0]
    DL[s] = dict(date=str(g.DATE.iloc[-1].date()), deliv_last=g.DELIV_PER.iloc[-1], deliv_avg=round(g.DELIV_PER.mean(), 1),
                 vol_x=round(g.TTL_TRD_QNTY.iloc[-1]/g.TTL_TRD_QNTY.iloc[-21:-1].mean(), 2), updown_deliv=round(up.DELIV_QTY.sum()/max(dn.DELIV_QTY.sum(), 1), 2))

# ---------------- D. shareholding (NSE SHP XBRL) + pledge + SAST + bulk/block ----------------
def shp(path):
    x = open(path, errors="ignore").read()
    pct = dict(re.findall(r'ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="([^"]+)"[^>]*>([\d.]+)<', x))
    nos = dict(re.findall(r'NumberOfShares contextRef="([^"]+)"[^>]*>(\d+)<', x))
    g = lambda k: num(pct.get(k))
    tot = max((int(v) for k, v in nos.items() if k.endswith("_ContextI")), default=None)
    return dict(promoter=g("ShareholdingOfPromoterAndPromoterGroup_ContextI"), fii=g("InstitutionsForeign_ContextI"), dii=g("InstitutionsDomestic_ContextI"),
                promoter_shares=num(nos.get("ShareholdingOfPromoterAndPromoterGroup_ContextI")), total_shares=tot)
SH = {}
for s in S:
    fs = sorted(glob.glob(f"nse/shp/{s}_*.xml"), key=lambda p: pd.to_datetime(re.search(r"_(\d{2}-[A-Z]{3}-\d{4})\.xml", p).group(1), format="%d-%b-%Y"))
    rec = {}
    if len(fs) >= 1:
        cur = shp(fs[-1]); rec.update({k: (round(v*100, 2) if k in ("promoter", "fii", "dii") and v is not None else v) for k, v in cur.items()}); rec["as_of"] = fs[-1][-15:-4]
        if len(fs) >= 2:
            prv = shp(fs[-2])
            for k in ("promoter", "fii", "dii"):
                if cur[k] is not None and prv[k] is not None: rec[k + "_chg"] = round((cur[k]-prv[k])*100, 2)
            if cur["promoter_shares"] and prv["promoter_shares"]:
                ds = cur["promoter_shares"]-prv["promoter_shares"]
                rec["promoter_action"] = "SOLD" if ds < 0 else ("BOUGHT" if ds > 0 else ("diluted (no sale)" if (cur["total_shares"] or 0) > (prv["total_shares"] or 0) else "unchanged"))
                rec["promoter_shares_chg"] = int(ds)
    html = open(f"scr/{s}.html", errors="ignore").read() if os.path.exists(f"scr/{s}.html") else ""
    m = re.search(r"pledged ([\d.]+)%", html); rec["pledge"] = m.group(1)+"%" if m else "none disclosed"
    sa = jload(f"nse/sast/{s}.json", {}) or {}
    rec["sast"] = [f'{r.get("acquirerDate")} {r.get("acqSaleType")} {str(r.get("acquirerName"))[:40]}' for r in sa.get("data", [])][:6]
    deals = []
    for t in ("bulk_deals", "block_deals"):
        for r in (jload(f"nse/deals/{s}_{t}.json", {}) or {}).get("data", []):
            if r.get("BD_SYMBOL") == s: deals.append(f'{t[:5]} {r["BD_DT_DATE"]} {r["BD_BUY_SELL"]} {r["BD_QTY_TRD"]:,} @{r["BD_TP_WATP"]} {r["BD_CLIENT_NAME"][:35]}')
    rec["deals"] = deals[:10]
    SH[s] = rec

# ---------------- E. results + cash flow (NSE consolidated XBRL) ----------------
X = "{http://www.xbrl.org/2003/instance}"
TAGS = ["RevenueFromOperations", "OtherIncome", "FinanceCosts", "DepreciationDepletionAndAmortisationExpense", "ExceptionalItemsBeforeTax", "ProfitBeforeTax",
        "ProfitLossForPeriod", "ProfitOrLossAttributableToOwnersOfParent", "ProfitOrLossAttributableToNonControllingInterests",
        "CashFlowsFromUsedInOperatingActivities", "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
        "TradeReceivablesCurrent", "TradeReceivablesNoncurrent", "Inventories", "CashAndCashEquivalents", "BankBalanceOtherThanCashAndCashEquivalents",
        "CurrentInvestments", "BorrowingsCurrent", "BorrowingsNoncurrent", "Equity"]
# banks file the SEBI "IFBanking" taxonomy: map to the common names + keep bank-only lines
BANKMAP = {"InterestEarned": "RevenueFromOperations", "ProfitLossForThePeriod": "ProfitLossForPeriod",
           "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates": "ProfitOrLossAttributableToOwnersOfParent",
           "ProfitLossOfMinorityInterest": "ProfitOrLossAttributableToNonControllingInterests", "ProfitLossFromOrdinaryActivitiesBeforeTax": "ProfitBeforeTax"}
BANKX = ["InterestExpended", "OperatingProfitBeforeProvisionAndContingencies", "ProvisionsOtherThanTaxAndContingencies", "PercentageOfGrossNpa", "PercentageOfNpa"]
FLOW = TAGS[:9] + ["InterestExpended", "OperatingProfitBeforeProvisionAndContingencies", "ProvisionsOtherThanTaxAndContingencies"]
def parse_x(path):
    try: root = ET.parse(path).getroot()
    except Exception: return {}
    ctx = {}
    for c in root.iter(X + "context"):
        sc = c.find(X + "scenario")
        if sc is not None and len(list(sc)): continue
        p = c.find(X + "period"); sd, ed, ins = p.find(X + "startDate"), p.find(X + "endDate"), p.find(X + "instant")
        ctx[c.get("id")] = (sd.text, ed.text) if sd is not None else ("I", ins.text)
    out = {}
    for el in root:
        t = el.tag.split("}")[-1]; t = BANKMAP.get(t, t)
        if (t in TAGS or t in BANKX) and el.get("contextRef") in ctx:
            v = num(el.text)
            if v is not None: out.setdefault(ctx[el.get("contextRef")], {}).setdefault(t, v)
    return out
def owners(d):
    if not d: return None
    pl, nci, own = d.get("ProfitLossForPeriod"), d.get("ProfitOrLossAttributableToNonControllingInterests") or 0, d.get("ProfitOrLossAttributableToOwnersOfParent")
    if pl is None: return own
    der = pl - nci
    return der if (own is None or own == 0 or abs(own-der) > max(1e7, 0.02*abs(der))) else own
def ebitda(d):
    if not d or d.get("ProfitBeforeTax") is None: return None
    return d["ProfitBeforeTax"]+d.get("FinanceCosts", 0)+d.get("DepreciationDepletionAndAmortisationExpense", 0)-d.get("OtherIncome", 0)-d.get("ExceptionalItemsBeforeTax", 0)
cr = lambda v: None if v is None else round(v/1e7, 1)
npa = lambda v: None if not v else round(v*100 if v < 1 else v, 2)        # 0/blank in consolidated bank filings = not reported; fractions -> %
pct = lambda a, b: None if (a is None or not b) else round((a/b-1)*100, 1)
FU = {}
for s in S:
    P = {}
    SA = {}
    for f in glob.glob(f"xbrl/{s}_*_SA.xml"):
        for k, v in parse_x(f).items(): SA.setdefault(k, {}).update({kk: vv for kk, vv in v.items() if kk in ("PercentageOfGrossNpa", "PercentageOfNpa")})
    for f in [f for f in glob.glob(f"xbrl/{s}_*.xml") if not f.endswith("_SA.xml")]:
        for k, v in parse_x(f).items():
            P.setdefault(k, {}).update({kk: vv for kk, vv in v.items() if kk not in P.get(k, {})})
    q = {k: v for k, v in P.items() if k[0] != "I" and 80 <= (pd.Timestamp(k[1])-pd.Timestamp(k[0])).days <= 95}
    # derive missing quarters from H1/9M/FY minus earlier quarters (some filers tag only cumulative periods)
    for k, v in P.items():
        if k[0] == "I": continue
        st, en = pd.Timestamp(k[0]), pd.Timestamp(k[1]); qs = (en - pd.DateOffset(months=3) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        if (qs, k[1]) in q or (en-st).days < 150: continue
        prior = [q.get(kk) for kk in q if pd.Timestamp(kk[0]) >= st and pd.Timestamp(kk[1]) < en]
        if prior and sum(((pd.Timestamp(kk[1])-pd.Timestamp(kk[0])).days+1) for kk in q if pd.Timestamp(kk[0]) >= st and pd.Timestamp(kk[1]) < en) + 92 >= (en-st).days:
            d = {t: v[t]-sum(p.get(t, 0) for p in prior) for t in v if t in FLOW}
            d["ProfitOrLossAttributableToOwnersOfParent"] = owners(v)-sum(owners(p) or 0 for p in prior); d["ProfitOrLossAttributableToNonControllingInterests"] = 0
            d["ProfitLossForPeriod"] = d["ProfitOrLossAttributableToOwnersOfParent"]; d["_derived"] = True
            q[(qs, k[1])] = d
    if not q: FU[s] = dict(note="no XBRL"); continue
    lk = max(q, key=lambda k: k[1]); cur = q[lk]
    ly = q.get(((pd.Timestamp(lk[0])-pd.DateOffset(years=1)).strftime("%Y-%m-%d"), (pd.Timestamp(lk[1])-pd.DateOffset(years=1)).strftime("%Y-%m-%d")))
    pq = [k for k in q if k[1] < lk[0]]; pv = q[max(pq, key=lambda k: k[1])] if pq else None
    e, ely = ebitda(cur), ebitda(ly)
    rec = dict(quarter_end=lk[1], derived=bool(cur.get("_derived")), rev_cr=cr(cur.get("RevenueFromOperations")),
               rev_yoy=pct(cur.get("RevenueFromOperations"), (ly or {}).get("RevenueFromOperations")), rev_qoq=pct(cur.get("RevenueFromOperations"), (pv or {}).get("RevenueFromOperations")),
               ebitda_m=round(e/cur["RevenueFromOperations"]*100, 1) if e and cur.get("RevenueFromOperations") else None,
               ebitda_m_ly=round(ely/ly["RevenueFromOperations"]*100, 1) if ely and ly and ly.get("RevenueFromOperations") else None,
               pat_owner_cr=cr(owners(cur)), pat_yoy=pct(owners(cur), owners(ly)), pat_qoq=pct(owners(cur), owners(pv)),
               exceptional_cr=cr(cur.get("ExceptionalItemsBeforeTax")), other_inc_pct_pbt=round(cur.get("OtherIncome", 0)/cur["ProfitBeforeTax"]*100) if cur.get("ProfitBeforeTax") else None,
               minority_cr=cr(cur.get("ProfitOrLossAttributableToNonControllingInterests")))
    pl_ly = owners(ly) if ly else None
    rec["pat_low_base"] = bool(pl_ly is not None and (pl_ly <= 0 or (ly.get("RevenueFromOperations") and abs(pl_ly) < 0.02*ly["RevenueFromOperations"])))
    for kk in (lk, max(pq, key=lambda k: k[1]) if pq else None):                 # standalone NPA ratios fill gaps in consolidated
        if kk and kk in SA:
            for t_ in ("PercentageOfGrossNpa", "PercentageOfNpa"):
                if not q[kk].get(t_) and SA[kk].get(t_): q[kk][t_] = SA[kk][t_]
    if "InterestExpended" in cur:                                  # bank: NII, pre-provision profit, asset quality
        nii = lambda d: (d.get("RevenueFromOperations") or 0) - (d.get("InterestExpended") or 0) if d else None
        rec.update(bank=True, ebitda_m=None, ebitda_m_ly=None, nii_cr=cr(nii(cur)), nii_yoy=pct(nii(cur), nii(ly)),
                   ppop_yoy=pct(cur.get("OperatingProfitBeforeProvisionAndContingencies"), (ly or {}).get("OperatingProfitBeforeProvisionAndContingencies")),
                   provisions_yoy=pct(cur.get("ProvisionsOtherThanTaxAndContingencies"), (ly or {}).get("ProvisionsOtherThanTaxAndContingencies")),
                   gnpa_pct=npa(cur.get("PercentageOfGrossNpa")), nnpa_pct=npa(cur.get("PercentageOfNpa")), gnpa_pct_prev=npa((pv or {}).get("PercentageOfGrossNpa")))
    # cash flow: longest duration ending at latest period end (H1 / 9M / FY) that has CFO
    cf = [(k, v) for k, v in P.items() if k[0] != "I" and v.get("CashFlowsFromUsedInOperatingActivities") is not None]
    if cf:
        k, v = max(cf, key=lambda kv: (kv[0][1], (pd.Timestamp(kv[0][1])-pd.Timestamp(kv[0][0])).days))
        days = (pd.Timestamp(k[1])-pd.Timestamp(k[0])).days + 1; bal = P.get(("I", k[1]), {})
        cfo, pl, capex = v.get("CashFlowsFromUsedInOperatingActivities"), v.get("ProfitLossForPeriod"), v.get("PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities")
        rv = v.get("RevenueFromOperations"); rec_ = (bal.get("TradeReceivablesCurrent") or 0)+(bal.get("TradeReceivablesNoncurrent") or 0)
        cash = sum(bal.get(t) or 0 for t in ["CashAndCashEquivalents", "BankBalanceOtherThanCashAndCashEquivalents", "CurrentInvestments"])
        debt = (bal.get("BorrowingsCurrent") or 0)+(bal.get("BorrowingsNoncurrent") or 0)
        rec.update(cf_period=f"{k[0]}..{k[1]}", cfo_cr=cr(cfo), cfo_to_pat=round(cfo/pl, 2) if cfo and pl else None, capex_cr=cr(abs(capex)) if capex else None,
                   fcf_cr=cr(cfo-abs(capex)) if cfo is not None and capex is not None else None,
                   recv_days=round(rec_/rv*days) if rv and bal else None, net_debt_cr=cr(debt-cash) if bal else None,
                   debt_equity=round(debt/bal["Equity"], 2) if bal.get("Equity") else None)
        lyk = ((pd.Timestamp(k[0])-pd.DateOffset(years=1)).strftime("%Y-%m-%d"), (pd.Timestamp(k[1])-pd.DateOffset(years=1)).strftime("%Y-%m-%d"))
        lyv, lyb = P.get(lyk, {}), P.get(("I", lyk[1]), {})
        if lyv.get("RevenueFromOperations") and lyb:
            rec["recv_days_ly"] = round(((lyb.get("TradeReceivablesCurrent") or 0)+(lyb.get("TradeReceivablesNoncurrent") or 0))/lyv["RevenueFromOperations"]*days)
    FU[s] = rec

# ---------------- F. valuation + consensus + estimate revisions ----------------
from bs4 import BeautifulSoup
VA = {}
for s in S:
    rec = {}
    try:
        soup = BeautifulSoup(open(f"scr/{s}.html", errors="ignore").read(), "html.parser"); t = soup.find("section", id="profit-loss").find("table")
        hdr = [th.get_text(strip=True) for th in t.find("thead").find_all("th")][1:]
        eps = next([c.get_text(strip=True) for c in tr.find_all("td")][1:] for tr in t.find("tbody").find_all("tr") if tr.find("td").get_text(strip=True).startswith("EPS"))
        eps = {h: num(v) for h, v in zip(hdr, eps) if num(v) is not None}
        r = json.load(open(f"px10/{fn(s)}.json"))["chart"]["result"][0]
        mp = pd.Series(r["indicators"]["quote"][0]["close"], index=pd.to_datetime(r["timestamp"], unit="s").tz_localize("UTC").tz_convert(IST).tz_localize(None)).dropna()
        hist = {}
        for h, e in eps.items():
            mm = re.match(r"Mar (\d{4})", h)
            if mm and e > 0 and int(mm.group(1)) >= TODAY.year-8:
                sel = mp[(mp.index.year == int(mm.group(1))) & (mp.index.month == 3)]
                if len(sel): hist[int(mm.group(1))] = round(sel.iloc[-1]/e, 1)
        ttm = eps.get("TTM")
        if ttm and ttm > 0 and hist:
            med = float(np.median(list(hist.values()))); now = T[s]["live"]/ttm
            rec.update(pe_ttm=round(now, 1), pe_hist_median=round(med, 1), pe_vs_hist=round(now/med, 2), pe_hist=hist)
    except Exception as ex: rec["pe_err"] = str(ex)[:60]
    qs = jload(f"qs/{s}.json", {}) or {}
    try:
        R0 = qs["quoteSummary"]["result"][0]; fd, ks, sd = R0.get("financialData", {}), R0.get("defaultKeyStatistics", {}), R0.get("summaryDetail", {})
        g = lambda d, k: (d.get(k) or {}).get("raw") if isinstance(d.get(k), dict) else None
        med = g(fd, "targetMedianPrice")
        rec.update(n_analysts=g(fd, "numberOfAnalystOpinions"), target_median=med, price_vs_target=round((T[s]["live"]/med-1)*100, 1) if med else None,
                   fwd_pe=round(g(sd, "forwardPE") or g(ks, "forwardPE") or 0, 1) or None)
        tr = {t["period"]: t for t in R0.get("recommendationTrend", {}).get("trend", [])}
        f_ = lambda t: (t["strongBuy"]+t["buy"], t["hold"], t["sell"]+t["strongSell"]) if t else None
        rec["recs_now"], rec["recs_1m"] = f_(tr.get("0m")), f_(tr.get("-1m"))
        for t in R0.get("earningsTrend", {}).get("trend", []):
            if t["period"] in ("0y", "+1y"):
                et = t.get("epsTrend", {}); cur, d30, d90 = g(et, "current"), g(et, "30daysAgo"), g(et, "90daysAgo")
                er = t.get("epsRevisions", {})
                rec[f"eps_{t['period']}_rev30"] = round((cur/d30-1)*100, 1) if cur and d30 else None
                rec[f"eps_{t['period']}_rev90"] = round((cur/d90-1)*100, 1) if cur and d90 else None
                rec[f"eps_{t['period']}_up_down30"] = (g(er, "upLast30days"), g(er, "downLast30days"))
        hist = R0.get("earningsHistory", {}).get("history", [])
        rec["surprises_pct"] = [round(((h.get("surprisePercent") or {}).get("raw") or 0)*100, 1) for h in hist]
    except Exception: rec["consensus"] = "MISSING -> fetch via Firecrawl (see SKILL.md)"
    VA[s] = rec

# ---------------- G. events: next results, record dates, past results-day moves ----------------
EV = {}
for s in S:
    rec = {}
    bm = jload(f"nse/bm/{s}.json", []) or []
    fut = sorted({pd.to_datetime(r["bm_date"], format="%d-%b-%Y") for r in bm if "Result" in (r.get("bm_purpose") or "") + (r.get("bm_desc") or "")
                  and pd.to_datetime(r["bm_date"], format="%d-%b-%Y") >= TODAY})
    rec["next_results"] = str(fut[0].date()) if fut else None
    rec["results_in_trading_days"] = int(np.busday_count(TODAY.date(), fut[0].date())) if fut else None
    ca = jload(f"nse/ca/{s}.json", []) or []
    rec["upcoming_actions"] = [f'{r["exDate"]}: {r["subject"]}' for r in ca if r.get("exDate", "-") != "-" and pd.to_datetime(r["exDate"], format="%d-%b-%Y", errors="coerce") >= TODAY]
    dfp, _ = load_px(f"px/{fn(s)}.json"); dfp = dfp[dfp.index < CUT]; moves = []
    for r in (jload(f"nse/if/{s}.json", {}) or {}).get("data", []):
        if r.get("type") != "Integrated Filing- Financials" or not r.get("broadcast_Date"): continue
        t = pd.to_datetime(r["broadcast_Date"], format="%d-%b-%Y %H:%M:%S"); after = t.hour*60+t.minute >= 930
        sess = dfp.index[dfp.index > t.normalize()] if after else dfp.index[dfp.index >= t.normalize()]
        if len(sess) and dfp.index.get_loc(sess[0]) > 0:
            i = dfp.index.get_loc(sess[0]); moves.append((str(sess[0].date()), round((dfp.close.iloc[i]/dfp.close.iloc[i-1]-1)*100, 2)))
    moves = sorted(set(moves)); rec["past_results_moves"] = [m for _, m in moves][-8:]
    rec["median_abs_results_move"] = round(float(np.median([abs(m) for _, m in moves])), 2) if moves else None
    EV[s] = rec

# ---------------- H. portfolio: correlation, beta, vol ----------------
R = pd.DataFrame(RET).dropna(how="all"); corr = R.corr()
PF = {s: dict(beta=round(np.cov(R[s].dropna(), NRET.reindex(R[s].dropna().index).fillna(0))[0, 1]/NRET.var(), 2), vol=round(R[s].std()*np.sqrt(252)*100, 1),
              most_correlated=corr[s].drop(s).sort_values(ascending=False).head(2).round(2).to_dict()) for s in S}

# ---------------- I. announcements digest ----------------
AN = {}
skip = re.compile(r"Newspaper|Trading Window|Certificate under SEBI|Loss of Share|Duplicate|ESOP|Investor Presentation|Audio|Video|Schedule of meet", re.I)
red = re.compile(r"Resignation|Cessation|Auditor|USFDA|Form 483|Warning Letter|Import Alert|penalty|\bfine\b|SEBI order|Show Cause|Fraud|Default|Pledge|Qualified Institution|Preferential|Rights Issue|Search|Raid|Litigation|Regulation 29", re.I)
esop = re.compile(r"ESOP|ESOS|stock option", re.I)
for s in S:
    items = []
    for r in jload(f"nse/ann/{s}.json", []) or []:
        if skip.search(r["desc"]): continue
        txt = re.sub(r"\s+", " ", r["attchmntText"])[:180]
        items.append(("!! " if red.search(r["desc"]+" "+txt) and not esop.search(txt) else "") + f'{r["an_dt"][:11]} | {r["desc"][:35]} | {txt}')
    AN[s] = items[:25]

# ---------------- J. rule-based score (the model must still apply judgment, see SKILL.md) ----------------
VER = {}
for s in S:
    t, f, d, sh, fu, va, ev = T[s], FO.get(s, {}), DL.get(s, {}), SH.get(s, {}), FU.get(s, {}), VA.get(s, {}), EV.get(s, {})
    pos, neg, veto = [], [], []
    def chk(cond, lst, msg):
        if cond: lst.append(msg)
    chk(t["trend"] == "DOWN", veto, "trend down"); chk(f.get("ban_risk"), veto, "near F&O ban")
    chk(ev.get("results_in_trading_days") is not None and ev["results_in_trading_days"] <= 5, veto, f"results {ev.get('next_results')}")
    chk(sh.get("promoter_action") == "SOLD" and (sh.get("promoter_chg") or 0) <= -1, veto, f"promoter sold {sh.get('promoter_chg')} pts")
    fin = "Financial" in str(SL.set_index("symbol").industry.get(s, "")) or fu.get("bank")
    chk(not fin and fu.get("cfo_to_pat") is not None and fu["cfo_to_pat"] < 0.5 and (fu.get("pat_owner_cr") or 0) > 0, veto, f"cash conversion {fu.get('cfo_to_pat')}")
    chk(fu.get("bank") and fu.get("gnpa_pct") is not None and fu.get("gnpa_pct_prev") is not None and fu["gnpa_pct"] < fu["gnpa_pct_prev"], pos, "bad loans falling")
    chk(fu.get("bank") and fu.get("gnpa_pct") is not None and fu.get("gnpa_pct_prev") is not None and fu["gnpa_pct"] > fu["gnpa_pct_prev"] + 0.1, neg, "bad loans rising")
    chk((fu.get("pat_yoy") or 0) > 15 and not fu.get("pat_low_base"), pos, "profit growth"); chk(fu.get("pat_yoy") is not None and fu["pat_yoy"] < 0, neg, "profit falling")
    chk((fu.get("rev_yoy") or 0) > 10, pos, "revenue growth")
    chk(not fin and (fu.get("cfo_to_pat") or 0) >= 0.9, pos, "cash conversion ok"); chk((fu.get("net_debt_cr") or 0) < 0, pos, "net cash")
    chk(fu.get("recv_days") and fu.get("recv_days_ly") and fu["recv_days"] > fu["recv_days_ly"]*1.1, neg, "receivable days rising")
    rv = va.get("eps_+1y_rev30") if va.get("eps_+1y_rev30") is not None else va.get("eps_0y_rev30")
    chk(rv is not None and rv > 1, pos, f"EPS estimates up {rv}%"); chk(rv is not None and rv < -2, neg, f"EPS estimates cut {rv}%")
    sp_ = va.get("surprises_pct") or []; chk(len(sp_) >= 3 and all(x < 0 for x in sp_[-3:]), neg, "3+ EPS misses in a row")
    chk(va.get("price_vs_target") is not None and va["price_vs_target"] <= 0, pos, "below analyst target")
    chk(va.get("price_vs_target") is not None and va["price_vs_target"] > 10, neg, f"{va['price_vs_target'] if va.get('price_vs_target') else ''}% above analyst target")
    chk(va.get("pe_vs_hist") is not None and va["pe_vs_hist"] <= 1.2, pos, "P/E near/below own history"); chk((va.get("pe_vs_hist") or 0) > 1.5, neg, f"P/E {va.get('pe_vs_hist')}x own history")
    chk((sh.get("fii_chg") or 0) + (sh.get("dii_chg") or 0) > 0.5, pos, "institutions adding"); chk((sh.get("fii_chg") or 0) + (sh.get("dii_chg") or 0) < -0.5, neg, "institutions selling")
    chk((d.get("updown_deliv") or 0) >= 1.2, pos, "delivery heavier on up days"); chk(d.get("updown_deliv") is not None and d["updown_deliv"] < 0.9, neg, "delivery heavier on down days")
    chk((d.get("deliv_last") or 100) < 20 and (d.get("vol_x") or 0) > 3, neg, "speculative volume spike")
    chk(f.get("today") == "Long build-up", pos, "futures long build-up"); chk(f.get("today") == "Short build-up", neg, "futures short build-up")
    chk(50 <= t["rsi"] <= 70, pos, "RSI healthy"); chk(t["rsi"] > 75, neg, f"RSI {t['rsi']} overbought")
    chk(any(x.startswith("!!") for x in AN.get(s, [])), neg, "red-flag filing to read")
    score = len(pos)-len(neg)
    v = "AVOID" if veto and not any("results" in x for x in veto) else ("WAIT (results)" if veto else
        ("BUY" if score >= 4 else "BUY SMALL / HOLD" if score >= 2 else "WATCH" if score >= 0 else "AVOID"))
    VER[s] = dict(score=score, prelim=v, veto=veto, positives=pos, negatives=neg)

out = dict(shortlist_ind=dict(zip(SL.symbol, SL.industry)), snapshot=open("snapshot_time.txt").read().strip(), market=MKT, tech=T, fo=FO, delivery=DL, holding=SH, results=FU, valuation=VA,
           events=EV, portfolio=PF, announcements=AN, verdict=VER, shortlist=SL.to_dict("records"))
json.dump(out, open("master.json", "w"), indent=1, default=str)
# plan.json = input for the market-open check (s5). Edit "verdict" to the final call after the judgment layer.
json.dump(dict(prep_time=out["snapshot"], capital=CAP, risk_pct=REG["risk_per_trade_pct"], max_positions=REG["max_new_positions"],
               nifty_sma200=REG["sma200"], stocks={s: dict(verdict=VER[s]["prelim"], buy_lo=T[s]["buy_lo"], buy_hi=T[s]["buy_hi"], stop=T[s]["stop"],
               t1=T[s]["t1"], t2=T[s]["t2"], prev_close=T[s]["prev_close"], in_fo=FO[s].get("in_fo", False)) for s in S}),
          open("plan.json", "w"), indent=1)
print("SNAPSHOT", out["snapshot"]); print("MARKET", json.dumps(MKT, default=str)[:1500])
for name, tab in [("TECH", T), ("F&O", FO), ("DELIVERY", DL), ("RESULTS", FU), ("VALUATION", VA), ("EVENTS", EV), ("PORTFOLIO", PF)]:
    print(f"\n== {name}"); print(pd.DataFrame(tab).T.to_string())
print("\n== HOLDING"); print(pd.DataFrame({k: {kk: vv for kk, vv in v.items() if kk not in ("sast", "deals")} for k, v in SH.items()}).T.to_string())
for s in S:
    if SH[s].get("sast") or SH[s].get("deals"): print(s, "SAST:", SH[s]["sast"], "DEALS:", SH[s]["deals"])
print("\n== RED-FLAG FILINGS"); [print(s, x) for s in S for x in AN[s] if x.startswith("!!")]
print("\n== RULE SCORE"); print(pd.DataFrame(VER).T.to_string())
