"""STEP 2 — momentum screen across Large/Mid/Small caps; writes shortlist.csv + regime.json.
Usage: python3 s2_screen.py WORKDIR [shortlist_size=20]
Shortlist = the top-scored names, as even a split across Large/Mid/Small as possible (20 -> 7/7/6 by score)."""
import json, sys, os
import numpy as np, pandas as pd

W = sys.argv[1]; TOTAL = int(sys.argv[2]) if len(sys.argv) > 2 else 20
TOTAL = TOTAL*3 if TOTAL <= 8 else TOTAL          # old callers passed per-bucket (6) -> 18
PER = -(-TOTAL // 3)
IST = "Asia/Kolkata"

def load(path):
    try: r = json.load(open(path))["chart"]["result"][0]
    except Exception: return None, None
    q = r["indicators"]["quote"][0]
    idx = pd.to_datetime(r["timestamp"], unit="s").tz_localize("UTC").tz_convert(IST).normalize().tz_localize(None)
    df = pd.DataFrame({k: q[k] for k in ["open", "high", "low", "close", "volume"]}, index=idx).dropna(subset=["close"])
    return df[~df.index.duplicated(keep="last")], r["meta"]

nifty, nmeta = load(f"{W}/px/_NSEI.json")
# completed sessions only: before 16:00 IST today's bar is partial (or absent pre-open); after 16:00 today's bar is final
now = pd.Timestamp.now(tz=IST); today = now.normalize().tz_localize(None) + (pd.Timedelta(days=1) if now.hour >= 16 else pd.Timedelta(0))
n_done = nifty[nifty.index < today].close
regime = dict(nifty_live=nmeta["regularMarketPrice"], sma50=round(n_done.tail(50).mean(), 1), sma200=round(n_done.tail(200).mean(), 1),
              hi52=round(n_done.tail(252).max(), 1), lo52=round(n_done.tail(252).min(), 1), last_completed=str(n_done.index[-1].date()))
regime["above_200dma"] = bool(regime["nifty_live"] > regime["sma200"])
regime["risk_per_trade_pct"] = 1.0 if regime["above_200dma"] else 0.5
regime["max_new_positions"] = 3 if regime["above_200dma"] else 2      # confident picks only; zero is a valid day
# global cues (last two completed closes)
glob_ = {}
for n in ["GSPC", "IXIC", "BRENT", "USDINR", "US10Y", "DXY", "N225", "HSI", "INDIAVIX", "NSEBANK"]:
    g, gm = load(f"{W}/px/_{n}.json")
    if g is None: continue
    c = g.close.dropna(); glob_[n] = dict(last=round(gm.get("regularMarketPrice") or c.iloc[-1], 2), prev=round(c.iloc[-2], 2), date=str(c.index[-1].date()),
                                         chg_pct=round(((gm.get("regularMarketPrice") or c.iloc[-1])/c.iloc[-2]-1)*100, 2))
regime["global"] = glob_
json.dump(regime, open(f"{W}/regime.json", "w"), indent=1); print("REGIME", regime)

u = pd.read_csv(f"{W}/lists/universe.csv"); DF = {}
for s, cap, ind in zip(u.symbol, u.cap, u.industry):
    df, meta = load(f"{W}/px/{s.replace('&', '_')}.json")
    if df is None or len(df) < 265: continue
    DF[s] = (df[df.index < today], meta, cap, ind)
sess = list(n_done.index)

def screen(k):
    """Metrics as of k sessions back (k=0: latest completed session, live price). Returns (all rows, filtered+scored)."""
    nd = n_done.iloc[:len(n_done)-k]; rows = []
    for s, (d0, meta, cap, ind) in DF.items():
        d = d0[d0.index <= nd.index[-1]]
        if len(d) < 260: continue
        c, v = d.close, d.volume
        live = (meta.get("regularMarketPrice") or c.iloc[-1]) if k == 0 else c.iloc[-1]
        sma50, sma200 = c.tail(50).mean(), c.tail(200).mean()
        r1m, r3m, r6m = c.iloc[-1] / c.iloc[-22] - 1, c.iloc[-1] / c.iloc[-64] - 1, c.iloc[-1] / c.iloc[-127] - 1
        n3 = nd.iloc[-1] / nd.iloc[-64] - 1
        hi = d.high.tail(252).max(); turnover_cr = (c * v).tail(20).mean() / 1e7
        rows.append(dict(symbol=s, cap=cap, industry=ind, live=live, r1m=r1m*100, r3m=r3m*100, r6m=r6m*100, rs3m=(r3m-n3)*100,
                         from_hi=(live/hi-1)*100, above50=live > sma50, above200=live > sma200, golden=sma50 > sma200, turnover_cr=turnover_cr,
                         r5=(c.iloc[-1]/c.iloc[-6]-1)*100, brk=bool(c.iloc[-1] >= d.high.iloc[-21:-1].max()*0.995),
                         volx=v.tail(5).mean()/max(v.tail(50).mean(), 1)))
    m = pd.DataFrame(rows)
    # hard filters: uptrend + liquidity + near highs
    f = m[m.above50 & m.above200 & (m.from_hi > -15) & (m.r1m > 0) & (m.turnover_cr >= 10)].copy()
    # momentum score = rank-average of 3M RS, 6M return, 1M return, closeness to 52w high
    for c_ in ["rs3m", "r6m", "r1m", "from_hi"]: f[c_ + "_rk"] = f[c_].rank(pct=True)
    f["score"] = (0.35*f.rs3m_rk + 0.25*f.r6m_rk + 0.2*f.r1m_rk + 0.2*f.from_hi_rk).round(3)
    return m, f
pick = lambda f: f.sort_values("score", ascending=False).groupby("cap").head(PER).sort_values("score", ascending=False).head(TOTAL)
top = lambda f: set(pick(f).symbol)
m, f = screen(0)
# ROTATION (backtested: same per-trade quality, more fresh names): a name that has been in the top-6 of its bucket on each of the
# last 3 sessions AND has nothing new (|5-day move| < 3% and no 20-day breakout) is rested today; the next-ranked name takes its slot.
prev = [top(screen(k)[1]) for k in (1, 2, 3)]
base = top(f)
stale = sorted(s for s in base if all(s in p for p in prev) and abs(f.loc[f.symbol == s, "r5"].iloc[0]) < 3 and not f.loc[f.symbol == s, "brk"].iloc[0])
# carry-over memory: names that are already open trades / live limit orders (journal) are NOT re-picked as new ideas
ACT = json.load(open(f"{W}/active.json")) if os.path.exists(f"{W}/active.json") else {}
f["bucket"] = f.cap
sl = pick(f[~f.symbol.isin(ACT) & ~f.symbol.isin(stale)])
regime.update(passed_filters=int(len(f)), shortlist_size=TOTAL, rested=stale)
json.dump(regime, open(f"{W}/regime.json", "w"), indent=1)
extra = []
for s_ in ACT:                                   # re-check active names (filings/results/stop) but tag them
    r_ = m[m.symbol == s_]
    if len(r_): extra.append(r_.assign(bucket="Active", score=np.nan))
OVN = json.load(open(f"{W}/overnight.json")) if os.path.exists(f"{W}/overnight.json") else {}
cat = m[m.symbol.isin(OVN.get("catalyst_symbols", [])) & m.above200 & (m.turnover_cr >= 10) & ~m.symbol.isin(sl.symbol) & ~m.symbol.isin(ACT)]
if len(cat): extra.append(cat.assign(bucket="Catalyst", score=np.nan).sort_values("rs3m", ascending=False).head(4))
sl = pd.concat([sl] + extra, ignore_index=True)
sl = sl.sort_values(["bucket", "score"], ascending=[True, False])
sl.round(2).to_csv(f"{W}/shortlist.csv", index=False)
print(f"screened {len(m)} | passed filters {len(f)} | shortlist {len(sl)}")
print(sl[["symbol", "bucket", "cap", "industry", "live", "r1m", "r3m", "rs3m", "from_hi", "score"]].round(1).to_string(index=False))
print("excluded as active (carried over):", list(ACT))
print("rested today (top-ranked 3+ sessions, nothing new):", stale)
