"""Send text (stdin or args) to Telegram. Splits >4000-char messages; retries; prints 'TG_OK' or 'TG_FAIL <reason>'.
Usage: echo "text" | python3 tg_send.py TOKEN CHAT_ID      or   python3 tg_send.py TOKEN CHAT_ID "text"
       python3 tg_send.py TOKEN CHAT_ID --file path        (sends a file as a document)"""
import sys, json, time, subprocess
tok, chat = sys.argv[1], sys.argv[2]
api = f"https://api.telegram.org/bot{tok}"
def call(args):
    for t in range(3):
        try:
            r = json.loads(subprocess.run(["curl", "-sS", "-m", "30"] + args, capture_output=True, text=True).stdout)
            if r.get("ok"): return True, ""
            if r.get("error_code") == 429: time.sleep(r.get("parameters", {}).get("retry_after", 3)); continue
            return False, r.get("description", "")
        except Exception as e: err = str(e); time.sleep(2)
    return False, "network"
if len(sys.argv) > 4 and sys.argv[3] == "--photos":           # --photos "caption" img1.png img2.png ... (album, max 10)
    cap, imgs = sys.argv[4], sys.argv[5:15]
    media = [dict(type="photo", media=f"attach://p{i}", **({"caption": cap[:1024]} if i == 0 else {})) for i in range(len(imgs))]
    args = [f"{api}/sendMediaGroup", "-F", f"chat_id={chat}", "-F", "media=" + json.dumps(media)]
    for i, f in enumerate(imgs): args += ["-F", f"p{i}=@{f}"]
    ok, why = call(args) if len(imgs) > 1 else call([f"{api}/sendPhoto", "-F", f"chat_id={chat}", "-F", f"caption={cap[:1024]}", "-F", f"photo=@{imgs[0]}"])
elif len(sys.argv) > 4 and sys.argv[3] == "--file":
    ok, why = call([f"{api}/sendDocument", "-F", f"chat_id={chat}", "-F", f"document=@{sys.argv[4]}"])
else:
    text = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else sys.stdin.read()
    parts, buf = [], ""
    for line in text.splitlines(keepends=True):             # split on line boundaries, 4000-char chunks
        if len(buf) + len(line) > 4000: parts.append(buf); buf = ""
        buf += line
    if buf.strip(): parts.append(buf)
    ok, why = True, ""
    for p in parts:
        o, w = call([f"{api}/sendMessage", "--data-urlencode", f"chat_id={chat}", "--data-urlencode", f"text={p}",
                     "--data-urlencode", "disable_web_page_preview=true"])
        ok, why = ok and o, why or w
print("TG_OK" if ok else f"TG_FAIL {why}")
