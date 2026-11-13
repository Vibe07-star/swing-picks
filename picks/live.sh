#!/usr/bin/env bash
# 09:31 live check in one command: journal -> plan -> live check -> cards -> Telegram.  Usage: bash live.sh [TEST]
# Needs TG_TOKEN, TG_CHAT. Prints LIVE_OK or LIVE_FAIL <step>. Never writes to the journal.
set -u
P=$(cd "$(dirname "$0")" && pwd); W=/tmp/claude-0/live_$(TZ=Asia/Kolkata date +%Y%m%d_%H%M); J=$W/journal.json; mkdir -p $W
PRE=""; [ "${1:-}" = "TEST" ] && PRE="🧪 TEST — "
python3 $P/journal.py pull $J > $W/log.txt 2>&1 || { echo "LIVE_FAIL pull"; cat $W/log.txt; exit 1; }
grep -q JOURNAL_MISSING $W/log.txt && { python3 $P/tg_send.py "$TG_TOKEN" "$TG_CHAT" "${PRE}⏱ Live check skipped — journal not found (re-pin the latest 📒 Journal)"; echo "LIVE_FAIL journal"; exit 1; }
python3 $P/journal.py plan $J $W >> $W/log.txt 2>&1 || { echo "LIVE_FAIL plan"; tail -5 $W/log.txt; exit 1; }
python3 $P/s5_open_check.py $W/plan.json > $W/s5.txt 2>&1 || { echo "LIVE_FAIL s5"; tail -5 $W/s5.txt; exit 1; }
grep -q "mode=live" $W/s5.txt || { echo "LIVE_SKIP market not open (holiday or too early)"; exit 0; }
python3 $P/render_cards.py open $W/open_check.json $W/open.png > $W/pages.txt 2>&1 || { echo "LIVE_FAIL render"; tail -5 $W/pages.txt; exit 1; }
CAP="${PRE}$(head -1 $W/caption.txt)"
python3 $P/tg_send.py "$TG_TOKEN" "$TG_CHAT" --photos "$CAP" $(cat $W/pages.txt) | grep -q TG_OK || python3 $P/tg_send.py "$TG_TOKEN" "$TG_CHAT" --photos "${PRE}⏱ Live check" $(cat $W/pages.txt)
python3 $P/tg_send.py "$TG_TOKEN" "$TG_CHAT" "${PRE}$(cat $W/caption.txt)" >/dev/null
grep "NEW FILING" $W/s5.txt | grep "!!" > $W/filings.txt
echo "LIVE_OK workdir=$W"; cat $W/caption.txt; [ -s $W/filings.txt ] && { echo "FLAGGED FILINGS:"; cat $W/filings.txt; }
exit 0
