#!/usr/bin/env bash
# STEP 3 — deep data for the shortlist (NSE primary sources), parallel. Usage: bash s3_deep_fetch.sh WORKDIR
set -u
W=${1:?workdir}; cd $W; mkdir -p nse/if nse/ann nse/bm nse/ca nse/shp nse/sast nse/deals nse/oc bhav fo xbrl pdf scr px10 qs
export UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
SYMS=$(tail -n +2 shortlist.csv | cut -d, -f1)
TZ=Asia/Kolkata date "+%Y-%m-%d %H:%M:%S IST" > snapshot_time.txt
enc() { python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$1"; }; export -f enc
# trading dates from Nifty series (holiday-proof): last 60 completed sessions (today counts only after 16:00 IST)
python3 - <<'EOF' > dates.txt
import json, pandas as pd
r = json.load(open("px/_NSEI.json"))["chart"]["result"][0]
idx = pd.to_datetime(r["timestamp"], unit="s").tz_localize("UTC").tz_convert("Asia/Kolkata").normalize().tz_localize(None).unique()
now = pd.Timestamp.now(tz="Asia/Kolkata"); today = now.normalize().tz_localize(None) + (pd.Timedelta(days=1) if now.hour >= 16 else pd.Timedelta(0))
done = [d for d in idx if d < today][-60:]
print(" ".join(d.strftime("%d%m%Y") for d in done))
EOF
DATES=$(cat dates.txt); LAST=$(echo $DATES | awk '{print $NF}')
export FROM35=$(TZ=Asia/Kolkata date -d "35 days ago" +%d-%m-%Y) FROM95=$(TZ=Asia/Kolkata date -d "95 days ago" +%d-%m-%Y) TODAY=$(TZ=Asia/Kolkata date +%d-%m-%Y)
get() { [ -s "$2" ] || curl -sS -A "$UA" -o "$2" "$1"; }; export -f get

# --- NSE archives (no cookie) : bhavcopies, F&O bhavcopy, participant OI, MWPL ---
{
  for d in $DATES; do echo "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_$d.csv bhav/$d.csv"; done
  for d in $(echo $DATES | tr ' ' '\n' | tail -5); do y=${d:4:4}${d:2:2}${d:0:2}
    echo "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_${y}_F_0000.csv.zip fo/$y.zip"
    echo "https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_$d.csv fo/part_$d.csv"; done
  echo "https://nsearchives.nseindia.com/archives/nsccl/mwpl/combineoi_$LAST.zip fo/mwpl_$LAST.zip"
} | xargs -P 8 -L 1 bash -c 'get "$0" "$1"'
(cd fo && for z in BhavCopy*.zip [0-9]*.zip; do [ -f "$z" ] && unzip -o -q "$z" 2>/dev/null; done; unzip -o -q mwpl_$LAST.zip -d mwpl 2>/dev/null)

# --- NSE APIs: one cookie, then read-only parallel calls (4 at a time) ---
curl -sS -A "$UA" -c ck.txt -o /dev/null "https://www.nseindia.com/option-chain"
nse() { curl -sS -A "$UA" -b "$PWD/ck.txt" -H "Accept: application/json" -H "Referer: https://www.nseindia.com/$1" -o "$3" "https://www.nseindia.com/api/$2"; }; export -f nse
{
  echo " allIndices nse/allIndices.json"
  echo " fiidiiTradeReact nse/fiidii.json"
  echo "market-data/oi-spurts live-analysis-oi-spurts-underlyings nse/spurts.json"
  echo " event-calendar?index=equities nse/event_calendar.json"
  echo "option-chain option-chain-contract-info?symbol=NIFTY nse/oc/NIFTY_ci.json"
  for s in $SYMS; do e=$(enc "$s")
    echo "companies-listing/corporate-integrated-filing integrated-filing-results?index=equities&symbol=$e&size=40 nse/if/$s.json"
    echo "companies-listing/corporate-filings-announcements corporate-announcements?index=equities&symbol=$e&from_date=$FROM35&to_date=$TODAY nse/ann/$s.json"
    echo " corporate-board-meetings?index=equities&symbol=$e nse/bm/$s.json"
    echo " corporates-corporateActions?index=equities&symbol=$e nse/ca/$s.json"
    echo " corporate-share-holdings-master?index=equities&symbol=$e nse/shp/$s.json"
    echo " corporate-sast-reg29?index=equities&symbol=$e&from_date=$FROM95&to_date=$TODAY nse/sast/$s.json"
    for t in bulk_deals block_deals; do echo "report-detail/display-bulk-and-block-deals historicalOR/bulk-block-short-deals?optionType=$t&symbol=$e&from=$FROM95&to=$TODAY nse/deals/${s}_$t.json"; done
    echo "option-chain option-chain-contract-info?symbol=$e nse/oc/${s}_ci.json"
  done
} | sed 's/^ /_ /' | xargs -P 4 -L 1 bash -c 'nse "${0#_}" "$1" "$2"'
# Screener + 10y monthly prices (P/E history), parallel
for s in $SYMS; do e=$(enc "$s")
  echo "https://www.screener.in/company/$e/consolidated/ scr/$s.html"
  echo "https://query2.finance.yahoo.com/v8/finance/chart/$e.NS?range=10y&interval=1mo px10/$(echo $s|tr '&' '_').json"
done | xargs -P 6 -L 1 bash -c 'get "$0" "$1"'

# --- option chains: stock monthly (roll if <3 days left), Nifty weekly (nearest) + monthly ---
python3 - <<'EOF' > oc_jobs.txt
import json, glob, os, urllib.parse, pandas as pd
today = pd.Timestamp.now(tz="Asia/Kolkata").normalize().tz_localize(None)
for f in glob.glob("nse/oc/*_ci.json"):
    s = os.path.basename(f)[:-8]
    try: ex = [pd.to_datetime(x, format="%d-%b-%Y") for x in json.load(open(f))["expiryDates"]]
    except Exception: continue            # not in F&O
    e = urllib.parse.quote(s)
    if s == "NIFTY":
        mon = [x for x in ex if x.month == ex[0].month]
        print(f"option-chain option-chain-v3?type=Indices&symbol=NIFTY&expiry={ex[0]:%d-%b-%Y} nse/oc/NIFTY_w.json")
        print(f"option-chain option-chain-v3?type=Indices&symbol=NIFTY&expiry={(mon[-1] if mon else ex[0]):%d-%b-%Y} nse/oc/NIFTY_m.json")
    else:
        ex = [x for x in ex if (x - today).days >= 3] or ex
        print(f"option-chain option-chain-v3?type=Equity&symbol={e}&expiry={ex[0]:%d-%b-%Y} nse/oc/{s}_m.json")
EOF
xargs -P 4 -L 1 bash -c 'nse "$0" "$1" "$2"' < oc_jobs.txt

# --- XBRL (latest 5 consolidated quarters), material PDFs, SHP XBRL (latest 2) ---
python3 - <<'EOF' > dl_jobs.txt
import json, glob, os, re
for f in glob.glob("nse/if/*.json"):
    s = os.path.basename(f)[:-5]
    try: d = json.load(open(f))["data"]
    except Exception: continue
    seen = []
    for r in d:
        if r.get("type") == "Integrated Filing- Financials" and r.get("consolidated") == "Consolidated" and r["qe_Date"] not in seen:
            seen.append(r["qe_Date"]); print(r["xbrl"], f"xbrl/{s}_{r['qe_Date']}.xml")
        if len(seen) >= 5: break
    sa = [r for r in d if r.get("type") == "Integrated Filing- Financials" and r.get("consolidated") == "Standalone" and "BANKING" in str(r.get("xbrl", ""))]
    for r in sa[:2]: print(r["xbrl"], f"xbrl/{s}_{r['qe_Date']}_SA.xml")      # banks: standalone has GNPA/NNPA
skip = re.compile(r"Newspaper|Trading Window|Certificate under SEBI|Loss of Share|Duplicate|Book Closure", re.I)
want = re.compile(r"Outcome of Board|Press Release|Transcript|Resignation|Change in Management|Change in Director|Auditor|USFDA|Form 483|Warning|Inspection|Action\(s\) taken|penalty|fine|Allotment|Qualified Institution|Preferential|Bonus|Split|Buyback|Acquisition|Credit Rating|Pledge|Fraud|Default|SEBI order", re.I)
for f in glob.glob("nse/ann/*.json"):
    s = os.path.basename(f)[:-5]
    try: d = json.load(open(f))
    except Exception: continue
    for i, r in enumerate(d):
        if skip.search(r["desc"]) or not want.search(r["desc"] + " " + r["attchmntText"]) or not r["attchmntFile"].lower().endswith(".pdf"): continue
        print(r["attchmntFile"], f"pdf/{s}_{i}.pdf")
for f in glob.glob("nse/shp/*.json"):
    s = os.path.basename(f)[:-5]
    try: d = json.load(open(f))
    except Exception: continue
    for r in d[:2]: print(r["xbrl"], f"nse/shp/{s}_{r['date']}.xml")
EOF
xargs -P 8 -L 1 bash -c 'get "$0" "$1"' < dl_jobs.txt
ls pdf/*.pdf 2>/dev/null | xargs -P 8 -I{} sh -c 'f={}; [ -s ${f%.pdf}.txt ] || pdftotext -layout $f ${f%.pdf}.txt 2>/dev/null'

# --- Yahoo consensus / estimate trend (needs crumb; HTTP 429 -> Firecrawl fallback, see SKILL.md) ---
curl -sS -A "$UA" -c yck.txt -o /dev/null "https://fc.yahoo.com"; CR=$(curl -sS -A "$UA" -b yck.txt "https://query2.finance.yahoo.com/v1/test/getcrumb")
case "$CR" in *Too*|""|*"<"*) echo "YAHOO_CRUMB_RATE_LIMITED -> use Firecrawl fallback for consensus/estimates";;
 *) export CRE=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1],safe=''))" "$CR")
    for s in $SYMS; do echo "$(enc "$s") qs/$s.json"; done | xargs -P 3 -L 1 bash -c 'curl -sS -A "$UA" -b yck.txt -o "$1" "https://query2.finance.yahoo.com/v10/finance/quoteSummary/$0.NS?modules=financialData,defaultKeyStatistics,summaryDetail,recommendationTrend,earningsTrend,earningsHistory&crumb=$CRE"';;
esac
echo "deep fetch done: $(ls xbrl | wc -l) xbrl, $(ls pdf/*.pdf 2>/dev/null | wc -l) pdfs, $(ls bhav | wc -l) bhavcopies, $(ls nse/oc | wc -l) oc files, $(ls qs | wc -l) consensus"
