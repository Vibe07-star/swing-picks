"""Persistent trade journal stored as a pinned JSON document in the Telegram chat (survives fresh sessions).
  python3 journal.py pull OUT.json                         # download latest pinned journal (creates an empty one if none)
  python3 journal.py push JOURNAL.json "caption"           # upload + pin (silent)
  python3 journal.py active JOURNAL.json WORKDIR           # -> WORKDIR/active.json: open trades + live limit orders (not re-picked as new)
  python3 journal.py record JOURNAL.json WORKDIR           # after PREP: add today's BUY/BUY SMALL recs + WAIT/WATCH/AVOID/catalyst names;
                                                           #   merge active orders into plan.json so the 09:30 check covers them
  python3 journal.py plan JOURNAL.json WORKDIR [capital]   # 09:31: WORKDIR/plan.json from active recs (today's = NEW, older = EARLIER)
  python3 journal.py cancel JOURNAL.json SYMBOL "reason"   # cancel an unfilled order after the morning re-check
  python3 journal.py update JOURNAL.json                   # walk daily bars for every pending/open rec up to the last completed session
  python3 journal.py lesson JOURNAL.json "text" "evidence" N provisional|active|retired
Env: TG_TOKEN, TG_CHAT."""
import json, os, subprocess, sys, urllib.parse
import pandas as pd
IST = "Asia/Kolkata"; UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
sh = lambda c: subprocess.run(c, shell=True, capture_output=True, text=True).stdout
TOK, CHAT = os.environ.get("TG_TOKEN", ""), os.environ.get("TG_CHAT", "")
API = f"https://api.telegram.org/bot{TOK}"
EMPTY = dict(version=3, created=None, updated=None, recs=[], watch=[], days=[], lessons=[])
EXPIRY, MAXHOLD = 10, 60                      # limit order valid 10 sessions; time stop 60 sessions after fill

def tg(method, *args):
    try: return json.loads(sh(f"curl -sS -m 60 {' '.join(args)} {API}/{method}"))
    except Exception: return {}
def pull(out):
    pm = tg("getChat", f"-d chat_id={CHAT}").get("result", {}).get("pinned_message", {})
    doc = pm.get("document", {})
    if doc.get("file_name", "").startswith("journal") and doc.get("file_name", "").endswith(".json"):
        fp = tg("getFile", f"-d file_id={doc['file_id']}").get("result", {}).get("file_path")
        if fp:
            sh(f'curl -sS -m 60 -o "{out}" "https://api.telegram.org/file/bot{TOK}/{fp}"')
            try: j = json.load(open(out)); print(f"JOURNAL_OK recs={len(j['recs'])} watch={len(j['watch'])} lessons={len(j['lessons'])}"); return j
            except Exception: pass
    # Safety: the latest pinned message is not a journal (user pinned something else, or it was unpinned).
    # Start an empty journal flagged _new; push() refuses to overwrite with it unless ALLOW_NEW_JOURNAL=1,
    # so a lost pin can never wipe the history (every past journal is still in the chat as a document).
    j = dict(EMPTY, created=str(pd.Timestamp.now(tz=IST))[:16], _new=True); json.dump(j, open(out, "w"), indent=1)
    print("JOURNAL_MISSING — latest pinned message is not a journal. Re-pin the newest '📒 Journal' document in Telegram; continuing without history."); return j
def push(path, caption):
    j = json.load(open(path))
    if j.get("_new") and os.environ.get("ALLOW_NEW_JOURNAL") != "1":
        print("JOURNAL_PUSH_REFUSED — journal was not loaded from Telegram (see JOURNAL_MISSING); not overwriting the pin"); return False
    j["updated"] = str(pd.Timestamp.now(tz=IST))[:16]; json.dump(j, open(path, "w"), indent=1, default=str)
    name = f"/tmp/journal_{pd.Timestamp.now(tz=IST):%Y%m%d_%H%M}.json"; sh(f'cp "{path}" "{name}"')
    r = tg("sendDocument", f"-F chat_id={CHAT}", f'-F "document=@{name}"', f"--form-string caption={json.dumps(caption[:900])}", "-F disable_notification=true")
    mid = r.get("result", {}).get("message_id")
    if not mid: print("JOURNAL_PUSH_FAIL", r.get("description")); return False
    ok = tg("pinChatMessage", f"-d chat_id={CHAT}", f"-d message_id={mid}", "-d disable_notification=true").get("ok")
    print("JOURNAL_PUSHED" if ok else "JOURNAL_PUSHED_NOT_PINNED", mid); return ok

def daily(sym, rng="6mo"):
    try:
        r = json.loads(sh(f'curl -sS -m 30 -A "{UA}" "https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}.NS?range={rng}&interval=1d"'))["chart"]["result"][0]
        q = r["indicators"]["quote"][0]
        d = pd.DataFrame({k: q[k] for k in ["open", "high", "low", "close"]},
                         index=pd.to_datetime(r["timestamp"], unit="s").tz_localize("UTC").tz_convert(IST).normalize().tz_localize(None)).dropna()
        d = d[~d.index.duplicated(keep="last")]
        now = pd.Timestamp.now(tz=IST); cut = now.normalize().tz_localize(None) + (pd.Timedelta(days=1) if (now.hour, now.minute) >= (15, 45) else pd.Timedelta(0))
        return d[d.index < cut]                                          # completed sessions only (today's bar counts after 15:45)
    except Exception: return None

def active(j):
    return [r for r in j["recs"] if r["status"] in ("pending", "open", "t1_partial")]
def cmd_active(jpath, W):
    j = json.load(open(jpath)); a = active(j)
    json.dump({r["symbol"]: {k: r[k] for k in ("date", "verdict", "status", "buy_lo", "buy_hi", "stop", "stop_now", "t1", "t2", "qty", "fill_px", "sessions")} for r in a},
              open(f"{W}/active.json", "w"), indent=1, default=str)
    print("ACTIVE", [(r["symbol"], r["status"], r["date"]) for r in a])

def cmd_record(jpath, W):
    j = json.load(open(jpath)); P = json.load(open(f"{W}/plan.json")); N = json.load(open(f"{W}/notes.json"))
    M = json.load(open(f"{W}/master.json")) if os.path.exists(f"{W}/master.json") else {}
    O = json.load(open(f"{W}/overnight.json")) if os.path.exists(f"{W}/overnight.json") else {}
    today = str(pd.Timestamp.now(tz=IST).date()); act = {r["symbol"] for r in active(j)}
    SL = {r["symbol"]: r for r in M.get("shortlist", [])}
    added = []
    for s, v in P["stocks"].items():
        vk = v["verdict"].upper()
        if vk.startswith("ACTIVE") or s in act: continue
        t, f, d = M.get("tech", {}).get(s, {}), M.get("fo", {}).get(s, {}), M.get("delivery", {}).get(s, {})
        fu, va, ev = M.get("results", {}).get(s, {}), M.get("valuation", {}).get(s, {}), M.get("events", {}).get(s, {})
        feat = dict(rsi=t.get("rsi"), ext20=t.get("ext20"), from_hi52=t.get("from_hi52"), atr_pct=t.get("atr_pct"), style=t.get("style"),
                    fo_today=f.get("today"), deliv_updown=d.get("updown_deliv"), pat_yoy=fu.get("pat_yoy"), cfo_to_pat=fu.get("cfo_to_pat"),
                    eps_rev30=va.get("eps_+1y_rev30") if va.get("eps_+1y_rev30") is not None else va.get("eps_0y_rev30"),
                    pe_vs_hist=va.get("pe_vs_hist"), price_vs_target=va.get("price_vs_target"), rule_score=M.get("verdict", {}).get(s, {}).get("score"),
                    screen_score=SL.get(s, {}).get("score"), cap=SL.get(s, {}).get("cap"), industry=SL.get(s, {}).get("industry"),
                    catalyst=s in O.get("catalyst_symbols", []), regime_above200=P["risk_pct"] >= 1, results_days=ev.get("results_in_trading_days"))
        if vk.startswith("BUY"):
            em = (v["buy_lo"] + v["buy_hi"])/2; rps = em - v["stop"]
            qty = min(int(P["capital"]*P["risk_pct"]/100/rps), int(0.25*P["capital"]/em)) if rps > 0 else 0
            if vk.startswith("BUY SMALL"): qty //= 2
            j["recs"].append(dict(id=f"{today}:{s}", date=today, symbol=s, verdict=v["verdict"], buy_lo=v["buy_lo"], buy_hi=v["buy_hi"], stop=v["stop"],
                                  stop_now=v["stop"], t1=v["t1"], t2=v["t2"], qty=qty, ref_close=v["prev_close"], why=N.get("stocks", {}).get(s, {}).get("why"),
                                  features=feat, status="pending", fill_date=None, fill_px=None, exit_date=None, exit_px=None, exit_reason=None,
                                  half_booked=False, r_mult=None, mfe_r=None, mae_r=None, sessions=0, last_bar=None))
            added.append(s)
        else:
            j["watch"].append(dict(date=today, symbol=s, verdict=v["verdict"], reason=N.get("stocks", {}).get(s, {}).get("reason"),
                                   ref_close=v["prev_close"], features=feat, ret_1d=None, ret_5d=None, nifty_1d=None, nifty_5d=None,
                                   levels={k: v[k] for k in ("buy_lo", "buy_hi", "stop", "t1", "t2", "prev_close") if k in v}))
    for s in O.get("catalyst_symbols", []):                      # track overnight catalysts even if not shortlisted -> learn if they work
        if s not in P["stocks"]:
            j["watch"].append(dict(date=today, symbol=s, verdict="CATALYST", reason=next((f["cat"] for f in O["filings"] if f["symbol"] == s), ""),
                                   ref_close=None, features=dict(catalyst=True), ret_1d=None, ret_5d=None, nifty_1d=None, nifty_5d=None))
    prior = [r for r in active(j) if r["date"] != today]
    for r in prior:                                              # 09:30 check must re-validate live orders/positions too
        if r["symbol"] not in P["stocks"] or P["stocks"][r["symbol"]]["verdict"].upper().startswith(("WATCH", "WAIT", "AVOID")):
            P["stocks"][r["symbol"]] = dict(verdict=f"ACTIVE {r['status'].upper()} (from {r['date']})", buy_lo=r["buy_lo"], buy_hi=r["buy_hi"],
                                            stop=r["stop_now"], t1=r["t1"], t2=r["t2"], prev_close=r.get("ref_close"), in_fo=False)
    json.dump(P, open(f"{W}/plan.json", "w"), indent=1); json.dump(j, open(jpath, "w"), indent=1, default=str)
    print("RECORDED new recs:", added, "| watch entries:", len(j["watch"]), "| carried-over merged into plan:", [r["symbol"] for r in prior])

def walk(r, bars):
    """Advance one rec through daily bars after its last processed bar. Stop is checked before targets (conservative)."""
    for dt, b in bars.iterrows():
        if r["last_bar"] and dt <= pd.Timestamp(r["last_bar"]): continue
        r["last_bar"] = str(dt.date()); r["sessions"] += 1
        if r["status"] == "pending":
            if b.low <= r["buy_hi"]:
                r["fill_px"] = round(min(b.open, r["buy_hi"]), 2); r["fill_date"] = str(dt.date()); r["status"] = "open"; r["sessions"] = 1
                r["R"] = r["fill_px"] - r["stop"]
            else:
                r["max_above_zone_pct"] = round(max(r.get("max_above_zone_pct") or -99, (b.high/r["buy_hi"] - 1)*100), 2)   # how far it ran without us
                if r["sessions"] >= EXPIRY:
                    r["status"] = "expired"; r["exit_reason"] = "not filled in 10 sessions"; r["exit_date"] = str(dt.date())
                    r["missed_move_pct"] = round((b.close/r["buy_hi"] - 1)*100, 2)
                continue
        e, R = r["fill_px"], r.get("R") or (r["fill_px"] - r["stop"])
        if R <= 0: r["status"] = "closed"; r["exit_reason"] = "bad levels"; continue
        r["mfe_r"] = round(max(r["mfe_r"] or -9, (b.high - e)/R), 2); r["mae_r"] = round(min(r["mae_r"] or 9, (b.low - e)/R), 2)
        if b.low <= r["stop_now"]:                               # stop (gap-down fills at open)
            px = min(r["stop_now"], b.open); rr = (px - e)/R
            r["r_mult"] = round(0.5*(r["t1"] - e)/R + 0.5*rr, 2) if r["half_booked"] else round(rr, 2)
            r.update(status="closed", exit_px=round(px, 2), exit_date=str(dt.date()), exit_reason="stop after T1 (breakeven)" if r["half_booked"] else "stop"); continue
        if not r["half_booked"] and b.high >= r["t1"]:
            r["half_booked"] = True; r["status"] = "t1_partial"; r["stop_now"] = e; r["t1_date"] = str(dt.date())
        if r["half_booked"] and b.high >= r["t2"]:
            r["r_mult"] = round(0.5*(r["t1"] - e)/R + 0.5*(r["t2"] - e)/R, 2); r.update(status="closed", exit_px=r["t2"], exit_date=str(dt.date()), exit_reason="T2"); continue
        if r["sessions"] >= MAXHOLD:
            rr = (b.close - e)/R; r["r_mult"] = round(0.5*(r["t1"] - e)/R + 0.5*rr, 2) if r["half_booked"] else round(rr, 2)
            r.update(status="closed", exit_px=round(b.close, 2), exit_date=str(dt.date()), exit_reason="60-session time stop"); continue
        r["mark_r"] = round(((0.5*(r["t1"] - e) + 0.5*(b.close - e)) if r["half_booked"] else (b.close - e))/R, 2); r["last_close"] = round(b.close, 2)
def cmd_update(jpath):
    j = json.load(open(jpath)); cache = {}
    get = lambda s: cache.setdefault(s, daily(s))
    for r in j["recs"]:
        if r["status"] in ("pending", "open", "t1_partial"):
            b = get(r["symbol"])
            if b is not None: walk(r, b[b.index >= pd.Timestamp(r["date"])])
    try:
        nr = json.loads(sh(f'curl -sS -A "{UA}" "https://query2.finance.yahoo.com/v8/finance/chart/%5ENSEI?range=6mo&interval=1d"'))["chart"]["result"][0]
        nb = pd.Series(nr["indicators"]["quote"][0]["close"], index=pd.to_datetime(nr["timestamp"], unit="s").tz_localize("UTC").tz_convert(IST).normalize().tz_localize(None)).dropna()
    except Exception: nb = None
    for w in j["watch"]:                                          # 1-day and 5-day outcome of non-buy calls (were the vetoes right?)
        if w.get("ret_5d") is not None: continue
        b = get(w["symbol"])
        if b is None: continue
        after = b[b.index >= pd.Timestamp(w["date"])]
        before = b[b.index < pd.Timestamp(w["date"])]
        if not len(before) or not len(after): continue
        ref = w.get("ref_close") or before.close.iloc[-1]; w["ref_close"] = round(ref, 2)
        w["ret_1d"] = round((after.close.iloc[0]/ref - 1)*100, 2)
        if len(after) >= 5: w["ret_5d"] = round((after.close.iloc[4]/ref - 1)*100, 2)
        if nb is not None:
            na, nbf = nb[nb.index >= pd.Timestamp(w["date"])], nb[nb.index < pd.Timestamp(w["date"])]
            if len(na) and len(nbf):
                w["nifty_1d"] = round((na.iloc[0]/nbf.iloc[-1] - 1)*100, 2)
                if len(na) >= 5: w["nifty_5d"] = round((na.iloc[4]/nbf.iloc[-1] - 1)*100, 2)
    json.dump(j, open(jpath, "w"), indent=1, default=str)
    print("UPDATED", {s: sum(r["status"] == s for r in j["recs"]) for s in ("pending", "open", "t1_partial", "closed", "expired")})

def cmd_plan(jpath, W, capital=1_000_000):
    j = json.load(open(jpath)); today = str(pd.Timestamp.now(tz=IST).date()); st = {}
    for r in active(j):
        new = r["date"] == today
        st[r["symbol"]] = dict(verdict=r["verdict"] if new else f"ACTIVE {r['status'].upper()} (from {r['date']})", group="NEW" if new else "EARLIER",
                               buy_lo=r["buy_lo"], buy_hi=r["buy_hi"], stop=r["stop_now"], t1=r["t1"], t2=r["t2"], prev_close=r.get("ref_close"),
                               fill_px=r.get("fill_px"), why=(r.get("why") or "")[:160], in_fo=False)
    for w in j["watch"]:                                             # analysed-not-picked today -> candidates for "next opportunities"
        if w["date"] == today and w["verdict"] == "WATCH" and w.get("levels") and w["symbol"] not in st:
            st[w["symbol"]] = dict(verdict="WATCH", group="WATCH", **w["levels"])
    os.makedirs(W, exist_ok=True)
    json.dump(dict(prep_time=f"{today} 08:00:00 IST", capital=float(capital), risk_pct=1.0, max_positions=3, nifty_sma200=None, stocks=st),
              open(f"{W}/plan.json", "w"), indent=1)
    print("PLAN", {g: [s_ for s_, v in st.items() if v["group"] == g] for g in ("NEW", "EARLIER", "WATCH")})

def cmd_cancel(jpath, symbol, reason):
    """Cancel an UNFILLED order after the daily re-check (confidence no longer holds). Held positions are never cancelled here."""
    j = json.load(open(jpath)); n = 0
    for r in j["recs"]:
        if r["symbol"] == symbol and r["status"] == "pending":
            r.update(status="cancelled", exit_reason="cancelled on re-check: " + reason, exit_date=str(pd.Timestamp.now(tz=IST).date())); n += 1
    json.dump(j, open(jpath, "w"), indent=1, default=str); print("CANCELLED" if n else "NOT_PENDING", symbol, reason[:80])

def cmd_lesson(jpath, text, evidence, n, status):
    j = json.load(open(jpath))
    j["lessons"].append(dict(date=str(pd.Timestamp.now(tz=IST).date()), text=text, evidence=evidence, n=int(n), status=status))
    json.dump(j, open(jpath, "w"), indent=1, default=str); print("LESSON ADDED", status, text[:80])

if __name__ == "__main__":
    c = sys.argv[1]
    if c == "pull": pull(sys.argv[2])
    elif c == "push": push(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "journal")
    elif c == "active": cmd_active(sys.argv[2], sys.argv[3])
    elif c == "record": cmd_record(sys.argv[2], sys.argv[3])
    elif c == "update": cmd_update(sys.argv[2])
    elif c == "plan": cmd_plan(sys.argv[2], sys.argv[3], *(sys.argv[4:5]))
    elif c == "cancel": cmd_cancel(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "re-check")
    elif c == "lesson": cmd_lesson(*sys.argv[2:7])           # lesson JOURNAL "text" "evidence" n provisional|active|retired
