"""Selection backtest: does a setup-aware, rotating ranking beat the pure-momentum ranking?
Each day: rank stocks that pass the hard filters, take the top K not already active, trade the existing plan
(fill within 10 sessions at/below buy_hi, stop first, T1 = 2R, 60-session time stop, 0.35% costs). Survivorship-biased (today's index lists)."""
import json, glob, os, sys
import numpy as np, pandas as pd
PX, UNI = sys.argv[1], sys.argv[2]
COST, K = 0.0035, 3
def load(p):
    try: r = json.load(open(p))["chart"]["result"][0]
    except Exception: return None
    q = r["indicators"]["quote"][0]
    d = pd.DataFrame({k: q[k] for k in ["open", "high", "low", "close", "volume"]},
                     index=pd.to_datetime(r["timestamp"], unit="s").tz_localize("UTC").tz_convert("Asia/Kolkata").normalize().tz_localize(None))
    d = d.dropna(subset=["close"]); d = d[~d.index.duplicated(keep="last")]
    return d[d.index < pd.Timestamp("2026-11-12")]
u = pd.read_csv(UNI); ind_of = dict(zip(u.symbol, u.industry))
N = load(f"{PX}/_NSEI.json").close
F, D = {}, {}
for s in u.symbol:
    df = load(f"{PX}/{s.replace('&','_')}.json")
    if df is None or len(df) < 400: continue
    c, h, l, v = df.close, df.high, df.low, df.volume
    e20, e50 = c.ewm(span=20, adjust=False).mean(), c.ewm(span=50, adjust=False).mean()
    s20, s50, s200 = c.rolling(20).mean(), c.rolling(50).mean(), c.rolling(200).mean()
    dd = c.diff(); au = dd.clip(lower=0).ewm(alpha=1/14, adjust=False).mean(); ad = (-dd.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rsi = 100 - 100/(1+au/ad)
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1); atr = tr.ewm(alpha=1/14, adjust=False).mean()
    hh20 = h.rolling(20).max().shift(1); hi252 = h.rolling(252, min_periods=150).max()
    bbw = 4*c.rolling(20).std()/s20; bbp = bbw.rolling(126, min_periods=40).rank(pct=True)
    n = N.reindex(df.index).ffill()
    volx = v/v.rolling(20).mean()
    setup = np.select([(c >= hh20*0.995) & (volx >= 1.5), (c >= hh20*0.995),
                       (l.rolling(3).min() <= e20*1.01) & (c > e20) & (e20 > e50), (bbp < 0.25) & (c > e50)], [1.0, 0.6, 0.9, 0.7], 0.3)
    ext = (c-e20)/atr
    setup = setup - 0.4*(ext > 2.5) - 0.3*(rsi > 75)
    F[s] = pd.DataFrame(dict(ok=(c > s50) & (c > s200) & (c/hi252 >= 0.85) & (c.pct_change(21) > 0) & ((c*v).rolling(20).mean()/1e7 >= 10),
                             rs63=c.pct_change(63)-n.pct_change(63), r126=c.pct_change(126), r21=c.pct_change(21), fh=c/hi252-1,
                             ext=ext, setupraw=pd.Series(np.select([(c >= hh20*0.995) & (volx >= 1.5), (c >= hh20*0.995), (l.rolling(3).min() <= e20*1.01) & (c > e20) & (e20 > e50), (bbp < 0.25) & (c > e50)], [4, 3, 2, 1], 0), index=df.index), srs=(c.pct_change(5)-n.pct_change(5)) + (c.pct_change(10)-n.pct_change(10)), setup=setup, r20=c.pct_change(20),
                             close=c, s20=s20, rsi=rsi, atr=atr, low10=l.rolling(10).min()))
    D[s] = df
days = [d for d in N.index if d >= N.index[260] and d <= N.index[-62]]
PANEL = {k: pd.DataFrame({s: f[k] for s, f in F.items()}).reindex(N.index) for k in F[next(iter(F))].columns}
SECT = PANEL["r20"].T.groupby(lambda s: ind_of.get(s)).transform("mean").T      # industry 20d mean return, per stock
def rank_day(d):
    ok = PANEL["ok"].loc[d].fillna(False).astype(bool)
    if not ok.any(): return None
    x = pd.DataFrame({k: PANEL[k].loc[d][ok] for k in PANEL if k != "ok"}).astype(float); x["sec"] = SECT.loc[d][ok]
    pr = lambda k: x[k].rank(pct=True)
    x["old"] = .35*pr("rs63") + .25*pr("r126") + .2*pr("r21") + .2*pr("fh")
    x["new"] = .40*x.old.rank(pct=True) + .35*x.setup + .15*pr("srs") + .10*pr("sec")
    return x
def plan(r):
    p, a, s20 = r.close, r.atr, r.s20
    lo, hi = (max(s20, p-2*a), p-a) if (r.rsi > 70 or (p-s20)/s20 > 0.06) else (p-0.75*a, p)
    em = (lo+hi)/2; stop = min(max(r.low10-0.25*a, em-2.5*a), em-1.5*a); R = em-stop
    return min(hi, p), stop, em+2*R
def trade(s, d, r):
    df = D[s]; i = df.index.get_loc(d); hi, stop, t1 = plan(r)
    o, h, l, c = df.open.values, df.high.values, df.low.values, df.close.values
    fill = next((j for j in range(i+1, min(i+11, len(df))) if l[j] <= hi), None)
    if fill is None: return dict(filled=False, end=df.index[min(i+10, len(df)-1)])
    e = o[fill] if o[fill] <= hi else hi
    for k in range(fill, min(fill+60, len(df))):
        if l[k] <= stop: return dict(filled=True, tag="stop", net=(min(stop, o[k])-e)/e-COST, end=df.index[k])
        if h[k] >= t1: return dict(filled=True, tag="t1", net=(t1-e)/e-COST, end=df.index[k])
    return dict(filled=True, tag="time", net=(c[k]-e)/e-COST, end=df.index[k])
res = {v: [] for v in ("old", "new", "old_noext", "old_setup")}; lists = {v: [] for v in res}
active = {v: {} for v in res}; recent = {}
for n_, d in enumerate(days):
    x = rank_day(d)
    if x is None: continue
    for v in res:
        key = "new" if v == "new" else "old"
        act = active[v]
        for s in [s for s, end in act.items() if end <= d]: act.pop(s)
        xx = x
        if v == "old_noext": xx = x[(x.ext <= 2.5) & (x.rsi <= 75)]
        if v == "old_setup": xx = x[x.setupraw.isin([4, 2])]
        cand = [s for s in xx.sort_values(key, ascending=False).index if s not in act]
        if v == "new_rot":   # rotation: skip names recommended in the last 10 sessions that never filled
            cand = [s for s in cand if not (s in recent and n_ - recent[s] <= 10)]
        pick = cand[:K]; lists[v].append(pick)
        for s in pick:
            t = trade(s, d, x.loc[s]); act[s] = t["end"]; t.update(sym=s, date=d); res[v].append(t)
            if v == "new_rot" and not t["filled"]: recent[s] = n_
def summ(v):
    b = pd.DataFrame(res[v]); f = b[b.filled]
    turn = np.mean([len(set(a) - set(p))/K for p, a in zip(lists[v][:-1], lists[v][1:])])
    return dict(recs=len(b), fill_rate=round(b.filled.mean()*100, 1), trades=len(f), hit_t1=round((f.tag == "t1").mean()*100, 1),
                avg_net=round(f.net.mean()*100, 2), pf=round(f.net[f.net > 0].sum()/-f.net[f.net < 0].sum(), 2),
                distinct_names=b.sym.nunique(), daily_new_names_pct=round(turn*100, 1))
out = {v: summ(v) for v in res}
for v, s in out.items(): print(v, s)
for v in res:
    b = pd.DataFrame(res[v]); f = b[b.filled].copy(); f["y"] = pd.to_datetime(f.date).dt.year
    print(v, "by year:", f.groupby("y").net.agg(lambda z: round(z.mean()*100, 2)).to_dict(), "n:", f.groupby("y").size().to_dict())
json.dump(out, open("/tmp/claude-0/bt_select.json", "w"), indent=1)
