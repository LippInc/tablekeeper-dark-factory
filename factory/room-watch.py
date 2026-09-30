"""Watch a Band room: print one line per new text or error message from an agent (newest page, polled).

Superseded by stage-watch.py (2026-09-28); kept for the record."""
import json, os, subprocess, sys, time

room = sys.argv[1]
interval = int(sys.argv[2]) if len(sys.argv) > 2 else 20
_win = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "jam", "bin", "jam.exe")
jam = _win if os.path.isfile(_win) else "jam"
seen = set()
first = True

def fetch(kind):
    try:
        out = subprocess.run([jam, "room", "messages", room, "--type", kind, "--json"], capture_output=True, text=True, encoding="utf-8", timeout=60)
        return json.loads(out.stdout).get("messages", [])
    except Exception as e:
        print(f"[watch] fetch {kind} failed: {e}", flush=True)
        return []

while True:
    msgs = fetch("text") + fetch("error")
    msgs.sort(key=lambda m: m.get("inserted_at", ""))
    for m in msgs:
        if m["id"] in seen:
            continue
        seen.add(m["id"])
        if first:
            continue
        t = m.get("inserted_at", "")[11:16]
        kind = "ERROR " if m.get("message_type") == "error" else ""
        text = " ".join(str(m.get("content", "")).split())
        flag = "PERMISSION " if "claude-permission:" in text else ""
        print(f"[{t}Z] {flag}{kind}{m.get('sender_name')}: {text[:260]}", flush=True)
    first = False
    time.sleep(interval)
