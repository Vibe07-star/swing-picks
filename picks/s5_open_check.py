"""STEP 5 — market-open check (<1 min). Re-validates yesterday's/this morning's plan against pre-open or live prices.
Usage: python3 s5_open_check.py PLAN_JSON [only=SYM1,SYM2]
  before 09:00 IST  -> overnight check (global cues + new filings; prices = last close)
  09:00-09:15 IST   -> NSE pre-open indicative price (IEP, final at ~09:08)
  after 09:15 IST   -> live price, today's open/high/low, live futures OI, opening range (first 15 min), VWAP,
                       market read (indices, sectors, breadth) and "next opportunity" names from the plan's WATCH list
Only names that are IN ZONE *and* confirmed by the tape (above VWAP, holding the opening range, normal volume, calm market) are
flagged confident=True; the card shows full detail for those only.
PLAN_JSON: {"prep_time": "YYYY-MM-DD HH:MM:SS IST", "capital":..., "risk_pct":..., "max_positions":..., "nifty_sma200":...,
            "stocks": {SYM: {"verdict","buy_lo","buy_hi","stop","t1","t2","prev_close","in_fo"}}}"""
import json, re, sys, subprocess, tempfile, os, urllib.parse
import pandas as pd
P = json.load(open(sys.argv[1])); ONLY = sys.argv[2].split(",") if len(sys.argv) > 2 else None
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
IST = "Asia/Kolkata"; NOW = pd.Timestamp.now(tz=IST); hm = NOW.hour*60 + NOW.minute
MODE = "overnight" if hm < 540 else ("pre-open" if hm < 555 else "live")
TMP = tempfile.mkdtemp(); CK = f"{TMP}/ck.txt"
def sh(cmd): return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout
def nse(api, ref=""):
    if not os.path.exists(CK): sh(f'curl -sS -A "{UA}" -c {CK} -o /dev/null https://www.nseindia.com/option-chain')
    try: return json.loads(sh(f'curl -sS -A "{UA}" -b {CK} -H "Accept: application/json" -H "Referer: https://www.nseindia.com/{ref}" "https://www.nseindia.com/api/{api}"'))
    except Exception: return {}
def yq(sym, rng="1d", itv="1m"):
    try: return json.loads(sh(f'curl -sS -A "{UA}" "https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range={rng}&interval={itv}"'))["chart"]["result"][0]
    except Exception: return None
stocks = {s: v for s, v in P["stocks"].items() if (ONLY is None or s in ONLY) and v["verdict"].upper().startswith(("BUY", "ACTIVE"))}   # new buys + carried-over orders/positions only
print(f"OPEN CHECK {NOW:%Y-%m-%d %H:%M} IST | mode={MODE} | plan prepared {P['prep_time']}")

# ---- 1. global + Indian market overlay ----
cues = {}
for n, y in [("S&P500", "^GSPC"), ("Nasdaq", "^IXIC"), ("S&P fut", "ES=F"), ("Nasdaq fut", "NQ=F"), ("Nikkei", "^N225"), ("HangSeng", "^HSI"),
             ("Brent", "BZ=F"), ("USDINR", "INR=X"), ("US10Y", "^TNX")]:
    r = yq(y, "5d", "1d")
    if not r: continue
    m = r["meta"]; c = [x for x in r["indicators"]["quote"][0]["close"] if x]
    if len(c) >= 2: cues[n] = f'{m["regularMarketPrice"]:,.2f} ({(m["regularMarketPrice"]/c[-2]-1)*100:+.2f}%)'
print("GLOBAL", cues)
ai = {d["index"]: d for d in nse("allIndices").get("data", [])}
nf, vix = ai.get("NIFTY 50", {}), ai.get("INDIA VIX", {})
nifty_gap = nf.get("percentChange", 0); vix_chg = vix.get("percentChange", 0)
print(f'NIFTY {nf.get("last")} ({nifty_gap:+.2f}%) vs 200DMA {P.get("nifty_sma200")} | VIX {vix.get("last")} ({vix_chg:+.2f}%)' if nf else "NIFTY n/a")
caution = []
if MODE != "overnight" and nifty_gap <= -1: caution.append("Nifty down >1%: wait till 09:45, buy only names holding their zone; half size")
if MODE != "overnight" and vix_chg >= 10: caution.append("VIX +10%: half size")
if nf and P.get("nifty_sma200") and (nf.get("last", 0) > P["nifty_sma200"]) != (P["risk_pct"] >= 1): caution.append("Nifty crossed its 200DMA vs prep: re-check risk % / max positions")
print("MARKET CAUTION:", caution or "none")
# market read: broad indices, sector leaders/laggards, breadth, Nifty vs its opening range
g = lambda n: (ai.get(n, {}).get("last"), ai.get(n, {}).get("percentChange"))
market = dict(indices={n: g(n) for n in ("NIFTY 50", "NIFTY BANK", "NIFTY MIDCAP 100", "NIFTY SMALLCAP 100", "INDIA VIX") if n in ai})
sect = sorted([(d["index"].replace("NIFTY ", ""), d.get("percentChange") or 0) for d in ai.values() if d.get("key") == "SECTORAL INDICES"], key=lambda x: -x[1])
market["sector_leaders"], market["sector_laggards"] = sect[:3], sect[-3:][::-1]
n5 = ai.get("NIFTY 500", {})
try: market["advances"], market["declines"] = int(n5.get("advances")), int(n5.get("declines"))
except Exception: pass
if MODE == "live":
    r = yq("^NSEI")
    if r:
        q = r["indicators"]["quote"][0]
        d = pd.DataFrame({k: q.get(k) for k in ("high", "low", "close")}, index=pd.to_datetime(r.get("timestamp", []), unit="s", utc=True).tz_convert(IST)).dropna()
        d = d[d.index.date == NOW.date()]; o = d[(d.index.hour == 9) & (d.index.minute < 30)]
        if len(o):
            last = r["meta"]["regularMarketPrice"]; market.update(nifty_or_hi=round(float(o.high.max()), 1), nifty_or_lo=round(float(o.low.min()), 1))
            market["nifty_vs_range"] = "above opening range" if last > o.high.max() else ("below opening range" if last < o.low.min() else "inside opening range")
adv, dec = market.get("advances"), market.get("declines")
tone = "weak" if (nifty_gap <= -0.5 or (adv and dec and adv < 0.6*dec)) else ("strong" if (nifty_gap >= 0.4 and (not adv or adv > 1.3*(dec or 1))) else "mixed")
market["tone"] = tone
print("MARKET READ", json.dumps(market, default=str))

# ---- 2. prices ----
px = {}
if MODE == "pre-open":
    for key in ("FO", "ALL"):
        for d in nse(f"market-data-pre-open?key={key}", "market-data/pre-open-market-cm-and-emerge-market").get("data", []):
            m = d["metadata"]
            if m["symbol"] in stocks and m["symbol"] not in px and m.get("iep"):
                px[m["symbol"]] = dict(price=m["iep"], prev=m["previousClose"], open=None, high=None, low=None, src="NSE pre-open IEP")
def quote(s):
    r = yq(f"{s}.NS")
    if not r: return None
    m, q = r["meta"], r["indicators"]["quote"][0]
    df = pd.DataFrame({k: q.get(k) for k in ("open", "high", "low", "close", "volume")}, index=pd.to_datetime(r.get("timestamp", []), unit="s", utc=True).tz_convert(IST)).dropna(subset=["close"])
    today_bars = MODE == "live" and pd.Timestamp(m["regularMarketTime"], unit="s", tz="UTC").tz_convert(IST).date() == NOW.date()
    df = df[df.index.date == NOW.date()] if today_bars else df.iloc[0:0]
    dly = yq(f"{s}.NS", "1mo", "1d"); vavg = None
    if dly:
        vv = [x for x in dly["indicators"]["quote"][0].get("volume", []) if x][:-1][-20:]
        vavg = sum(vv)/len(vv) if vv else None
    frac = min(max((hm - 555)/375, 0.02), 1.0)                     # share of the 09:15-15:30 session elapsed
    orb = df[(df.index.hour == 9) & (df.index.minute < 30)]         # opening range = first 15 minutes
    vol = df.volume.fillna(0); vsum = float(vol.sum())
    vwap = float((((df.high + df.low + df.close)/3)*vol).sum()/vsum) if vsum > 0 else None
    return dict(price=m["regularMarketPrice"], prev=m.get("chartPreviousClose") if today_bars else m["regularMarketPrice"],
                open=float(df.open.iloc[0]) if len(df) else None, high=float(df.high.max()) if len(df) else None, low=float(df.low.min()) if len(df) else None,
                or_hi=float(orb.high.max()) if len(orb) else None, or_lo=float(orb.low.min()) if len(orb) else None, vwap=round(vwap, 2) if vwap else None,
                src="Yahoo live" if today_bars else "last close",
                vol_pace=round(vsum/(vavg*frac), 2) if (today_bars and vavg and vsum) else None)   # >1.5 = heavier than a normal day so far
for s in stocks:
    if s in px: continue
    q_ = quote(s)
    if q_: px[s] = q_
spurts = {}
if MODE == "live":
    sp = pd.DataFrame(nse("live-analysis-oi-spurts-underlyings", "market-data/oi-spurts").get("data", []))
    if len(sp): spurts = {r.symbol: r.changeInOI/r.prevOI*100 for r in sp.itertuples()}

# ---- 3. new filings since prep + results today ----
since = pd.Timestamp(P["prep_time"][:19])
red = re.compile(r"Resignation|Cessation|Auditor|USFDA|Form 483|Warning Letter|Import Alert|penalty|\bfine\b|SEBI order|Show Cause|Fraud|Default|Pledge|Qualified Institution|Preferential|Rights Issue|Search|Raid|Litigation|Outcome of Board|Financial Result|Press Release|Acquisition|Order", re.I)
noise = re.compile(r"Newspaper|Trading Window|ESOP|ESOS|Loss of Share|Duplicate|Certificate under", re.I)
frm = (since - pd.Timedelta(days=1)).strftime("%d-%m-%Y"); to = NOW.strftime("%d-%m-%Y")
news = {}
for s in stocks:
    items = []
    for r in nse(f"corporate-announcements?index=equities&symbol={urllib.parse.quote(s)}&from_date={frm}&to_date={to}", "companies-listing/corporate-filings-announcements") or []:
        t = pd.to_datetime(r.get("an_dt"), format="%d-%b-%Y %H:%M:%S", errors="coerce")
        if t is pd.NaT or t <= since or noise.search(r["desc"]): continue
        items.append(("!! " if red.search(r["desc"] + " " + r["attchmntText"]) else "") + f'{r["an_dt"]} {r["desc"][:40]} | {re.sub(r"\s+", " ", r["attchmntText"])[:120]} | {r["attchmntFile"]}')
    bm = nse(f"corporate-board-meetings?index=equities&symbol={urllib.parse.quote(s)}") or []
    for r in bm:
        d = pd.to_datetime(r.get("bm_date"), format="%d-%b-%Y", errors="coerce")
        if d is not pd.NaT and d.date() == NOW.date(): items.append(f'!! BOARD MEETING TODAY: {r.get("bm_purpose")}')
    news[s] = items

# ---- 4. per-stock action ----
rows = []
for s, v in stocks.items():
    p = px.get(s)
    if not p: rows.append(dict(symbol=s, action="NO PRICE - check manually")); continue
    price, prev = p["price"], p["prev"] or v["prev_close"]
    lo, hi, st, t1 = v["buy_lo"], v["buy_hi"], v["stop"], v["t1"]
    low_today = p["low"] if p["low"] else price
    held = any(k in v["verdict"].upper() for k in ("ACTIVE OPEN", "ACTIVE T1"))          # already bought: manage, don't buy
    if held: act = ("HELD - stop traded: exit" if low_today <= st else "HELD - at T1: book half, stop to entry" if price >= t1 else "HELD - no action")
    elif v["verdict"].startswith("WAIT"): act = "WAIT (event) - no entry"
    elif low_today <= st: act = "DROP - stop level traded, setup broken"
    elif price >= t1: act = "SKIP - already at T1" + (" without filling: cancel the order" if v["verdict"].upper().startswith("ACTIVE") else "")
    elif price > hi: act = f"ABOVE ZONE (+{(price/hi-1)*100:.1f}%) - don't chase; keep limit {lo}-{hi} for 10 sessions"
    elif price >= lo: act = "IN ZONE - buy" + (" after first 15-min candle holds (gap-down open)" if (price/prev-1) <= -0.02 else "")
    else: act = f"BELOW ZONE ({(price/lo-1)*100:.1f}%) - buy only if it reclaims {lo}; stop unchanged"
    if any(x.startswith("!!") for x in news.get(s, [])): act = "HOLD - read new filing first | " + act
    entry = price if (lo <= price <= hi or act.startswith("MOVING")) else (lo + hi)/2; rps = entry - st   # buy now if in zone / confirmed move
    qty = min(int(P["capital"]*P["risk_pct"]/100/rps), int(0.25*P["capital"]/entry)) if rps > 0 else 0
    if caution and MODE != "overnight": qty //= 2
    if v["verdict"].startswith("BUY SMALL"): qty //= 2
    ok, doubt = [], []
    if MODE == "live":
        if p.get("vwap"): (ok if price >= p["vwap"] else doubt).append("above VWAP" if price >= p["vwap"] else "below VWAP")
        if p.get("or_lo"): (ok if price > p["or_lo"] else doubt).append("holding opening range" if price > p["or_lo"] else "broke opening-range low")
        if p.get("vol_pace") is not None: (ok if p["vol_pace"] >= 0.8 else doubt).append(f'volume {p["vol_pace"]}x normal')
        if caution: doubt.append("market caution")
        if tone == "weak": doubt.append("weak market breadth")
    confident = act.startswith("IN ZONE") and not doubt and "gap-down" not in act
    # crossed the zone but still worth buying: confirmed by the tape, below T1, and ≥1.5R left to T2 from here with the plan's stop
    rr_now = (v["t2"] - price)/(price - st) if price > st else 0
    if act.startswith("ABOVE") and MODE == "live" and not doubt and len(ok) >= 2 and price < t1 and rr_now >= 1.5:
        confident = True; act = f"MOVING - above zone, confirmed, {rr_now:.1f}R left to T2"
        entry = price; rps = entry - st                                  # buy at market, size on the real distance to the stop
        qty = min(int(P["capital"]*P["risk_pct"]/100/rps), int(0.25*P["capital"]/entry))
        if caution: qty //= 2
    rows.append(dict(fill_px=v.get("fill_px"), symbol=s, group=v.get("group", "EARLIER" if v["verdict"].upper().startswith("ACTIVE") else "NEW"), why=v.get("why", ""), verdict=v["verdict"], src=p["src"], prev=prev, price=price, gap_pct=round((price/prev-1)*100, 2), open=p["open"], day_low=p["low"],
                     vwap=p.get("vwap"), or_hi=p.get("or_hi"), or_lo=p.get("or_lo"), confident=confident, confirms=ok, doubts=doubt,
                     zone=f"{lo}-{hi}", stop=st, t1=t1, entry=round(entry, 2), rr_t1=round((t1-entry)/rps, 2) if rps > 0 else None, qty=qty,
                     oi_chg=round(spurts[s], 1) if s in spurts else None, vol_pace=p.get("vol_pace"), action=act))
# ---- 5. next opportunities: analysed-but-not-picked names (WATCH) that open strong on volume. No order today; candidates for the next plan.
opps = []
if MODE == "live" and ONLY is None:
    for s, v in P["stocks"].items():
        if s in stocks or v["verdict"].upper().startswith(("AVOID", "WAIT")): continue
        p = quote(s)
        if not p or not p.get("or_hi") or not p.get("vwap") or not p.get("vol_pace"): continue
        chg = (p["price"]/p["prev"]-1)*100
        if chg >= 0.5 and p["price"] >= p["vwap"] and p["price"] >= p["or_hi"]*0.998 and p["vol_pace"] >= 1.3 and p["price"] < v["t1"]:
            opps.append(dict(symbol=s, price=p["price"], chg_pct=round(chg, 2), vol_pace=p["vol_pace"], zone=f'{v["buy_lo"]}-{v["buy_hi"]}', stop=v["stop"],
                             note="at/above opening-range high, above VWAP"))
    opps = sorted(opps, key=lambda o: -o["vol_pace"])[:4]
print("NEXT OPPORTUNITIES", opps)
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 90)
print(pd.DataFrame(rows).to_string(index=False))
print("\nBUY NOW only for rows with confident=True; held positions are managed, not bought.")
for s, it in news.items():
    for x in it: print("NEW FILING", s, x)
# ready-made Telegram caption (keeps the model's work at 09:31 minimal)
cap = [f"⏱ Live check {NOW:%H:%M} · Nifty {nifty_gap:+.2f}% · market {tone}"]
for g, lab in (("NEW", "New"), ("EARLIER", "Earlier")):
    rs = [r for r in rows if r.get("group") == g]
    if not rs: continue
    buys = [r for r in rs if r.get("confident")]
    cap.append(f"{lab}: " + ("; ".join(f'{r["symbol"]} BUY @{r["price"]:.0f} SL {r["stop"]:.0f} T1 {r["t1"]:.0f} Qty {r["qty"]}' for r in buys) or "no confirmed buy"))
    acts = [f'{r["symbol"]} {r["action"].split(" - ")[1] if " - " in r["action"] else r["action"]}' for r in rs if not r.get("confident") and any(k in r.get("action", "") for k in ("DROP", "exit", "cancel", "T1", "HOLD - read"))]
    if acts: cap.append("  action: " + "; ".join(acts))
if opps: cap.append("Next: " + ", ".join(f'{o["symbol"]} {o["chg_pct"]:+.1f}%' for o in opps))
open(os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), "caption.txt"), "w").write("\n".join(cap))
print("CAPTION\n" + "\n".join(cap))
# structured output for the visual card (render_cards.py open ...)
json.dump(dict(time=f"{NOW:%d %b %Y %H:%M} IST", mode=MODE, prep_time=P["prep_time"], nifty=nf.get("last"), nifty_chg=nifty_gap, vix=vix.get("last"),
               vix_chg=vix_chg, nifty_sma200=P["nifty_sma200"], caution=caution, max_positions=P["max_positions"], cues=cues, market=market, opportunities=opps,
               rows=[{**r, **{k: P["stocks"][r["symbol"]].get(k) for k in ("t2",)}} for r in rows], news=news),
          open(os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), "open_check.json"), "w"), indent=1, default=str)
