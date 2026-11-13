"""STEP 6 — end-of-day review. Run after 15:45 IST on the pulled journal (journal.py update is run inside).
Usage: python3 s6_eod_review.py JOURNAL.json OUTDIR   -> OUTDIR/eod.json (for render_cards.py eod) + printed evidence tables."""
import json, os, subprocess, sys
import numpy as np, pandas as pd
J, OUT = sys.argv[1], sys.argv[2]; os.makedirs(OUT, exist_ok=True)
HERE = os.path.dirname(os.path.abspath(__file__)); IST = "Asia/Kolkata"
before = {r["id"]: (r["status"], r.get("half_booked")) for r in json.load(open(J))["recs"]}
print(subprocess.run([sys.executable, f"{HERE}/journal.py", "update", J], capture_output=True, text=True).stdout.strip())
j = json.load(open(J)); R = pd.DataFrame(j["recs"]); Wt = pd.DataFrame(j["watch"])
sys.path.insert(0, HERE); from journal import daily
UA = "Mozilla/5.0"; nr = json.loads(subprocess.run(f'curl -sS -A "{UA}" "https://query2.finance.yahoo.com/v8/finance/chart/%5ENSEI?range=1mo&interval=1d"', shell=True, capture_output=True, text=True).stdout)["chart"]["result"][0]
ns = pd.Series(nr["indicators"]["quote"][0]["close"], index=pd.to_datetime(nr["timestamp"], unit="s").tz_localize("UTC").tz_convert(IST).normalize().tz_localize(None)).dropna()
now = pd.Timestamp.now(tz=IST); cut = now.normalize().tz_localize(None) + (pd.Timedelta(days=1) if (now.hour, now.minute) >= (15, 45) else pd.Timedelta(0))
ns = ns[ns.index < cut]; day = ns.index[-1]; nifty_day = round((ns.iloc[-1]/ns.iloc[-2] - 1)*100, 2)
D = str(day.date())

# ---- today's picks: what the price actually did today ----
today_rows = []
for r in j["recs"]:
    if r["date"] != D: continue
    b = daily(r["symbol"], "1mo"); b = b[b.index == day] if b is not None else None
    if b is None or not len(b): continue
    b = b.iloc[0]; ref = r.get("ref_close") or b.open
    touched = b.low <= r["buy_hi"]
    out = ("STOPPED" if r["status"] == "closed" and r["exit_reason"].startswith("stop") else "T1 HIT" if r["half_booked"] else
           "FILLED" if r["status"] in ("open", "t1_partial") else "NOT FILLED")
    today_rows.append(dict(symbol=r["symbol"], verdict=r["verdict"], zone=f'{r["buy_lo"]}-{r["buy_hi"]}', stop=r["stop"], t1=r["t1"],
                           open=round(b.open, 2), high=round(b.high, 2), low=round(b.low, 2), close=round(b.close, 2), day_pct=round((b.close/ref - 1)*100, 2),
                           vs_nifty=round((b.close/ref - 1)*100 - nifty_day, 2), touched_zone=bool(touched), outcome=out,
                           close_vs_zone_pct=round((b.close/r["buy_hi"] - 1)*100, 2), fill_px=r.get("fill_px"), mark_r=r.get("mark_r")))
# ---- events on older recs today (fills, stops, targets, expiries) ----
events = []
for r in j["recs"]:
    if r["date"] == D: continue
    old = before.get(r["id"]); new = (r["status"], r.get("half_booked"))
    if old and old != new:
        what = ("filled @" + str(r["fill_px"]) if old[0] == "pending" and new[0] in ("open", "t1_partial") else
                "T1 hit — half booked, stop to entry" if new[1] and not old[1] else
                f'closed: {r["exit_reason"]} ({r["r_mult"]:+.2f}R)' if new[0] == "closed" else
                f'expired unfilled (price {r.get("missed_move_pct", 0):+.1f}% vs zone top)' if new[0] == "expired" else new[0])
        events.append(dict(symbol=r["symbol"], rec_date=r["date"], event=what))
openpos = [dict(symbol=r["symbol"], rec_date=r["date"], status=r["status"], fill_px=r["fill_px"], stop_now=r["stop_now"], t1=r["t1"], t2=r["t2"],
                mark_r=r.get("mark_r"), last_close=r.get("last_close"), sessions=r["sessions"]) for r in j["recs"] if r["status"] in ("open", "t1_partial")]
pending = [dict(symbol=r["symbol"], rec_date=r["date"], zone=f'{r["buy_lo"]}-{r["buy_hi"]}', sessions_left=10 - r["sessions"]) for r in j["recs"] if r["status"] == "pending"]
# ---- non-buy calls today: were they right? ----
watch_today = [dict(symbol=w["symbol"], verdict=w["verdict"], reason=w.get("reason"), ret_1d=w.get("ret_1d"),
                    excess_1d=None if w.get("ret_1d") is None or w.get("nifty_1d") is None else round(w["ret_1d"] - w["nifty_1d"], 2))
               for w in j["watch"] if w["date"] == D]

# ---- running scorecard ----
def stats(df):
    c = df[df.status == "closed"] if len(df) else df
    filled = df[df.fill_px.notna()] if len(df) else df
    return dict(recs=len(df), filled=len(filled), fill_rate=round(len(filled)/len(df)*100) if len(df) else None, closed=len(c),
                win_rate=round((c.r_mult > 0).mean()*100) if len(c) else None, avg_r=round(c.r_mult.mean(), 2) if len(c) else None,
                total_r=round(c.r_mult.sum(), 2) if len(c) else 0.0, open_mark_r=round(df[df.status.isin(["open", "t1_partial"])].get("mark_r", pd.Series(dtype=float)).fillna(0).sum(), 2) if len(df) else 0.0,
                expired=int((df.status == "expired").sum()) if len(df) else 0)
score = stats(R) if len(R) else stats(pd.DataFrame(columns=["status", "fill_px", "r_mult"]))
# evidence by feature bucket: realized R (closed) + mark R (open) so early days aren't empty; n shown, nothing is "learned" below n=15
ev = []
if len(R):
    F = pd.json_normalize(R.features).add_prefix("f_"); X = pd.concat([R.reset_index(drop=True), F], axis=1)
    X["outcome_r"] = X.r_mult.fillna(X.get("mark_r"))
    X = X[X.fill_px.notna()]
    def bucket(name, s):
        for k, g in X.groupby(s, dropna=True):
            ev.append(dict(factor=name, bucket=str(k), n=len(g), avg_r=round(g.outcome_r.mean(), 2), win=round((g.outcome_r > 0).mean()*100)))
    if len(X):
        bucket("verdict", X.verdict.str.upper().str.startswith("BUY SMALL").map({True: "BUY SMALL", False: "BUY"}))
        for col, name in [("f_cap", "cap"), ("f_style", "entry style"), ("f_catalyst", "overnight catalyst"), ("f_fo_today", "futures signal"), ("f_regime_above200", "Nifty>200DMA")]:
            if col in X: bucket(name, X[col])
        if "f_rsi" in X: bucket("RSI", pd.cut(X.f_rsi, [0, 60, 70, 100], labels=["<60", "60-70", ">70"]))
        if "f_deliv_updown" in X: bucket("delivery up/down", pd.cut(X.f_deliv_updown, [0, 0.9, 1.2, 99], labels=["<0.9", "0.9-1.2", ">1.2"]))
wev = []
if len(Wt):
    Wd = Wt.dropna(subset=["ret_1d"]).copy()
    if len(Wd):
        Wd["ex1"] = Wd.ret_1d - Wd.nifty_1d.fillna(0); Wd["ex5"] = Wd.ret_5d - Wd.nifty_5d.fillna(0)
        for k, g in Wd.groupby(Wd.verdict.str.split().str[0].str.upper()):
            wev.append(dict(call=k, n=len(g), avg_excess_1d=round(g.ex1.mean(), 2), n5=int(g.ex5.notna().sum()), avg_excess_5d=round(g.ex5.mean(), 2) if g.ex5.notna().any() else None))
out = dict(date=D, nifty_day=nifty_day, today=today_rows, events=events, open=openpos, pending=pending, watch=watch_today, score=score,
           evidence=ev, watch_evidence=wev, lessons=[l for l in j["lessons"] if l["status"] in ("active", "provisional")][-6:])
json.dump(out, open(f"{OUT}/eod.json", "w"), indent=1, default=str); json.dump(j, open(J, "w"), indent=1, default=str)
pd.set_option("display.width", 220)
print(f"\nEOD {D} | Nifty {nifty_day:+.2f}%"); print("TODAY'S PICKS\n", pd.DataFrame(today_rows).to_string(index=False) if today_rows else " none")
print("EVENTS ON OLDER RECS:", events or "none"); print("OPEN:", openpos or "none"); print("PENDING ORDERS:", pending or "none")
print("NON-BUY CALLS TODAY\n", pd.DataFrame(watch_today).to_string(index=False) if watch_today else " none")
print("SCORECARD:", score); print("EVIDENCE BY FACTOR (n<15 = anecdote, do not change rules)\n", pd.DataFrame(ev).to_string(index=False) if ev else " none yet")
print("NON-BUY CALL OUTCOMES (excess vs Nifty)\n", pd.DataFrame(wev).to_string(index=False) if wev else " none yet")
