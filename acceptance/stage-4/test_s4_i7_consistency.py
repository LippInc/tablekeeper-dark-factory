"""S4-I7 acceptance check (verifier seat): answers made off the event loop are still answers of
one state (stage-1 §7 "requests take effect one at a time", the plan's S4-I7 "made in a worker
thread while the request keeps the store lock"): no write lands in the middle of an answer.

Two bookings on a dense day swap places in every write: A (t_1) and B (t_2) are at 01:00 and
22:00, one each, and each move batch moves both. In any state, at 01:00 and at 22:00 exactly one
of t_1 and t_2 is held. Readers ask (explained and plain, four party sizes, so answers keep
being made anew) while a writer keeps swapping, and some readers give up early; every answer
must show exactly one of the two held at each of those slots, and nothing may fail.

Resets the service; run it alone, with nothing else loading the service. `-rP` prints the
counts.
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

import fixtures as fx
from harness.http import Api, assert_status, new_key

pytestmark = pytest.mark.stage(4)

DATE = fx.booking_date()
TABLES = 40
SECONDS = 8.0


def seeds() -> list[dict]:
    """A (t_1, 01:00) and B (t_2, 22:00); 8 bookings on each other table."""
    items = [("AAAA01", "t_1", "01:00"), ("BBBB01", "t_2", "22:00")]
    for n in range(3, TABLES + 1):
        for j in range(8):
            start = (n * 7) % 60 + j * 160
            items.append((f"F{n:02d}N{j}X", f"t_{n}", f"{start // 60:02d}:{start % 60:02d}"))
    return [{"id": f"res_{r}", "reference": r, "user_id": "u_bob", "restaurant_id": "r_anker", "table_id": t,
             "starts_at_local": fx.local(DATE, s), "party_size": 1} for r, t, s in items]


def held_pair(body: bytes, hhmm: str, explain: bool) -> tuple[bool, bool]:
    """Whether t_1 and t_2 are held at the slot (explain: no_overlap does not hold; plain: the
    table is missing though it seats the party)."""
    slot = next(s for s in json.loads(body)["slots"] if s["starts_at_local"].endswith(hhmm))
    if explain:
        rules = {e["table_id"]: {r["rule"]: r["holds"] for r in e["rules"]} for e in slot["explain"]}
        return (not rules["t_1"]["no_overlap"], not rules["t_2"]["no_overlap"])
    return ("t_1" not in slot["available_table_ids"], "t_2" not in slot["available_table_ids"])


def test_no_write_lands_inside_an_answer(reset, base_url):
    tables = [{"id": f"t_{n}", "label": str(n), "capacity": n % 8 + 1} for n in range(1, TABLES + 1)]
    reset(fx.fixture(restaurants=[{**fx.restaurant(tables=tables, slot_minutes=1, opening_hours=fx.all_week("00:00", "23:30")),
                                   "manager_user_ids": [fx.ADA["id"]]}], reservations=seeds()))
    with Api(base_url) as login:
        bob = login.authenticate(fx.BOB["email"], fx.BOB["password"]).token
    stop = time.monotonic() + SECONDS
    counts = {"answers": 0, "torn": [], "errors": [], "moves": 0, "gave_up": 0}
    lock = threading.Lock()

    def writer():
        place = [("22:00", "01:00"), ("01:00", "22:00")]
        k = 0
        with Api(base_url, token=bob, timeout=30) as client:
            while time.monotonic() < stop:
                a, b = place[k % 2]
                response = client.post("/reservation-moves", idempotency_key=new_key(), json={"moves": [
                    {"reference": "AAAA01", "starts_at_local": fx.local(DATE, a)},
                    {"reference": "BBBB01", "starts_at_local": fx.local(DATE, b)}]})
                with lock:
                    if response.status_code != 201:
                        counts["errors"].append(f"move {response.status_code} {response.text[:120]}")
                    counts["moves"] += 1
                k += 1

    def reader(index):
        explain = index % 2 == 0
        party = 1 + (index // 2) % 4 if explain else 1 + (index // 2) % 2  # plain: parties both tables seat
        params = {"restaurant_id": "r_anker", "date": DATE, "party_size": party, **({"explain": "true"} if explain else {})}
        impatient = index % 5 == 4  # gives up after 50 ms
        with Api(base_url, token=bob, timeout=0.05 if impatient else 30) as client:
            while time.monotonic() < stop:
                try:
                    response = client.get("/availability", params=params)
                except httpx.TimeoutException:
                    with lock:
                        counts["gave_up"] += 1
                    continue
                with lock:
                    if response.status_code != 200:
                        counts["errors"].append(f"availability {response.status_code} {response.text[:120]}")
                        continue
                    counts["answers"] += 1
                for hhmm in ("01:00", "22:00"):
                    t1, t2 = held_pair(response.content, hhmm, explain)
                    if t1 == t2:
                        with lock:
                            counts["torn"].append(f"party {party} explain {explain} at {hhmm}: t_1 held {t1}, t_2 held {t2}")

    with ThreadPoolExecutor(13) as pool:
        futures = [pool.submit(writer)] + [pool.submit(reader, i) for i in range(12)]
        for future in futures:
            future.result()
    with Api(base_url, timeout=30) as control:
        assert_status(control.get("/health"), 200)
    print(f"answers {counts['answers']}, moves {counts['moves']}, gave up {counts['gave_up']}, "
          f"torn {len(counts['torn'])}, errors {len(counts['errors'])}")
    assert counts["answers"] > 20 and counts["moves"] > 5, counts
    assert counts["torn"] == [] and counts["errors"] == [], (counts["torn"][:5], counts["errors"][:5])
