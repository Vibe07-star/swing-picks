"""Render phone-friendly PNG cards for Telegram (split into phone-sized pages: OUT_1.png, OUT_2.png ...).
  python3 render_cards.py plan PLAN_JSON NOTES_JSON OUT_PNG [MASTER_JSON]   (morning plan; MASTER adds the full check grid)
  python3 render_cards.py open OPEN_CHECK_JSON OUT_PNG                      (09:10 / 09:35 check)
NOTES_JSON (written by Claude after the judgment layer):
  {"date": "Tue 3 Nov 2026", "market": ["bullet", ...],
   "stocks": {"SYM": {"tag": "Mid · IT", "why": "...", "risk": "...", "filings": "one line on filings/news read", "peers": "fwd P/E 20 vs IT peers 15-26",
                      "reason": "results Nov 4 (for WAIT/WATCH/AVOID)"}},
   "unavailable": ["Insider trades (NSE PIT feed stale)", ...], "sources": "NSE filings & archives, company PDFs, Yahoo/Screener, news"}"""
import json, sys, html
from playwright.sync_api import sync_playwright
E = html.escape
VC = {"BUY": "#15803d", "BUY SMALL": "#0f766e", "WAIT": "#b45309", "WATCH": "#475569", "AVOID": "#b91c1c", "ACTIVE": "#1d4ed8"}
G, R, N_ = "#15803d", "#b91c1c", "#475569"
def vkey(v):
    v = v.upper()
    if v.startswith("ACTIVE"): return "ACTIVE"
    return "BUY SMALL" if v.startswith("BUY SMALL") else next((k for k in ("BUY", "WAIT", "WATCH", "AVOID") if v.startswith(k)), "WATCH")
def fmt(x):
    if x is None: return "–"
    return f"{x:,.0f}" if x >= 1000 else (f"{x:,.1f}" if x >= 100 else f"{x:,.2f}")
def pc(x, d=0): return "–" if x is None else f"{x:+.{d}f}%"
CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Inter,'DejaVu Sans',sans-serif;background:#f1f5f9;color:#0f172a;width:760px;padding:22px}
.hdr{background:#0f172a;color:#fff;border-radius:16px;padding:18px 22px;margin-bottom:14px}
.hdr h1{font-size:26px;font-weight:800;letter-spacing:-.3px}
.hdr .sub{font-size:15px;color:#cbd5e1;margin-top:4px}
.pill{display:inline-block;padding:5px 12px;border-radius:999px;font-weight:700;font-size:14px;margin:10px 8px 0 0}
.mk{background:#fff;border-radius:14px;padding:14px 18px;margin-bottom:14px;font-size:15px;line-height:1.5}
.mk li{margin-left:18px}
.card{background:#fff;border-radius:16px;padding:16px 18px 14px;margin-bottom:12px;border-left:10px solid #ccc}
.top{display:flex;justify-content:space-between;align-items:center}
.sym{font-size:24px;font-weight:800}.tag{font-size:13px;color:#64748b;margin-left:8px;font-weight:600}
.chip{color:#fff;font-weight:800;font-size:16px;padding:6px 14px;border-radius:10px}
.nums{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin-top:12px;text-align:center}
.nums div{background:#f8fafc;border-radius:10px;padding:7px 2px}
.nums b{display:block;font-size:18px}.nums span{font-size:11px;color:#64748b;font-weight:700;letter-spacing:.5px}
.lad{position:relative;height:90px;margin:22px 30px 4px}
.track{position:absolute;top:14px;left:0;right:0;height:6px;background:#e2e8f0;border-radius:3px}
.seg{position:absolute;top:10px;height:14px;border-radius:4px}
.mark{position:absolute;top:2px;width:3px;height:30px;border-radius:2px;transform:translateX(-50%)}
.ml{position:absolute;font-size:12px;font-weight:800;transform:translateX(-50%);white-space:nowrap;text-align:center;line-height:1.15}
.ml small{display:block;font-size:10px;font-weight:700;opacity:.8;letter-spacing:.4px}
.chk{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:10px}
.chk div{border-radius:10px;padding:6px 9px;font-size:13px;line-height:1.3;border:1.5px solid}
.chk span{display:block;font-size:10.5px;font-weight:800;letter-spacing:.5px;opacity:.85}
.chk b{font-weight:700}
.txt{font-size:14.5px;line-height:1.45;margin-top:8px}.txt b{font-weight:800}
.act{font-size:19px;font-weight:800;margin-top:10px}
.small{font-size:13px;color:#475569;margin-top:6px}
.rest{background:#fff;border-radius:14px;padding:12px 18px;margin-bottom:10px;font-size:14.5px;line-height:1.55}
.rest h3{font-size:16px;margin-bottom:4px}
.foot{font-size:12px;color:#64748b;text-align:center;margin-top:8px}
.warn{background:#fef2f2;color:#991b1b;border-radius:12px;padding:10px 16px;font-weight:700;margin-bottom:12px;font-size:15px}
"""
def ladder(stop, lo, hi, t1, t2, price):
    """Price bar with every level labelled: NOW above; SL & T1 on row 1 below, ZONE & T2 on row 2 below (avoids overlaps)."""
    a = min(stop, price) * 0.995; b = max(t2, price) * 1.005; X = lambda v: (v - a) / (b - a) * 100
    lab = lambda v, top, col, name, val: f'<div class="ml" style="left:{X(v):.1f}%;top:{top}px;color:{col}"><small>{name}</small>{val}</div>'
    return f"""<div class="lad"><div class="track"></div>
<div class="seg" style="left:{X(stop):.1f}%;width:{X(lo)-X(stop):.1f}%;background:#fecaca"></div>
<div class="seg" style="left:{X(lo):.1f}%;width:{max(X(hi)-X(lo),1.2):.1f}%;background:#22c55e"></div>
<div class="seg" style="left:{X(hi):.1f}%;width:{X(t2)-X(hi):.1f}%;background:#dbeafe"></div>
<div class="mark" style="left:{X(stop):.1f}%;background:#dc2626"></div><div class="mark" style="left:{X(t1):.1f}%;background:#2563eb"></div>
<div class="mark" style="left:{X(t2):.1f}%;background:#1e3a8a"></div>
<div class="mark" style="left:{X(price):.1f}%;background:#0f172a;width:5px"></div>
<div class="ml" style="left:{X(price):.1f}%;top:-17px;color:#0f172a">NOW {fmt(price)}</div>
{lab(stop, 34, '#dc2626', 'STOP', fmt(stop))}{lab(t1, 34, '#2563eb', 'T1', fmt(t1))}
{lab((lo+hi)/2, 56, '#15803d', 'BUY ZONE', fmt(lo)+'–'+fmt(hi))}{lab(t2, 56, '#1e3a8a', 'T2', fmt(t2))}</div>"""
def tile(name, val, good):
    c = G if good is True else (R if good is False else N_)
    bg = "#f0fdf4" if good is True else ("#fef2f2" if good is False else "#f8fafc")
    return f'<div style="border-color:{c};background:{bg};color:{c}"><span>{name}</span><b>{E(val)}</b></div>'
def checks(m, s):
    """Every quantitative check from master.json as a coloured tile (green good / red bad / grey neutral or missing)."""
    fu, va, sh = m["results"].get(s, {}), m["valuation"].get(s, {}), m["holding"].get(s, {})
    fo, dl, ev, pf, te = m["fo"].get(s, {}), m["delivery"].get(s, {}), m["events"].get(s, {}), m["portfolio"].get(s, {}), m["tech"].get(s, {})
    t = []
    q = (fu.get("quarter_end") or "")[:7]
    t.append(tile(f"RESULTS {q}", f"PAT {pc(fu.get('pat_yoy'))}{' (low base)' if fu.get('pat_low_base') else ''} · Rev {pc(fu.get('rev_yoy'))}", None if fu.get("pat_yoy") is None else fu["pat_yoy"] > 0))
    mg = fu.get("ebitda_m"); mly = fu.get("ebitda_m_ly")
    if fu.get("bank"):
        t.append(tile("BANK CORE", f"NII {pc(fu.get('nii_yoy'))} · PPOP {pc(fu.get('ppop_yoy'))} · prov {pc(fu.get('provisions_yoy'))}", None if fu.get("nii_yoy") is None else fu["nii_yoy"] > 0))
        g, gp = fu.get("gnpa_pct"), fu.get("gnpa_pct_prev")
        t.append(tile("ASSET QUALITY", (f"GNPA {g}% (prev {gp}%) · NNPA {fu.get('nnpa_pct')}%" if g is not None else "GNPA not in consolidated filing"), None if g is None or gp is None else g <= gp))
    else:
        t.append(tile("MARGIN", f"EBITDA {mg}% (LY {mly}%)" if mg else "–", None if not (mg and mly) else mg >= mly))
        cp = fu.get("cfo_to_pat"); fin = "Financial" in str((m.get("shortlist_ind") or {}).get(s, ""))
        t.append(tile("CASH FLOW", "n/a for lenders/brokers" if fin else (f"CFO/PAT {cp} · FCF ₹{fmt(fu.get('fcf_cr'))} cr" if cp is not None else "–"),
                      None if (fin or cp is None) else (True if cp >= 0.9 else (False if cp < 0.5 else None))))
    nd = None if fu.get("bank") else fu.get("net_debt_cr")
    if fu.get("bank"): t.append(tile("BALANCE SHEET", "n/a for banks (see asset quality)", None))
    else: t.append(tile("BALANCE SHEET", ("Net cash ₹" + fmt(-nd) + " cr") if nd is not None and nd < 0 else (f"Net debt ₹{fmt(nd)} cr · D/E {fu.get('debt_equity')}" if nd is not None else "–"), None if nd is None else nd < 0 or (fu.get("debt_equity") or 0) < 0.5))
    rv = va.get("eps_+1y_rev30") if va.get("eps_+1y_rev30") is not None else va.get("eps_0y_rev30")
    t.append(tile("EPS ESTIMATES 30D", pc(rv, 1) if rv is not None else "–", None if rv is None else (True if rv > 1 else (False if rv < -2 else None))))
    pt = va.get("price_vs_target")
    t.append(tile("ANALYST TARGET", f"₹{fmt(va.get('target_median'))} ({pc(-pt if pt is not None else None)} upside) · {va.get('n_analysts') or '–'} analysts" if pt is not None else "–", None if pt is None else (True if pt <= 0 else (False if pt > 10 else None))))
    pv = va.get("pe_vs_hist")
    t.append(tile("VALUATION", f"P/E {va.get('pe_ttm')} vs own {va.get('pe_hist_median')} · fwd {va.get('fwd_pe') or '–'}" if pv else "–", None if pv is None else (True if pv <= 1.2 else (False if pv > 1.5 else None))))
    ic = (sh.get("fii_chg") or 0) + (sh.get("dii_chg") or 0)
    t.append(tile(f"HOLDING {sh.get('as_of','')[3:]}", f"FII {pc(sh.get('fii_chg'),2)} · DII {pc(sh.get('dii_chg'),2)} · Prom {sh.get('promoter_action','–')}",
                  False if sh.get("promoter_action") == "SOLD" or ic < -0.5 else (True if ic > 0.5 else None)))
    t.append(tile("PLEDGE / BIG DEALS", f"Pledge {sh.get('pledge','–')} · {len(sh.get('sast') or [])} SAST · {len(sh.get('deals') or [])} deals", False if sh.get("pledge", "none").startswith(tuple("123456789")) else None))
    ft = fo.get("today")
    t.append(tile("FUTURES TODAY", ft or ("not in F&O" if not fo.get("in_fo") else "–"), None if not ft else ft in ("Long build-up", "Short covering")))
    t.append(tile("OPTIONS", f"PCR {fo.get('pcr','–')} · R {fo.get('max_call_oi','–')} · S {fo.get('max_put_oi','–')} · IV {fo.get('atm_iv','–')}" if fo.get("in_fo") else "not in F&O", None))
    ud = dl.get("updown_deliv")
    t.append(tile(f"DELIVERY {dl.get('date','')[5:]}", f"{dl.get('deliv_last','–')}% (avg {dl.get('deliv_avg','–')}%) · up/down {ud}", None if ud is None else (True if ud >= 1.2 else (False if ud < 0.9 else None))))
    t.append(tile("TECHNICAL", f"RSI {te.get('rsi')} · {te.get('trend')} · {pc(te.get('from_hi52'),1)} from 52w hi", True if te.get("trend") == "UP" and (te.get("rsi") or 0) <= 70 else (False if (te.get("rsi") or 0) > 75 or te.get("trend") == "DOWN" else None)))
    nr = ev.get("next_results"); ua = ev.get("upcoming_actions") or []
    t.append(tile("EVENTS", (f"Results {nr}" if nr else "No results date") + (f" · {len(ua)} corp action" if ua else "") + (f" · past moves ±{ev.get('median_abs_results_move')}%" if ev.get("median_abs_results_move") else ""),
                  False if ev.get("results_in_trading_days") is not None and ev["results_in_trading_days"] <= 5 else None))
    mc = pf.get("most_correlated") or {}
    t.append(tile("PORTFOLIO", f"β {pf.get('beta')} · vol {pf.get('vol')}% · moves with " + ", ".join(f"{k} {v}" for k, v in list(mc.items())[:2]), None))
    return '<div class="chk">' + "".join(t) + "</div>"
def shot(body, out, max_h=1150):
    page = f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body}</body></html>"
    files = []
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(viewport={"width": 760, "height": 400}, device_scale_factor=2)
        pg.set_content(page)
        boxes = pg.evaluate("[...document.body.children].map(e=>{const r=e.getBoundingClientRect();return [r.top,r.bottom]})")
        pages, start, end = [], None, None
        for top, bot in boxes:
            if start is None: start = top
            if bot - start > max_h and end is not None: pages.append((start, end)); start = top
            end = bot
        if start is not None: pages.append((start, end))
        stem = out[:-4] if out.endswith(".png") else out
        for i, (t, e) in enumerate(pages, 1):
            f = f"{stem}_{i}.png"; pg.screenshot(path=f, full_page=True, clip=dict(x=0, y=max(t-10, 0), width=760, height=e-t+20)); files.append(f)
        b.close()
    print("\n".join(files))

def plan_card(P, N, out, M=None):
    reg = "Nifty ABOVE 200-DMA" if P["risk_pct"] >= 1 else "Nifty BELOW 200-DMA"
    h = f"""<div class="hdr"><h1>Swing plan · {E(N.get('date',''))}</h1><div class="sub">Prepared {E(P['prep_time'])} · capital ₹{P['capital']:,.0f}</div>
<span class="pill" style="background:{'#16a34a' if P['risk_pct']>=1 else '#dc2626'}">{reg}</span>
<span class="pill" style="background:#334155">Risk {P['risk_pct']}% / trade</span><span class="pill" style="background:#334155">Max {P['max_positions']} new</span></div>"""
    if N.get("market"): h += "<div class='mk'><ul>" + "".join(f"<li>{E(m)}</li>" for m in N["market"]) + "</ul></div>"
    buys = [(s, v) for s, v in P["stocks"].items() if vkey(v["verdict"]) in ("BUY", "BUY SMALL")]
    order = {"BUY": 0, "BUY SMALL": 1}; tot_risk = 0
    h += "<div class='rest'><h3>New picks</h3>" + (f"{len(buys)} confident pick{'s' if len(buys) > 1 else ''} today." if buys else "No confident new pick today.") + "</div>"
    for s, v in sorted(buys, key=lambda kv: order[vkey(kv[1]["verdict"])]):
        k = vkey(v["verdict"]); c = VC[k]; n = N.get("stocks", {}).get(s, {})
        em = (v["buy_lo"] + v["buy_hi"]) / 2; rps = em - v["stop"]
        qty = min(int(P["capital"] * P["risk_pct"] / 100 / rps), int(0.25 * P["capital"] / em)) if rps > 0 else 0   # risk-based, max 25% of capital
        if k == "BUY SMALL": qty //= 2
        tot_risk += qty * rps
        h += f"""<div class="card" style="border-left-color:{c}"><div class="top"><div><span class="sym">{E(s)}</span><span class="tag">{E(n.get('tag',''))}</span></div>
<span class="chip" style="background:{c}">{k}</span></div>
<div class="nums"><div><span>BUY ZONE</span><b style="color:#15803d">{fmt(v['buy_lo'])}–{fmt(v['buy_hi'])}</b></div><div><span>STOP</span><b style="color:#dc2626">{fmt(v['stop'])}</b></div>
<div><span>TARGET 1</span><b style="color:#2563eb">{fmt(v['t1'])}</b></div><div><span>TARGET 2</span><b style="color:#1e3a8a">{fmt(v['t2'])}</b></div>
<div><span>QTY</span><b>{qty}</b></div></div>{ladder(v['stop'], v['buy_lo'], v['buy_hi'], v['t1'], v['t2'], v['prev_close'])}
<div class="small">Risk ₹{qty*rps:,.0f} ({(rps/em*100):.1f}% to stop) · ₹{qty*em:,.0f} deployed · R:R {((v['t1']-em)/rps):.1f} to T1 · last close {fmt(v['prev_close'])}</div>
{f"<div class='txt'><b>Why:</b> {E(n['why'])}</div>" if n.get('why') else ''}{f"<div class='txt'><b>Risk:</b> {E(n['risk'])}</div>" if n.get('risk') else ''}
{f"<div class='txt'><b>Filings/news:</b> {E(n['filings'])}</div>" if n.get('filings') else ''}{f"<div class='txt'><b>Peers:</b> {E(n['peers'])}</div>" if n.get('peers') else ''}
{checks(M, s) if M else ''}</div>"""
    act = [(s_, v) for s_, v in P["stocks"].items() if vkey(v["verdict"]) == "ACTIVE"]
    if act:
        h += "<div class='rest'><h3>Earlier picks — re-checked today</h3>Separate from new picks. Each one re-analysed with today's data.</div>"
        def dec(s_, v):
            r = (N.get("stocks", {}).get(s_, {}).get("reason") or "").strip(); u = r.upper()
            if "CANCEL" in v["verdict"].upper() or u.startswith("CANCEL"): return "CANCEL", "#b91c1c", r
            if u.startswith(("HOLD", "EXIT", "BOOK")) or "OPEN" in v["verdict"].upper() or "T1_PARTIAL" in v["verdict"].upper(): return "HOLD", "#0f766e", r
            return "KEEP", "#15803d", r
        rank = {"HOLD": 0, "KEEP": 1, "CANCEL": 2}
        for s_, v in sorted(act, key=lambda kv: rank[dec(*kv)[0]]):
            d, c, r = dec(s_, v); frm = v["verdict"].split("(from ")[-1].rstrip(")") if "(from" in v["verdict"] else ""
            px = (M or {}).get("tech", {}).get(s_, {}).get("live") or v.get("prev_close")
            h += f"""<div class="card" style="border-left-color:{c}"><div class="top"><div><span class="sym">{E(s_)}</span><span class="tag">picked {E(frm)}</span></div>
<span class="chip" style="background:{c}">{d}</span></div>
<div class="act" style="color:{c}">{E(r or d)}</div>
<div class="nums"><div><span>BUY ZONE</span><b style="color:#15803d">{fmt(v['buy_lo'])}–{fmt(v['buy_hi'])}</b></div><div><span>STOP</span><b style="color:#dc2626">{fmt(v['stop'])}</b></div>
<div><span>TARGET 1</span><b style="color:#2563eb">{fmt(v['t1'])}</b></div><div><span>TARGET 2</span><b style="color:#1e3a8a">{fmt(v['t2'])}</b></div>
<div><span>LAST</span><b>{fmt(px)}</b></div></div>{ladder(v['stop'], v['buy_lo'], v['buy_hi'], v['t1'], v['t2'], px) if px else ''}
{checks(M, s_) if (M and d != "CANCEL" and s_ in (M.get("tech") or {})) else ''}</div>"""
    if N.get("overnight"):
        h += "<div class='rest'><h3>Since yesterday's close</h3>" + "<br>".join("• " + E(x) for x in N["overnight"]) + "</div>"
    if not buys: h += "<div class='warn'>No confident new pick today — earlier orders as listed, otherwise stay in cash.</div>"
    else: h += f"<div class='rest'><b>Total risk if all filled:</b> ₹{tot_risk:,.0f} ({tot_risk/P['capital']*100:.1f}% of capital)</div>"
    nb = [s for s, v in P["stocks"].items() if vkey(v["verdict"]) in ("WAIT", "WATCH", "AVOID")]
    wt = [(s, N.get("stocks", {}).get(s, {}).get("reason", "")) for s, v in P["stocks"].items() if vkey(v["verdict"]) == "WAIT"]
    if wt: h += "<div class='rest'><b style='color:#64748b'>Waiting on an event</b> · " + " · ".join(f"<b>{E(s)}</b>{(' ('+E(r)+')') if r else ''}" for s, r in wt) + "</div>"
    if nb: h += f"<div class='rest'><b>Not picked:</b> {len(nb)} other analysed names did not clear the confidence bar (tracked in the journal for learning).</div>"
    rg = (M or {}).get("market", {}).get("regime", {})
    if rg.get("passed_filters"):
        h += (f"<div class='rest'><b>Screen:</b> {rg['passed_filters']} stocks passed today's momentum filters; the top {rg.get('shortlist_size', 20)} were analysed."
              + (" <b>Rested</b> (top-ranked 3+ days, nothing new): " + " · ".join(E(s_) for s_ in rg["rested"]) if rg.get("rested") else "") + "</div>")
    h += """<div class='rest'><h3>Trade rules</h3>Buy only inside the green zone (limit order, valid 10 sessions) · exit on a daily close below STOP (intraday for small caps)
· book half at T1 and move stop to entry · exit the rest at T2 or after 60 sessions · never chase above the zone.</div>"""
    asof = f"Prepared {E(P['prep_time'])}"
    if M:
        d = next(iter(M["delivery"].values()), {}).get("date", "–"); r = M["market"]["regime"]
        asof += f" · prices to {E(r.get('last_completed','–'))} close · delivery data {E(d)} · Nifty {fmt(r.get('nifty_live'))} vs 200-DMA {fmt(r.get('sma200'))}"
    un = N.get("unavailable") or []
    h += f"<div class='rest'><h3>Data</h3>{asof}{('<br><b>Not available:</b> ' + ' · '.join(E(x) for x in un)) if un else ''}<br><b>Sources:</b> {E(N.get('sources','NSE filings, archives & option chain; company PDFs; Yahoo/Screener; news'))}</div>"
    h += "<div class='foot'>Tiles: green = supports the trade · red = against · grey = neutral/missing. Not investment advice; backtested edge is thin when Nifty is below its 200-DMA.</div>"
    shot(h, out)

ACT = [("DROP", "#b91c1c", "DROP — STOP HIT"), ("SKIP", "#64748b", "SKIP — AT TARGET"), ("WAIT", "#64748b", "WAIT — EVENT"),
       ("ABOVE", "#d97706", "DON'T CHASE — LIMIT IN ZONE"), ("IN ZONE", "#15803d", "BUY NOW"), ("BELOW", "#ea580c", "WAIT — BUY ONLY ON RECLAIM"),
       ("NO PRICE", "#64748b", "NO PRICE — CHECK")]
def open_card(O, out):
    """09:31 card: short market strip, then NEW and EARLIER sections. Confident names get the full buy/stop/target card;
    everything else is one line. Then next opportunities."""
    nc = O.get("nifty_chg") or 0; vc = O.get("vix_chg") or 0; M = O.get("market") or {}
    tone = M.get("tone", ""); tc = {"strong": "#16a34a", "weak": "#dc2626"}.get(tone, "#b45309")
    h = f"""<div class="hdr"><h1>Live check · {E(O['time'][-9:])}</h1><div class="sub">{E(O['time'])} · live prices</div>
<span class="pill" style="background:{'#16a34a' if nc>=0 else '#dc2626'}">NIFTY {fmt(O.get('nifty'))} ({nc:+.2f}%)</span>
<span class="pill" style="background:{'#dc2626' if vc>=5 else '#334155'}">VIX {fmt(O.get('vix'))} ({vc:+.1f}%)</span>
{f'<span class="pill" style="background:{tc}">Market {E(tone.upper())}</span>' if tone else ''}</div>"""
    bits = []
    if M.get("advances") is not None: bits.append(f"{M['advances']} up / {M['declines']} down")
    if M.get("sector_leaders"): bits.append("leading " + ", ".join(f"{E(n.title())} {c:+.1f}%" for n, c in M["sector_leaders"][:2]))
    if M.get("sector_laggards"): bits.append("lagging " + ", ".join(f"{E(n.title())} {c:+.1f}%" for n, c in M["sector_laggards"][:2]))
    if M.get("nifty_vs_range"): bits.append("Nifty " + E(M["nifty_vs_range"]))
    if bits or O.get("read"): h += "<div class='mk'>" + "".join(f"{E(x)}<br>" for x in O.get("read", [])) + " · ".join(bits) + "</div>"
    for c in O.get("caution", []): h += f"<div class='warn'>⚠ {E(c)}</div>"
    def status(r):
        a = r.get("action", ""); z = r.get("zone", "").replace(".0", "")
        if r.get("confident"):
            return ("#2563eb", "BUY NOW — above zone, moving to target") if a.startswith("MOVING") else ("#15803d", "BUY NOW — in buy zone, confirmed")
        if a.startswith("HELD"): return ("#b91c1c" if "exit" in a else "#15803d" if "T1" in a else "#0f766e"), "HOLDING — " + a.split(" - ", 1)[1]
        if "NO PRICE" in a: return "#64748b", "No live price — check manually"
        if a.startswith("HOLD"): return "#7c3aed", "New filing — read before acting"
        if "DROP" in a: return "#b91c1c", "Stop hit — cancel the order"
        if "cancel the order" in a: return "#b91c1c", "Hit target without filling — cancel"
        if "ABOVE" in a: return "#d97706", "Above zone, not confirmed — limit order stays"
        if "BELOW" in a: return "#ea580c", "Below zone — buy only if it gets back into the zone"
        if "WAIT" in a: return "#64748b", "Event pending — no entry"
        return "#0f766e", "In zone, not confirmed yet — wait (" + ", ".join(r.get("doubts") or []) + ")"
    def card(r):
        if not r.get("price"): return f"<div class='rest'><b>{E(r['symbol'])}</b> — no live price</div>"
        col, lab = status(r); lo, hi = [float(x) for x in r["zone"].split("-")]; buy = r.get("confident")
        held = r.get("action", "").startswith("HELD")
        chip = "BUY" if buy else ("HOLD" if held else ("CANCEL" if col == "#b91c1c" else "WAIT"))
        last = f"<div><span>QTY</span><b>{r['qty']}</b></div>" if buy else (f"<div><span>BOUGHT AT</span><b>{fmt(r.get('fill_px'))}</b></div>" if held and r.get('fill_px') else "")
        return f"""<div class="card" style="border-left-color:{col}"><div class="top"><span class="sym">{E(r['symbol'])}</span><span class="chip" style="background:{col}">{chip}</span></div>
<div class="act" style="color:{col}">{E(lab)}</div>
<div class="nums"><div><span>NOW</span><b>{fmt(r['price'])} <small style="color:{'#15803d' if r.get('gap_pct',0)>=0 else '#dc2626'}">{r.get('gap_pct',0):+.1f}%</small></b></div><div><span>BUY ZONE</span><b style="color:#15803d">{fmt(lo)}–{fmt(hi)}</b></div>
<div><span>STOP</span><b style="color:#dc2626">{fmt(r['stop'])}</b></div><div><span>TARGET 1</span><b style="color:#2563eb">{fmt(r['t1'])}</b></div>
<div><span>TARGET 2</span><b style="color:#1e3a8a">{fmt(r.get('t2'))}</b></div>{last}</div>
{ladder(r['stop'], lo, hi, r['t1'], r.get('t2') or r['t1']*1.05, r['price'])}
{f"<div class='small'>Buy at {fmt(r.get('entry'))} · R:R {r.get('rr_t1')} to T1 · {E(', '.join(r.get('confirms') or []))}</div>" if buy else ''}
{f"<div class='txt'>{E(r['why'])}</div>" if r.get('why') and buy else ''}</div>"""
    def line(r):
        a = r.get("action", ""); z = r.get("zone", "").replace(".0", ""); b = f"<b>{E(r['symbol'])}</b> {fmt(r.get('price'))}"
        if a.startswith("HELD"): return f"{b} — holding · {E(a.split(' - ', 1)[1])}"
        if "NO PRICE" in a: return f"{b} — no live price"
        if a.startswith("HOLD"): return f"{b} — new filing, read first"
        if "DROP" in a: return f"{b} — <span style='color:#b91c1c'>stop hit, cancel</span>"
        if "cancel the order" in a: return f"{b} — <span style='color:#b91c1c'>hit target without filling, cancel</span>"
        if "ABOVE" in a: return f"{b} — above zone {E(z)}, not confirmed: limit stays"
        if "BELOW" in a: return f"{b} — below zone {E(z)}: buy only on reclaim"
        if "WAIT" in a: return f"{b} — event pending"
        return f"{b} — in zone {E(z)}, not confirmed yet ({E(', '.join(r.get('doubts') or []))}): wait"
    for g, title in (("NEW", "New picks"), ("EARLIER", "Earlier picks")):
        rs = [r for r in O["rows"] if r.get("group") == g]
        if not rs: continue
        nb = sum(1 for r in rs if r.get("confident"))
        h += f"<div class='rest'><h3>{title}</h3>" + (f"{nb} confirmed buy{'s' if nb > 1 else ''} right now." if nb else "No confirmed buy right now.") + "</div>"
        for r in sorted(rs, key=lambda r: (not r.get("confident"), not r.get("action", "").startswith("HELD"))): h += card(r)
    if O.get("opportunities"):
        h += "<div class='rest'><h3>Next opportunities — watch only</h3>" + "<br>".join(
            f"<b>{E(o['symbol'])}</b> {fmt(o['price'])} ({o['chg_pct']:+.1f}%) · volume {o['vol_pace']:.1f}× · zone {E(o['zone'])}" for o in O["opportunities"]) + "</div>"
    h += "<div class='foot'>BUY only when confirmed: above VWAP, holding the first 15-min range, normal volume, calm market. Not investment advice.</div>"
    shot(h, out)

OUTC = {"T1 HIT": "#15803d", "FILLED": "#0f766e", "NOT FILLED": "#64748b", "STOPPED": "#b91c1c"}
def eod_card(X, out, review=None):
    """X = eod.json from s6; review = {"summary": str, "went_right": [..], "went_wrong": [..], "changes": [..]} written by Claude."""
    nd = X["nifty_day"]; sc = X["score"]; rv = review or {}
    h = f"""<div class="hdr"><h1>Day review · {E(X['date'])}</h1><div class="sub">How today's calls did after the close · learning journal</div>
<span class="pill" style="background:{'#16a34a' if nd>=0 else '#dc2626'}">NIFTY {nd:+.2f}%</span>
<span class="pill" style="background:#334155">{sc['recs']} picks tracked</span><span class="pill" style="background:#334155">{len(X['open'])} open · {len(X['pending'])} orders</span></div>"""
    if rv.get("summary"): h += f"<div class='mk'>{E(rv['summary'])}</div>"
    if X["today"]:
        h += "<div class='rest'><h3>Today's picks</h3></div>"
        for r in X["today"]:
            col = OUTC.get(r["outcome"], "#475569"); lo, hi = [float(v) for v in r["zone"].split("-")]
            h += f"""<div class="card" style="border-left-color:{col}"><div class="top"><span class="sym">{E(r['symbol'])}</span>
<span class="chip" style="background:{col}">{E(r['outcome'])}</span></div>
<div class="nums"><div><span>DAY</span><b style="color:{'#15803d' if r['day_pct']>=0 else '#dc2626'}">{r['day_pct']:+.1f}%</b></div><div><span>VS NIFTY</span><b style="color:{'#15803d' if r['vs_nifty']>=0 else '#dc2626'}">{r['vs_nifty']:+.1f}%</b></div>
<div><span>DAY LOW</span><b>{fmt(r['low'])}</b></div><div><span>DAY HIGH</span><b>{fmt(r['high'])}</b></div><div><span>CLOSE</span><b>{fmt(r['close'])}</b></div></div>
{ladder(r['stop'], lo, hi, r['t1'], r['t1'] + (r['t1']-hi)*0.5, r['close'])}
<div class="small">{'Touched the buy zone' if r['touched_zone'] else 'Never reached the buy zone'} · close {r['close_vs_zone_pct']:+.1f}% vs zone top{(' · filled @'+fmt(r['fill_px'])) if r.get('fill_px') else ''}{(' · now '+format(r['mark_r'],'+.2f')+'R') if r.get('mark_r') is not None else ''}</div></div>"""
    if X["events"]: h += "<div class='rest'><h3>Earlier picks — what changed today</h3>" + "<br>".join(f"<b>{E(e['symbol'])}</b> ({E(e['rec_date'])}): {E(e['event'])}" for e in X["events"]) + "</div>"
    if X["open"]: h += "<div class='rest'><h3>Open trades</h3>" + "<br>".join(f"<b>{E(o['symbol'])}</b> in @{fmt(o['fill_px'])} · stop {fmt(o['stop_now'])} · T1 {fmt(o['t1'])} · now {fmt(o.get('last_close'))} (<b style='color:{'#15803d' if (o.get('mark_r') or 0)>=0 else '#dc2626'}'>{(o.get('mark_r') or 0):+.2f}R</b>) · day {o['sessions']}" for o in X["open"]) + "</div>"
    if X["pending"]: h += "<div class='rest'><h3>Limit orders still live</h3>" + " · ".join(f"<b>{E(p['symbol'])}</b> {E(p['zone'])} ({p['sessions_left']} sessions left)" for p in X["pending"]) + "</div>"
    if X["watch"]:
        h += "<div class='rest'><h3>Calls that were not buys</h3>" + " · ".join(
            f"<b>{E(w['symbol'])}</b> <span style='color:#64748b'>{E(w['verdict'].split()[0])}</span> {('' if w.get('ret_1d') is None else format(w['ret_1d'],'+.1f')+'%')}" for w in X["watch"]) + "</div>"
    tiles = [tile("FILL RATE", f"{sc['fill_rate'] if sc['fill_rate'] is not None else '–'}% ({sc['filled']}/{sc['recs']})", None),
             tile("CLOSED TRADES", str(sc["closed"]), None),
             tile("WIN RATE", f"{sc['win_rate']}%" if sc["win_rate"] is not None else "–", None if sc["win_rate"] is None else sc["win_rate"] >= 45),
             tile("AVG R / TRADE", f"{sc['avg_r']:+.2f}R" if sc["avg_r"] is not None else "–", None if sc["avg_r"] is None else sc["avg_r"] > 0),
             tile("REALISED", f"{sc['total_r']:+.2f}R", None if not sc["closed"] else sc["total_r"] > 0),
             tile("OPEN (MARKED)", f"{float(sc['open_mark_r']):+.2f}R", None if not X["open"] else float(sc["open_mark_r"]) > 0)]
    h += "<div class='card' style='border-left-color:#0f172a'><span class='sym' style='font-size:19px'>Scorecard (all tracked picks)</span><div class='chk'>" + "".join(tiles) + "</div>"
    if X["evidence"]:
        h += "<div class='small' style='margin-top:10px'><b>Evidence by factor</b> (avg R · win% · n) — rules change only at n ≥ 15:<br>" + " · ".join(
            f"{E(e['factor'])} <b>{E(e['bucket'])}</b>: {e['avg_r']:+.2f}R · {e['win']}% · n{e['n']}" for e in X["evidence"]) + "</div>"
    if X["watch_evidence"]:
        h += "<div class='small'><b>Non-buy calls</b> (avg move vs Nifty): " + " · ".join(f"{E(w['call'])} {w['avg_excess_1d']:+.2f}% 1d (n{w['n']})" + (f", {w['avg_excess_5d']:+.2f}% 5d" if w.get("avg_excess_5d") is not None else "") for w in X["watch_evidence"]) + "</div>"
    h += "</div>"
    for k, t in (("went_right", "What worked"), ("went_wrong", "What didn't")):
        if rv.get(k): h += f"<div class='rest'><h3>{t}</h3>" + "<br>".join("• " + E(x) for x in rv[k]) + "</div>"
    if rv.get("changes") or X["lessons"]:
        h += "<div class='rest'><h3>Learning</h3>" + "<br>".join("• " + E(x) for x in rv.get("changes", [])) + ("<br>" if rv.get("changes") and X["lessons"] else "") + "<br>".join(
            f"• <b>{E(l['status'].upper())}</b> {E(l['text'])} <span style='color:#64748b'>(n={l['n']})</span>" for l in X["lessons"]) + "</div>"
    h += "<div class='foot'>R = profit in units of the planned risk (entry − stop). Fills/stops simulated from daily bars, stop checked before target. Not investment advice.</div>"
    shot(h, out)

if __name__ == "__main__":
    if sys.argv[1] == "plan": plan_card(json.load(open(sys.argv[2])), json.load(open(sys.argv[3])), sys.argv[4], json.load(open(sys.argv[5])) if len(sys.argv) > 5 else None)
    elif sys.argv[1] == "eod": eod_card(json.load(open(sys.argv[2])), sys.argv[3], json.load(open(sys.argv[4])) if len(sys.argv) > 4 else None)
    else: open_card(json.load(open(sys.argv[2])), sys.argv[3])
