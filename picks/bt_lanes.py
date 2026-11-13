"""Does widening the shortlist help? Compares the current funnel with a 'fresh momentum' lane and stale-name rotation.
Each day (5y): hard filters -> shortlist -> 3 picks not already active -> existing trade plan
(fill within 10 sessions at/below buy_hi, stop checked first, T1 = 2R, 60-session time stop, 0.35% costs).
Survivorship-biased (today's index lists). Usage: python3 bt_lanes.py PXDIR UNIVERSE_CSV"""
import json, sys
import numpy as np, pandas as pd
PX, UNI = sys.argv[1], sys.argv[2]
COST, K, PER = 0.0035, 3, 6
END = pd.Timestamp("2026-11-12")
def load(p):
    try: r = json.load(open(p))["chart"]["result"][0]
    except Exception: return None
    q = r["indicators"]["quote"][0]
    d = pd.DataFrame({k: q[k] for k in ["open", "high", "low", "close", "volume"]},
                     index=pd.to_datetime(r["timestamp"], unit="s").tz_localize("UTC").tz_convert("Asia/Kolkata").normalize().tz_localize(None))
    d = d.dropna(subset=["close"]); d = d[~d.index.duplicated(keep="last")]
    return d[d.index < END]
u = pd.read_csv(UNI); CAP = dict(zip(u.symbol, u.cap))
N = load(f"{PX}/_NSEI.json").close
F, D = {}, {}
for s in u.symbol:
    df = load(f"{PX}/{s.replace('&','_')}.json")
    if df is None or len(df) < 400: continue
    c, h, l, v = df.close, df.high, df.low, df.volume
    s20, s50, s200 = c.rolling(20).mean(), c.rolling(50).mean(), c.rolling(200).mean()
    dd = c.diff(); au = dd.clip(lower=0).ewm(alpha=1/14, adjust=False).mean(); ad = (-dd.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    hi252 = h.rolling(252, min_periods=150).max(); hh20 = h.rolling(20).max().shift(1)
    n = N.reindex(df.index).ffill()
    F[s] = pd.DataFrame(dict(
        ok=(c > s50) & (c > s200) & (c/hi252 >= 0.85) & (c.pct_change(21) > 0) & ((c*v).rolling(20).mean()/1e7 >= 10),
        rs63=c.pct_change(63)-n.pct_change(63), r126=c.pct_change(126), r21=c.pct_change(21), fh=c/hi252-1,
        r5=c.pct_change(5), brk=(c >= hh20*0.995).astype(float), volx=v.rolling(5).mean()/v.rolling(50).mean(),
        close=c, s20=s20, rsi=100-100/(1+au/ad), atr=tr.ewm(alpha=1/14, adjust=False).mean(), low10=l.rolling(10).min()))
    D[s] = df
P = {k: pd.DataFrame({s: f[k] for s, f in F.items()}).reindex(N.index) for k in F[next(iter(F))].columns}
days = [d for d in N.index if d >= N.index[260] and d <= N.index[-62]]
above200 = (N > N.rolling(200).mean())

def plan(r):
    p, a, s20 = r.close, r.atr, r.s20
    lo, hi = (max(s20, p-2*a), p-a) if (r.rsi > 70 or (p-s20)/s20 > 0.06) else (p-0.75*a, p)
    em = (lo+hi)/2; stop = min(max(r.low10-0.25*a, em-2.5*a), em-1.5*a)
    return min(hi, p), stop, em+2*(em-stop)
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

V = ["current", "fresh_slot", "rotation", "fresh+rotation", "fresh_only"]
res = {v: [] for v in V}; SLs = {v: [] for v in V}; active = {v: {} for v in V}
hist = []                                   # base shortlists of previous days (for staleness)
for d in days:
    ok = P["ok"].loc[d].fillna(False).astype(bool)
    if ok.sum() < 20: hist.append(set()); continue
    x = pd.DataFrame({k: P[k].loc[d][ok] for k in P if k != "ok"}).astype(float); x["cap"] = [CAP[s] for s in x.index]
    pr = lambda k: x[k].rank(pct=True)
    x["old"] = .35*pr("rs63") + .25*pr("r126") + .2*pr("r21") + .2*pr("fh")
    x["fresh"] = .5*pr("r21") + .25*pr("volx") + .25*x.brk
    order = x.sort_values("old", ascending=False)
    base = list(order.groupby("cap").head(PER).index)
    # stale = on the base shortlist each of the last 3 days, and nothing new (|5d move| < 3%, no 20-day breakout today)
    stale = {s for s in base if len(hist) >= 3 and all(s in h_ for h_ in hist[-3:]) and abs(x.at[s, "r5"]) < 0.03 and x.at[s, "brk"] == 0}
    rot = [s for s in order.index if s not in stale]
    rot = list(x.loc[rot].sort_values("old", ascending=False).groupby("cap").head(PER).index)
    fresh = list(x.drop(index=base).sort_values("fresh", ascending=False).groupby("cap").head(2).index)
    fresh_r = list(x.drop(index=rot).sort_values("fresh", ascending=False).groupby("cap").head(2).index)
    hist.append(set(base))
    for v in V:
        act = active[v]
        for s in [s for s, e in act.items() if e <= d]: act.pop(s)
        if v == "current":          sl, picks = base, [s for s in base if s not in act][:K]
        elif v == "rotation":       sl, picks = rot, [s for s in sorted(rot, key=lambda s: -x.at[s, "old"]) if s not in act][:K]
        elif v == "fresh_slot":
            sl = base + fresh
            picks = [s for s in sorted(base, key=lambda s: -x.at[s, "old"]) if s not in act][:K-1] + [s for s in fresh if s not in act][:1]
        elif v == "fresh+rotation":
            sl = rot + fresh_r
            picks = [s for s in sorted(rot, key=lambda s: -x.at[s, "old"]) if s not in act][:K-1] + [s for s in fresh_r if s not in act][:1]
        else:                       sl, picks = fresh, [s for s in sorted(fresh, key=lambda s: -x.at[s, "fresh"]) if s not in act][:K]
        SLs[v].append(set(sl))
        for s in picks:
            t = trade(s, d, x.loc[s]); act[s] = t["end"]; t.update(sym=s, date=d, up=bool(above200.loc[d])); res[v].append(t)

def summ(v):
    b = pd.DataFrame(res[v]); f = b[b.filled]
    new = np.mean([len(a - p) for p, a in zip(SLs[v][:-1], SLs[v][1:])])
    pf = lambda z: round(z[z > 0].sum()/-z[z < 0].sum(), 2)
    half = f.date < f.date.iloc[len(f)//2]
    return dict(recs=len(b), fill_pct=round(b.filled.mean()*100, 1), trades=len(f), hit_t1_pct=round((f.tag == "t1").mean()*100, 1),
                avg_net_pct=round(f.net.mean()*100, 2), pf=pf(f.net), total_net_pct=round(f.net.sum()*100),
                older_half=round(f.net[half].mean()*100, 2), newer_half=round(f.net[~half].mean()*100, 2),
                nifty_above200=round(f.net[f.up].mean()*100, 2), nifty_below200=round(f.net[~f.up].mean()*100, 2),
                shortlist_new_per_day=round(new, 1), distinct_picked=b.sym.nunique())
out = {v: summ(v) for v in V}
print(pd.DataFrame(out).T.to_string())
for v in V:
    f = pd.DataFrame(res[v]); f = f[f.filled].copy(); f["y"] = pd.to_datetime(f.date).dt.year
    print(f"{v:<15} by year:", f.groupby("y").net.agg(lambda z: round(z.mean()*100, 2)).to_dict())
json.dump(out, open("/tmp/claude-0/bt_lanes.json", "w"), indent=1)
