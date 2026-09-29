"""S1-I5 acceptance checks under load (verifier seat), from §10 and §2.

Run this file alone, with nothing else loading the service. R137: export is an atomic,
read-only snapshot, so an export taken while creates, moves, PATCHes and cancels run
must restore a consistent state: a receipt it holds replays with its original body and
its booking is there; a booking it holds is never without its receipt. R136: export and
import each answer within the 10 s test-control timeout. `pytest -rP` prints the
measured values.
"""
from __future__ import annotations

import datetime as dt
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

import fixtures as fx
from harness.http import RESET_TIMEOUT, Api, assert_status, new_key

pytestmark = pytest.mark.stage(1)

DATE = fx.booking_date()
USERS = 40
DURATION = dt.timedelta(minutes=90)


def hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def accounts(n: int) -> list[dict]:
    return [{"id": f"u_{i:02d}", "email": f"diner{i:02d}@example.com",
             "password": "correct horse", "display_name": f"Diner {i}"} for i in range(n)]


def seed(reference: str, user: int, table_id: str, at: str) -> dict:
    return {"id": f"res_{reference}", "reference": reference, "user_id": f"u_{user:02d}",
            "restaurant_id": "r_anker", "table_id": table_id,
            "starts_at_local": fx.local(DATE, at), "party_size": 2}


def world_of(reset, api, *, users: int, tables: int, reservations: list[dict]) -> list[str]:
    reset(fx.fixture(users=accounts(users), reservations=reservations, restaurants=[
        fx.restaurant(opening_hours=fx.all_week("00:00", "23:30"), tables=[
            {"id": f"t_{n}", "label": str(n), "capacity": 4} for n in range(tables)])]))
    return [api().authenticate(u["email"], u["password"]).token for u in accounts(users)]


def test_an_export_taken_under_concurrent_writes_restores_consistently(reset, api, base_url):
    """R137/R140/R7: 140 writes (120 keyed creates, 10 keyed moves, 5 PATCHes, 5
    cancels) run 40 at a time while an export is taken; the export, imported, holds for
    every keyed write either its receipt and its effect or neither, and no two confirmed
    bookings overlap."""
    tokens = world_of(reset, api, users=USERS, tables=60,
                      reservations=[seed(f"OWN{i:03d}", i, f"t_{i}", "12:00") for i in range(USERS)])
    writes = [("create", j % USERS, "POST", "/reservations", {
        "restaurant_id": "r_anker", "table_id": f"t_{40 + j % 20}",
        "starts_at_local": fx.local(DATE, hhmm((j // 20) * 90)), "party_size": 2})
        for j in range(120)]
    writes += [("move", m, "POST", "/reservation-moves", {"moves": [
        {"reference": f"OWN{m:03d}", "starts_at_local": fx.local(DATE, "15:00")}]}) for m in range(10)]
    writes += [("patch", p, "PATCH", f"/reservations/OWN{p:03d}",
                {"starts_at_local": fx.local(DATE, "16:30")}) for p in range(10, 15)]
    writes += [("cancel", c, "POST", f"/reservations/OWN{c:03d}/cancel", None) for c in range(15, 20)]
    random.Random(137).shuffle(writes)
    done = threading.Semaphore(0)

    def send(write):
        kind, user, method, path, body = write
        key = new_key() if kind in ("create", "move") else None
        with Api(base_url, token=tokens[user]) as client:
            resp = client.request(method, path, json=body, idempotency_key=key)
        done.release()
        return write, key, resp

    with ThreadPoolExecutor(max_workers=40) as pool:
        futures = [pool.submit(send, w) for w in writes]
        for _ in range(45):
            done.acquire()
        with Api(base_url, timeout=RESET_TIMEOUT) as control:
            exported = assert_status(control.get("/_test/export", token=None), 200).json()
        results = [f.result() for f in futures]
    assert all(resp.status_code < 500 for _, _, resp in results)
    keyed = [(w, key, resp) for w, key, resp in results if key and resp.status_code == 201]

    with Api(base_url, timeout=RESET_TIMEOUT) as control:
        assert_status(control.post("/_test/import", json=exported, token=None), 204)

    def present(write, original, client) -> bool:
        kind, user, _, _, _ = write
        if kind == "create":
            return client.get(f"/reservations/{original['reference']}").status_code == 200
        booking = client.get(f"/reservations/OWN{user:03d}").json()
        return booking["starts_at_local"] == fx.local(DATE, "15:00")

    effects = []
    for write, key, resp in keyed:
        with Api(base_url, token=tokens[write[1]]) as client:
            effects.append(present(write, resp.json(), client))
    problems, replayed = [], 0
    for (write, key, resp), effect in zip(keyed, effects):
        kind, user, method, path, body = write
        with Api(base_url, token=tokens[user]) as client:
            replay = client.request(method, path, json=body, idempotency_key=key)
        if replay.status_code == 200:
            replayed += 1
            if replay.json() != resp.json() or not effect:
                problems.append((kind, user, "receipt without its effect or with another body"))
        elif effect:
            problems.append((kind, user, f"effect without its receipt: replay {replay.status_code}"))
    print(f"snapshot_under_writes keyed_201={len(keyed)} receipts_in_export={replayed} problems={problems[:5]}")
    assert not problems, problems[:5]
    assert 0 < replayed < len(keyed), "the export did not land inside the burst; rerun"

    held: dict[str, list[dt.datetime]] = {}
    for token in tokens:
        with Api(base_url, token=token) as client:
            for booking in client.get("/reservations").json()["reservations"]:
                if booking["status"] == "confirmed":
                    held.setdefault(booking["table_id"], []).append(
                        dt.datetime.fromisoformat(booking["starts_at"]))
    clashes = [table for table, starts in held.items()
               if any(b - a < DURATION for a, b in zip(sorted(starts), sorted(starts)[1:]))]
    assert not clashes, clashes


def test_export_and_import_of_a_large_state_each_take_under_10_s(reset, api, base_url):
    """R136: 50 accounts, 400 bookings and 60 receipts export and import within 10 s."""
    seeded = [seed(f"BIG{t:02d}{k}", t % 50, f"t_{t}", hhmm(k * 120)) for t in range(40) for k in range(10)]
    tokens = world_of(reset, api, users=50, tables=40, reservations=seeded)
    with Api(base_url, token=tokens[0]) as client:
        for n in range(60):
            assert_status(client.post("/reservations", idempotency_key=new_key(), json={
                "restaurant_id": "r_anker", "table_id": f"t_{n % 40}",
                "starts_at_local": fx.local(DATE, hhmm(19 * 60 + 30 + 90 * (n // 40))),
                "party_size": 2}), 201)
    with Api(base_url, timeout=RESET_TIMEOUT) as control:
        started = time.perf_counter()
        exported = assert_status(control.get("/_test/export", token=None), 200).json()
        export_s = time.perf_counter() - started
        started = time.perf_counter()
        assert_status(control.post("/_test/import", json=exported, token=None), 204)
        import_s = time.perf_counter() - started
    print(f"large_state export_s={export_s:.2f} import_s={import_s:.2f}")
    assert export_s < RESET_TIMEOUT and import_s < RESET_TIMEOUT
    with Api(base_url, token=tokens[0]) as client:
        assert len(assert_status(client.get("/reservations"), 200).json()["reservations"]) == 70
