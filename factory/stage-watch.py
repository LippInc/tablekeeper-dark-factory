"""stage-watch.py - one lean watcher for a judged stage (driver side; not part of the result repo).

Replaces room-watch.py + perm-watch.sh + liveness-watch.sh for the driver (2026-09-28): one process instead of three
loops, and only lines worth acting on, so the driver wakes less often.
Prints one line per:
  - milestone room message: a verdict, a look review, a repeat or packaging report, a builder handoff, the first part
    of an architect request, a critic plan review, anything addressed to the owner (the final report);
  - error message in the room, and any permission text;
  - new pending runtime permission request of a seat (jam permissions list);
  - liveness change: no seat transcript written for <quiet> minutes (QUIET, with the running container count, since a
    verifier's long known-bad loop is quiet but busy), and activity again.
Resumes without a gap: messages newer than <since> are reported on the first poll. On exit it prints the resume stamp.
Exits by itself after <max> seconds: on Windows a Monitor's 30-minute expiry leaves child loops running (38 stale
copies found 2026-09-27), so each re-arm must start a watcher that dies on its own.

Usage: python -u stage-watch.py <room> <owner handle> <owner participant id> <since ISO|none>
                               [poll s=45] [max s=1680] [quiet min=20] [transcript dir]
"""
import glob, json, os, re, subprocess, sys, time
from datetime import datetime, timezone

room, owner, owner_id, since = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
poll = int(sys.argv[5]) if len(sys.argv) > 5 else 45
max_s = int(sys.argv[6]) if len(sys.argv) > 6 else 1680
quiet_min = int(sys.argv[7]) if len(sys.argv) > 7 else 20
tdir = sys.argv[8] if len(sys.argv) > 8 else r"C:\factory\claude-config\projects\C--factory-ws"
since = "" if since.lower() == "none" else since

_win = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "jam", "bin", "jam.exe")
jam = _win if os.path.isfile(_win) else "jam"
seats = ["architect", "critic", "designer", "builder", "verifier", "release-clerk"]
mention = re.compile(r"@\[\[[0-9a-f-]{36}\]\]\s*")
# Milestones by the band's own message headers (seen in stages 1-3). Parts 2..N of a split request are skipped.
milestone = re.compile(
    r"^(VERDICT|REPEAT|LOOK REVIEW|PACKAGING REPORT|FINAL REPORT|STAGE \d+ ITEM \d+ HANDOFF"
    r"|\[1/\d+\] [A-Z]|PLAN REVIEW|CLEAR|BLOCKED|SPLIT)"
    r"|: \**(VERIFIED|REFUTED|APPROVED|CHANGES|PASS|FAIL|CLEAR|BLOCKED|SPLIT)\b")  # verdicts may be in **bold**


def now():
    return datetime.now(timezone.utc).strftime("%H:%MZ")


def run(args, timeout=60):
    return subprocess.run([jam] + args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


fails = 0
last_ts = since
seen = set()
perm_seen = set()
state = "active"
stop_at = time.time() + max_s
next_perm = 0.0

while time.time() < stop_at:
    # 1. Room messages (newest page of each type).
    msgs, ok = [], True
    for kind in ("text", "error"):
        try:
            out = run(["room", "messages", room, "--type", kind, "--json"])
            msgs += json.loads(out.stdout).get("messages", [])
        except Exception as e:
            ok = False
            err = e
    if ok:
        fails = 0
    else:
        fails += 1
        if fails == 3:
            print(f"[{now()}] [watch] room fetch failed 3 times in a row: {err}", flush=True)
    for m in sorted(msgs, key=lambda x: x.get("inserted_at", "")):
        ts = m.get("inserted_at", "")
        if m.get("id") in seen or (since and ts <= since):
            continue
        seen.add(m.get("id"))
        last_ts = max(last_ts, ts)
        raw = str(m.get("content", ""))
        text = " ".join(mention.sub("", raw).split())
        is_err = m.get("message_type") == "error"
        to_owner = owner_id in raw
        perm = "claude-permission:" in raw
        if is_err or to_owner or perm or milestone.search(text[:200]):
            flag = "ERROR " if is_err else ("PERMISSION " if perm else ("TO-OWNER " if to_owner else ""))
            print(f"[{ts[11:16]}Z] {flag}{m.get('sender_name')}: {text[:230]}", flush=True)

    # 2. Pending permission requests (every 120 s).
    if time.time() >= next_perm:
        next_perm = time.time() + 120
        for s in seats:
            try:
                out = run(["permissions", "list", "--as", f"{owner}/{s}"])
                body = (out.stdout or "") + (out.stderr or "")
            except Exception:
                continue
            if not body.strip() or "no runtime permissions" in body or "daemon unavailable" in body or "timed out" in body:
                continue
            for line in body.splitlines():
                key = f"{s}|{line}"
                if line.strip() and key not in perm_seen:
                    perm_seen.add(key)
                    print(f"[{now()}] PERMISSION {s}: {line[:220]}", flush=True)

    # 3. Liveness: the newest seat transcript.
    files = glob.glob(os.path.join(tdir, "*.jsonl"))
    if files:
        newest = max(files, key=os.path.getmtime)
        age = int((time.time() - os.path.getmtime(newest)) / 60)
        if age >= quiet_min and state == "active":
            try:
                names = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True, timeout=30).stdout.split()
            except Exception:
                names = []
            print(f"[{now()}] QUIET: no seat transcript written for {age} min; running containers: {len(names)} {' '.join(names)[:120]}", flush=True)
            state = "quiet"
        elif age < quiet_min and state == "quiet":
            print(f"[{now()}] ACTIVE again: a seat transcript was written {age} min ago", flush=True)
            state = "active"

    time.sleep(poll)

print(f"[{now()}] [watch] window ended; resume with since={last_ts or 'none'}", flush=True)
