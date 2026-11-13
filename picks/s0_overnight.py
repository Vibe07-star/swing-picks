"""STEP 0 — everything that happened between the LAST SESSION'S CLOSE (15:30 IST) and NOW.
Usage: python3 s0_overnight.py WORKDIR      (needs WORKDIR/px/_NSEI.json and lists/universe.csv from s1)
Writes WORKDIR/overnight.json and prints a digest. The model still does the web-news searches listed under "search_queries"."""
import json, os, re, subprocess, sys, tempfile, urllib.parse
import pandas as pd
W = sys.argv[1]; IST = "Asia/Kolkata"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
CK = os.path.join(tempfile.mkdtemp(), "ck.txt")
sh = lambda c: subprocess.run(c, shell=True, capture_output=True, text=True).stdout
def nse(api, ref="companies-listing/corporate-filings-announcements"):
    if not os.path.exists(CK): sh(f'curl -sS -A "{UA}" -c {CK} -o /dev/null https://www.nseindia.com/option-chain')
    try: return json.loads(sh(f'curl -sS -m 40 -A "{UA}" -b {CK} -H "Accept: application/json" -H "Referer: https://www.nseindia.com/{ref}" "https://www.nseindia.com/api/{api}"'))
    except Exception: return {}
def yahoo(sym, rng="5d", itv="15m"):
    try: return json.loads(sh(f'curl -sS -m 30 -A "{UA}" "https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range={rng}&interval={itv}"'))["chart"]["result"][0]
    except Exception: return None

# ---- window: last completed session close (15:30 IST) -> now ----
r = json.load(open(f"{W}/px/_NSEI.json"))["chart"]["result"][0]
idx = pd.to_datetime(r["timestamp"], unit="s").tz_localize("UTC").tz_convert(IST).normalize().tz_localize(None).unique()
NOW = pd.Timestamp.now(tz=IST); cut = NOW.normalize().tz_localize(None) + (pd.Timedelta(days=1) if NOW.hour >= 16 else pd.Timedelta(0))
last_sess = max(d for d in idx if d < cut)
START = (last_sess + pd.Timedelta(hours=15, minutes=30)).tz_localize(IST)
U = pd.read_csv(f"{W}/lists/universe.csv"); UNI = set(U.symbol); CAP = dict(zip(U.symbol, U.cap)); IND = dict(zip(U.symbol, U.industry))
out = dict(window=f"{START:%a %d %b %H:%M} IST → {NOW:%a %d %b %H:%M} IST", last_session=str(last_sess.date()))

# ---- 1. every NSE filing since the close, for the 500-stock universe ----
CATS = [("RESULTS", r"Financial Result|Outcome of Board Meeting.*(result|financial)|Integrated Filing.?Financial"),
        ("FUNDRAISE/DILUTION", r"Qualified Institution|QIP|preferential|rights issue|fund rais|warrant|allotment of (equity|warrant)|OFS|offer for sale|conversion of"),
        ("REGULATORY", r"USFDA|US FDA|Form 483|warning letter|import alert|\bEIR\b|inspection|SEBI order|show cause|adjudicat|penalty|\bfine\b|tax demand|GST (demand|notice)|search|raid|litigation|order of (the )?(hon|court|tribunal|NCLT|SAT|SEBI)"),
        ("GOVERNANCE", r"resignation|cessation|appointment of (CEO|CFO|MD|managing)|auditor|\bKMP\b"),
        ("ORDER/CONTRACT", r"\border(s)?\b|contract|bagging|award|letter of intent|\bLOI\b"),
        ("MINOR CORPORATE", r"incorporation of|wholly.owned subsidiary|step.down subsidiary|change in (name|address)|registered office"),
        ("M&A", r"acqui|merger|amalgamation|scheme of arrangement|joint venture|divest|stake (sale|purchase)"),
        ("CAPITAL RETURN", r"buyback|buy-back|dividend|bonus|split|sub-division"),
        ("RATING", r"credit rating"),
        ("PLEDGE/PROMOTER", r"pledge|encumbrance|Regulation 29|\bSAST\b")]
NOISE = re.compile(r"Trading Window|Newspaper|Loss of Share|Duplicate|Certificate under|ESOP|ESOS|Analysts?/Institutional Investor Meet|Investor Presentation|Audio|Video|Transcript|Schedule of", re.I)
frm, to = START.strftime("%d-%m-%Y"), NOW.strftime("%d-%m-%Y")
ann = nse(f"corporate-announcements?index=equities&from_date={frm}&to_date={to}")
ann = ann if isinstance(ann, list) else ann.get("data", []) if isinstance(ann, dict) else []
fil = []
for a in ann:
    s = a.get("symbol"); t = pd.to_datetime(a.get("an_dt"), format="%d-%b-%Y %H:%M:%S", errors="coerce")
    if s not in UNI or t is pd.NaT or t.tz_localize(IST) <= START: continue
    txt = f'{a.get("desc","")} {a.get("attchmntText","")}'
    if NOISE.search(a.get("desc", "")): continue
    cat = next((c for c, rx in CATS if re.search(rx, txt, re.I)), None)
    if not cat: continue
    fil.append(dict(symbol=s, cap=CAP.get(s), industry=IND.get(s), time=str(t), cat=cat, desc=a.get("desc", "")[:60],
                    text=re.sub(r"\s+", " ", a.get("attchmntText", ""))[:220], pdf=a.get("attchmntFile", "")))
out["filings_scanned"] = len(ann); out["filings"] = sorted(fil, key=lambda x: (x["cat"] != "RESULTS", x["symbol"]))
out["catalyst_symbols"] = sorted({f["symbol"] for f in fil if f["cat"] in ("RESULTS", "ORDER/CONTRACT", "M&A", "CAPITAL RETURN")})
out["risk_symbols"] = sorted({f["symbol"] for f in fil if f["cat"] in ("REGULATORY", "GOVERNANCE", "FUNDRAISE/DILUTION", "PLEDGE/PROMOTER")})

# ---- 2. bulk/block deals in the last session (universe only) ----
dd = last_sess.strftime("%d-%m-%Y"); deals = []
for t in ("bulk_deals", "block_deals"):
    j = nse(f"historicalOR/bulk-block-short-deals?optionType={t}&from={dd}&to={dd}", "report-detail/display-bulk-and-block-deals")
    for x in (j.get("data", []) if isinstance(j, dict) else []):
        if x.get("BD_SYMBOL") in UNI:
            deals.append(dict(type=t[:5], symbol=x["BD_SYMBOL"], side=x["BD_BUY_SELL"], qty=x["BD_QTY_TRD"], price=x["BD_TP_WATP"], client=str(x["BD_CLIENT_NAME"])[:40]))
out["deals"] = [dict(t) for t in {tuple(sorted(d.items())) for d in deals}]

# ---- 3. results due today / next session (universe) ----
ev = nse("event-calendar?index=equities", "companies-listing/corporate-filings-event-calendar")
ev = ev if isinstance(ev, list) else []
soon = []
for e in ev:
    d = pd.to_datetime(e.get("date"), format="%d-%b-%Y", errors="coerce")
    if e.get("symbol") in UNI and d is not pd.NaT and 0 <= (d - NOW.normalize().tz_localize(None)).days <= 3:
        soon.append(dict(symbol=e["symbol"], date=str(d.date()), purpose=str(e.get("purpose", ""))[:50]))
out["results_next_3d"] = sorted({(e["symbol"], e["date"]): e for e in soon}.values(), key=lambda x: x["date"])

# ---- 4. global markets: move SINCE India's close (not just the last daily bar) ----
GL = [("S&P 500", "^GSPC"), ("Nasdaq", "^IXIC"), ("Dow", "^DJI"), ("S&P fut", "ES=F"), ("Nasdaq fut", "NQ=F"), ("US VIX", "^VIX"),
      ("Euro Stoxx 50", "^STOXX50E"), ("DAX", "^GDAXI"), ("FTSE", "^FTSE"), ("Nikkei", "^N225"), ("Hang Seng", "^HSI"), ("Kospi", "^KS11"),
      ("Shanghai", "000001.SS"), ("Brent", "BZ=F"), ("Gold", "GC=F"), ("Dollar idx", "DX-Y.NYB"), ("USD/INR", "INR=X"), ("US 10Y", "^TNX")]
g = {}
for name, sym in GL:
    y = yahoo(sym)
    if not y or not y.get("timestamp"): continue
    s = pd.Series(y["indicators"]["quote"][0]["close"], index=pd.to_datetime(y["timestamp"], unit="s", utc=True)).dropna()
    before = s[s.index <= START.tz_convert("UTC")]
    base = before.iloc[-1] if len(before) else s.iloc[0]; last = y["meta"].get("regularMarketPrice") or s.iloc[-1]
    g[name] = dict(last=round(last, 2), since_india_close_pct=round((last/base-1)*100, 2), as_of=str(s.index[-1].tz_convert(IST))[:16])
out["global_since_close"] = g

# ---- 5. flows & positioning from the last session ----
fd = nse("fiidiiTradeReact", ""); out["fii_dii_cash"] = fd if isinstance(fd, list) else []
p = sh(f'curl -sS -A "{UA}" "https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{last_sess:%d%m%Y}.csv"')
try:
    from io import StringIO
    x = pd.read_csv(StringIO(p), skiprows=1); x.columns = [c.strip() for c in x.columns]; f = x[x["Client Type"].str.strip() == "FII"].iloc[0]
    out["fii_index_fut_long_pct"] = round(f["Future Index Long"]/(f["Future Index Long"] + f["Future Index Short"])*100, 1)
except Exception: out["fii_index_fut_long_pct"] = None

# ---- 6. web-news checklist for the model (window-bounded queries) ----
d0, d1 = last_sess.strftime("%d %B %Y"), NOW.strftime("%d %B %Y")
out["search_queries"] = [f"Wall Street close {d0}", f"US stock market news {d1}", f"GIFT Nifty today {d1}", f"Asian markets today {d1}",
    f"European markets close {d0}", f"crude oil price news {d1}", f"Fed ECB BoJ central bank news {d1}", f"US economic data released {d0}",
    f"geopolitical news markets {d1}", f"India stock market news {d1} pre-market", f"stocks to watch {d1} India",
    f"Q2 results after market hours {d0} India", f"RBI SEBI government policy announcement {d1}", f"FII DII data {d0}",
    f"India macro data {d0} inflation PMI IIP GDP"]
json.dump(out, open(f"{W}/overnight.json", "w"), indent=1, default=str)

print("WINDOW", out["window"], "| filings scanned", len(ann), "| material in universe", len(fil))
for f in out["filings"][:40]: print(f' {f["cat"]:<18} {f["symbol"]:<12} {f["time"][5:16]} {f["text"][:110]}')
print("CATALYSTS:", out["catalyst_symbols"]); print("RISK FLAGS:", out["risk_symbols"])
print("DEALS:", [f'{d["symbol"]} {d["side"]} {d["qty"]:,} @{d["price"]} {d["client"]}' for d in out["deals"]][:15])
print("RESULTS NEXT 3D:", [f'{e["symbol"]} {e["date"]}' for e in out["results_next_3d"]][:30])
print("GLOBAL since India close:", {k: f'{v["since_india_close_pct"]:+.2f}%' for k, v in g.items()})
print("FII idx-fut long %:", out["fii_index_fut_long_pct"], "| FII/DII cash:", [(r.get("category"), r.get("netValue")) for r in out["fii_dii_cash"]])
