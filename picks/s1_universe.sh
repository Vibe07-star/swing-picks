#!/usr/bin/env bash
# STEP 1 — universe lists + 2y daily prices (Yahoo chart API, no crumb). 8 parallel downloads (~1 min).
# Usage: bash s1_universe.sh WORKDIR
set -u
W=${1:?workdir}; mkdir -p $W/px $W/lists
export UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
for L in nifty100 niftymidcap150 niftysmallcap250; do
  curl -sS -A "$UA" -o $W/lists/$L.csv "https://nsearchives.nseindia.com/content/indices/ind_${L}list.csv" &
done; wait
python3 - "$W" <<'EOF'
import pandas as pd, sys, urllib.parse
W = sys.argv[1]; rows = []
for L, cap in [("nifty100", "Large"), ("niftymidcap150", "Mid"), ("niftysmallcap250", "Small")]:
    d = pd.read_csv(f"{W}/lists/{L}.csv")
    rows += [(s, cap, ind) for s, ind in zip(d.Symbol, d.Industry)]
u = pd.DataFrame(rows, columns=["symbol", "cap", "industry"]).drop_duplicates("symbol")
u.to_csv(f"{W}/lists/universe.csv", index=False); print("universe", len(u), u.cap.value_counts().to_dict())
# job list: <yahoo symbol> <outfile>; indices + global cues + all stocks
with open(f"{W}/lists/jobs.txt", "w") as f:
    for y, n in [("^NSEI", "_NSEI"), ("^NSEBANK", "_NSEBANK"), ("^INDIAVIX", "_INDIAVIX"), ("^GSPC", "_GSPC"), ("^IXIC", "_IXIC"),
                 ("BZ=F", "_BRENT"), ("INR=X", "_USDINR"), ("^TNX", "_US10Y"), ("DX-Y.NYB", "_DXY"), ("^N225", "_N225"), ("^HSI", "_HSI")]:
        f.write(f"{urllib.parse.quote(y)} {W}/px/{n}.json\n")
    for s in u.symbol: f.write(f"{urllib.parse.quote(s)}.NS {W}/px/{s.replace('&', '_')}.json\n")
EOF
fetch() {  # $1 yahoo symbol (url-encoded), $2 outfile
  for t in 1 2 3; do
    code=$(curl -sS -A "$UA" -o "$2" -w "%{http_code}" "https://query2.finance.yahoo.com/v8/finance/chart/$1?range=2y&interval=1d&events=div,split")
    [ "$code" = 200 ] && return 0; sleep $((t*3))
  done; rm -f "$2"; echo "FAILED $1" >&2
}
export -f fetch
xargs -P 8 -L 1 bash -c 'fetch "$0" "$1"' < $W/lists/jobs.txt
echo "prices: $(ls $W/px | wc -l) files"
