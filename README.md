# swing-picks

Scripts behind my daily NSE swing-trade messages on Telegram (run by scheduled Claude tasks).

| Time (IST, weekdays) | Task | Entry point |
|---|---|---|
| 08:28 | Pre-market plan: screen → data → judgment → cards | `s1`…`s4`, `journal.py record`, `render_cards.py plan` |
| 09:31 | Live check: New / Earlier picks vs the open | `bash picks/live.sh` |
| 16:07 | Day review & learning | `s6_eod_review.py`, `render_cards.py eod` |

Secrets are never stored here: `TG_TOKEN` and `TG_CHAT` come from the environment.
The trade journal lives as a pinned JSON document in the Telegram chat (`journal.py pull/push`).
