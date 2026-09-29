"""S1-I4 acceptance checks (verifier seat), written from the stage-1 specification.

POST /reservation-moves (§11): several of the caller's bookings change together or not
at all, with the ordinary amendment rules per item, occupancy judged on the resulting
set, and the idempotency of §7. R.. and D.. name the room plan's requirement lines and
decisions. The races are in test_s1_i4_races.py (run alone).
"""
from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace

import pytest

import fixtures as fx
from harness.http import assert_error, assert_status, error_code, new_key

pytestmark = pytest.mark.stage(1)

DATE = fx.booking_date()
PAST = (dt.date.fromisoformat(DATE) - dt.timedelta(days=30)).isoformat()


def seed(reference: str, table_id: str, at: str, *, user_id: str = "u_ada", date: str = DATE,
         restaurant_id: str = "r_anker", party_size: int = 2) -> dict:
    return {"id": f"res_{reference}", "reference": reference, "user_id": user_id,
            "restaurant_id": restaurant_id, "table_id": table_id,
            "starts_at_local": fx.local(date, at), "party_size": party_size}


@pytest.fixture
def batch(reset, api, anon):
    """Ada's bookings A (t_1 19:00), B (t_2 19:00), C (t_3 21:00), P (t_2, a month ago)
    and O (at another restaurant); Bob's booking on t_3 at 19:00."""
    other = fx.restaurant("r_other", name="Other",
                          tables=[{"id": "t_x", "label": "X", "capacity": 8}])
    reset(fx.fixture(restaurants=[fx.restaurant(), other], reservations=[
        seed("BOOKA1", "t_1", "19:00"), seed("BOOKB1", "t_2", "19:00"),
        seed("BOOKC1", "t_3", "21:00"), seed("PAST01", "t_2", "19:00", date=PAST),
        seed("OTHR01", "t_x", "19:00", restaurant_id="r_other"),
        seed("BOBB01", "t_3", "19:00", user_id="u_bob")]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    bob = api().authenticate(fx.BOB["email"], fx.BOB["password"])
    return SimpleNamespace(ada=ada, bob=bob, anon=anon)


def move(client, *items: dict, key: str | None = None):
    return client.post("/reservation-moves", json={"moves": list(items)},
                       idempotency_key=key or new_key())


def item(reference: str, table_id: str | None = None, at: str | None = None,
         party_size=None, **extra) -> dict:
    found = {"reference": reference, **extra}
    if table_id is not None:
        found["table_id"] = table_id
    if at is not None:
        found["starts_at_local"] = at if "T" in at else fx.local(DATE, at)
    if party_size is not None:
        found["party_size"] = party_size
    return found


def bookings(client) -> dict[str, dict]:
    listed = assert_status(client.get("/reservations"), 200).json()["reservations"]
    return {b["reference"]: b for b in listed}


def free(anon, at: str, party_size: int = 1) -> dict[str, list[str]]:
    slots = assert_status(anon.get("/availability", params={
        "restaurant_id": "r_anker", "date": DATE, "party_size": party_size}), 200).json()["slots"]
    return {s["starts_at_local"][-5:]: s["available_table_ids"] for s in slots}[at]


def unchanged(world_before: tuple, b) -> None:
    """Every booking and the 19:00/21:00 occupancy are as they were."""
    assert (bookings(b.ada), bookings(b.bob), free(b.anon, "19:00"), free(b.anon, "21:00")) == \
        world_before


def snapshot(b) -> tuple:
    return bookings(b.ada), bookings(b.bob), free(b.anon, "19:00"), free(b.anon, "21:00")


# ---- success (§11) ---------------------------------------------------------------------------

def test_a_table_swap_commits_together_in_input_order(batch):
    """R4/R150/R152/R147: A and B swap tables in one request; the answer lists every
    item in input order, the unchanged C included; identity, owner and creation time
    stay; both tables stay held."""
    before = bookings(batch.ada)
    resp = move(batch.ada, item("BOOKA1", "t_2"), item("BOOKC1"), item("BOOKB1", "t_1"))
    body = assert_status(resp, 201).json()
    assert [(r["reference"], r["table_id"]) for r in body["reservations"]] == \
        [("BOOKA1", "t_2"), ("BOOKC1", "t_3"), ("BOOKB1", "t_1")]
    after = bookings(batch.ada)
    for ref in ("BOOKA1", "BOOKB1", "BOOKC1"):
        for field in ("reservation_id", "reference", "created_at", "status", "starts_at"):
            assert after[ref][field] == before[ref][field], (ref, field)
    assert after["BOOKC1"] == before["BOOKC1"]
    assert [after[r["reference"]] for r in body["reservations"]] == body["reservations"]
    assert free(batch.anon, "19:00") == []


def test_items_change_time_and_party_and_keep_omitted_fields(batch):
    """R146/R29: an item takes table_id, starts_at_local and party_size; omitted fields keep
    their values; unknown fields are ignored; the old slot is released."""
    resp = move(batch.ada, item("BOOKA1", at="20:30", note="window please"),
                item("BOOKB1", party_size=4, color="red"))
    body = assert_status(resp, 201).json()["reservations"]
    assert (body[0]["table_id"], body[0]["starts_at_local"], body[0]["party_size"]) == \
        ("t_1", fx.local(DATE, "20:30"), 2)
    assert (body[1]["table_id"], body[1]["starts_at_local"], body[1]["party_size"]) == \
        ("t_2", fx.local(DATE, "19:00"), 4)
    assert "t_1" in free(batch.anon, "19:00") and "t_1" not in free(batch.anon, "20:30")


def test_a_batch_of_no_ops_keeps_every_value(batch):
    """R153: no-op moves retain all existing values."""
    before = bookings(batch.ada)
    body = assert_status(move(batch.ada, item("BOOKA1", "t_1", "19:00", 2), item("BOOKB1")),
                         201).json()
    assert body["reservations"] == [before["BOOKA1"], before["BOOKB1"]]
    assert bookings(batch.ada) == before


MOVE_SCENARIOS = {
    # a table swap between bookings at different times, and a time move of two bookings
    "table_swap": ([("SWAPA1", "t_1", "19:00"), ("SWAPB1", "t_2", "21:00")],
                   [item("SWAPA1", "t_2"), item("SWAPB1", "t_1")],
                   [("t_1", "19:00"), ("t_2", "21:00")], [("t_2", "19:00"), ("t_1", "21:00")],
                   ("t_1", "19:00"), ("t_2", "19:30")),
    "time_move": ([("TIMEC1", "t_3", "18:00"), ("TIMED1", "t_2", "18:00")],
                  [item("TIMEC1", at="21:30"), item("TIMED1", at="20:00")],
                  [("t_3", "18:00"), ("t_2", "18:00")], [("t_3", "21:30"), ("t_2", "20:00")],
                  ("t_3", "18:00"), ("t_2", "20:30")),
}


@pytest.mark.parametrize("scenario", list(MOVE_SCENARIOS))
def test_a_move_frees_its_old_slots_and_takes_its_new_ones(reset, api, anon, scenario):
    """R4/R150/R151/R108 (critic C29-B1): after a successful two-item move, GET
    /availability shows each old slot free and each new slot taken for the right tables;
    a create on a freed slot is 201 and on a taken slot 409."""
    seeds, moves, freed, taken, free_create, taken_create = MOVE_SCENARIOS[scenario]
    reset(fx.fixture(reservations=[seed(ref, table, at) for ref, table, at in seeds]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    bob = api().authenticate(fx.BOB["email"], fx.BOB["password"])
    assert_status(move(ada, *moves), 201)
    for table, at in freed:
        assert table in free(anon, at), f"{table} at {at} is still held after the move"
    for table, at in taken:
        assert table not in free(anon, at), f"{table} at {at} is not held after the move"
    for (table, at), status in ((free_create, 201), (taken_create, 409)):
        resp = bob.post("/reservations", idempotency_key=new_key(), json={
            "restaurant_id": "r_anker", "table_id": table, "starts_at_local": fx.local(DATE, at),
            "party_size": 2})
        assert resp.status_code == status, (table, at, resp.status_code, resp.text[:200])


# ---- atomicity (§11) --------------------------------------------------------------------------

def test_an_overlap_with_an_unlisted_booking_changes_nothing(batch):
    """R150/R151: moving onto Bob's table and time is 409 table_unavailable, and the other
    item in the batch does not move either."""
    before = snapshot(batch)
    assert_error(move(batch.ada, item("BOOKA1", at="20:30"), item("BOOKB1", "t_3")),
                 409, "table_unavailable")
    unchanged(before, batch)


def test_an_overlap_among_the_resulting_bookings_is_409(batch):
    """R150: two items moved onto one table and time conflict with each other."""
    before = snapshot(batch)
    assert_error(move(batch.ada, item("BOOKA1", "t_3", "21:00"), item("BOOKC1", at="21:30")),
                 409, "table_unavailable")
    unchanged(before, batch)


def test_an_unchanged_listed_booking_keeps_its_occupancy(batch):
    """R150: a listed booking that does not change still holds its slot against the
    other items; moving past it succeeds."""
    before = snapshot(batch)
    assert_error(move(batch.ada, item("BOOKA1"), item("BOOKB1", "t_1", "19:30")),
                 409, "table_unavailable")
    unchanged(before, batch)
    assert_status(move(batch.ada, item("BOOKA1"), item("BOOKB1", "t_1", "20:30")), 201)


@pytest.mark.parametrize("third,status,code", [
    (item("BOOKC1", at="21:15"), 422, "not_on_slot_grid"),
    (item("BOOKC1", at="19:00"), 409, "table_unavailable"),
    (item("BOBB01", "t_1"), 404, "not_found"),
])
def test_a_batch_failing_on_its_third_item_changes_nothing_and_frees_the_key(batch, third,
                                                                            status, code):
    """R151/R9/R79: items one and two are valid; the third fails; every booking, the
    occupancy and the key are as before, so the key is a first use again."""
    before = snapshot(batch)
    key = new_key()
    first_two = (item("BOOKA1", at="20:30"), item("BOOKB1", "t_2", "18:00"))
    assert_error(move(batch.ada, *first_two, third, key=key), status, code)
    unchanged(before, batch)
    retry = assert_status(move(batch.ada, *first_two, key=key), 201).json()["reservations"]
    assert [(r["reference"], r["starts_at_local"][-5:]) for r in retry] == \
        [("BOOKA1", "20:30"), ("BOOKB1", "18:00")]


# ---- shape and ownership (§11) ------------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    {"moves": []},
    {"moves": [{"reference": f"NOPE{n:02d}"} for n in range(9)]},
    {},
    {"moves": "BOOKA1"},
    {"moves": {"reference": "BOOKA1"}},
    {"moves": ["BOOKA1"]},
    {"moves": [{"reference": 123}]},
    {"moves": [{"table_id": "t_3"}]},
    {"moves": [{"reference": "BOOKA1"}, {"reference": "BOOKA1", "table_id": "t_3"}]},
    {"moves": [{"reference": "R" * 65}]},
], ids=["zero", "nine", "no_moves", "string", "object", "item_not_object", "reference_number",
        "reference_missing", "duplicate", "reference_65_chars"])
def test_an_invalid_batch_shape_is_422(batch, payload):
    """R144/D12: moves is 1..8 objects with distinct string references; anything else
    is 422 validation_failed and changes nothing."""
    before = snapshot(batch)
    resp = batch.ada.post("/reservation-moves", json=payload, idempotency_key=new_key())
    assert_error(resp, 422, "validation_failed")
    unchanged(before, batch)


def test_eight_moves_is_a_valid_batch(reset, api):
    """R144: up to 8 moves in one batch."""
    tables = [{"id": f"t_{n}", "label": str(n), "capacity": 4} for n in range(9)]
    reset(fx.fixture(restaurants=[fx.restaurant(tables=tables)],
                     reservations=[seed(f"EIGHT{n}", f"t_{n}", "19:00") for n in range(8)]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    moves = [item(f"EIGHT{n}", f"t_{n + 1}") for n in reversed(range(8))]
    body = assert_status(move(ada, *moves), 201).json()["reservations"]
    assert [r["table_id"] for r in body] == [f"t_{n + 1}" for n in reversed(range(8))]


@pytest.mark.parametrize("reference", ["BOBB01", "NOPE99"], ids=["another_owner", "unknown"])
def test_a_reference_that_is_not_the_callers_is_404(batch, reference):
    """R145: an unknown or another owner's reference is 404 not_found; nothing changes."""
    before = snapshot(batch)
    assert_error(move(batch.ada, item("BOOKA1", at="20:30"), item(reference, "t_1")),
                 404, "not_found")
    unchanged(before, batch)


def test_bookings_at_different_restaurants_are_422(batch):
    """R145: every booking in a batch must be at the same restaurant."""
    before = snapshot(batch)
    assert_error(move(batch.ada, item("BOOKA1", at="20:30"), item("OTHR01")), 422,
                 "validation_failed")
    unchanged(before, batch)


def test_moves_need_a_token_and_a_key(batch, api):
    """R143/R48/R59/R75: no token 401; absent or empty key 400; a 256-character key 422."""
    payload = {"moves": [item("BOOKA1", at="20:30")]}
    assert_error(api().post("/reservation-moves", json=payload, token=None,
                            idempotency_key=new_key()), 401, "unauthenticated")
    assert_error(batch.ada.post("/reservation-moves", json=payload), 400, "missing_idempotency_key")
    assert_error(batch.ada.post("/reservation-moves", json=payload, idempotency_key=""), 400,
                 "missing_idempotency_key")
    assert_error(batch.ada.post("/reservation-moves", json=payload, idempotency_key="k" * 256),
                 422, "validation_failed")
    assert bookings(batch.ada)["BOOKA1"]["starts_at_local"] == fx.local(DATE, "19:00")


# ---- per-item rules and precedence (§11, D9) -------------------------------------------------------

@pytest.mark.parametrize("bad,status,code", [
    (item("BOOKA1", at="19:15"), 422, "not_on_slot_grid"),
    (item("BOOKA1", at="22:00"), 422, "outside_opening_hours"),
    (item("BOOKA1", party_size=3), 422, "party_exceeds_capacity"),
    (item("BOOKA1", party_size="2"), 422, "validation_failed"),
    (item("BOOKA1", party_size=0), 422, "validation_failed"),
    (item("BOOKA1", at=f"{DATE}T19:00:00"), 422, "validation_failed"),
    (item("BOOKA1", table_id=1), 400, "malformed_request"),
    (item("BOOKA1", "t_9"), 404, "not_found"),
    (item("BOOKA1", "t_x"), 404, "not_found"),
    (item("BOOKA1", at="2026-03-29T02:30"), 422, "invalid_local_time"),
    (item("PAST01", "t_1"), 409, "cutoff_passed"),
    (item("PAST01"), 409, "cutoff_passed"),
], ids=["off_grid", "outside_hours", "over_capacity", "party_string", "party_zero",
        "local_with_seconds", "table_number", "unknown_table", "other_restaurants_table",
        "skipped_time", "cutoff", "cutoff_on_no_op"])
def test_each_item_answers_the_ordinary_amendment_code(batch, bad, status, code):
    """R148/R149/R122/R55/R56: an item breaking a rule gives that rule's PATCH code, the
    cutoff applies to every listed booking, and nothing changes."""
    before = snapshot(batch)
    assert_error(move(batch.ada, item("BOOKB1", at="20:30"), bad), status, code)
    unchanged(before, batch)


def test_a_cancelled_booking_in_a_batch_is_409(batch):
    """R148: a cancelled booking gives 409 reservation_cancelled, even as a no-op."""
    assert_status(batch.ada.post("/reservations/BOOKC1/cancel"), 200)
    before = snapshot(batch)
    assert_error(move(batch.ada, item("BOOKA1", at="20:30"), item("BOOKC1")), 409,
                 "reservation_cancelled")
    unchanged(before, batch)


@pytest.mark.parametrize("items,status,code", [
    ((item("BOOKA1", at="19:15"), item("PAST01")), 422, "not_on_slot_grid"),
    ((item("PAST01"), item("BOOKA1", at="19:15")), 409, "cutoff_passed"),
    ((item("PAST01", at="19:15"), item("BOOKA1")), 409, "cutoff_passed"),
    ((item("PAST01", party_size=0), item("BOOKA1")), 409, "cutoff_passed"),
    ((item("BOOKA1", "t_9"), item("BOOKB1", at="19:15")), 404, "not_found"),
    ((item("BOOKB1", at="19:15"), item("BOOKA1", "t_9")), 422, "not_on_slot_grid"),
    ((item("BOOKB1", at="19:15"), item("NOPE99")), 422, "not_on_slot_grid"),
    ((item("NOPE99"), item("BOOKB1", at="19:15")), 404, "not_found"),
], ids=["grid_before_later_cutoff", "cutoff_before_later_grid", "cutoff_before_own_grid",
        "cutoff_before_own_field", "table_before_later_grid", "grid_before_later_table",
        "grid_before_later_unknown", "unknown_before_later_grid"])
def test_errors_take_precedence_in_input_order_with_cutoff_first(batch, items, status, code):
    """R149/D9: non-occupancy errors take precedence in input order; for one booking the
    cutoff precedes its other changes."""
    assert_error(move(batch.ada, *items), status, code)


# ---- idempotency (§7, §11) ------------------------------------------------------------------------

def test_a_replay_returns_the_original_even_after_changes(batch):
    """R77/R153/R82: a replay answers 200 with the original body after a later PATCH and
    a cancel, and changes nothing."""
    key = new_key()
    moves = (item("BOOKA1", "t_2"), item("BOOKB1", "t_1"))
    original = assert_status(move(batch.ada, *moves, key=key), 201).json()
    assert_status(batch.ada.patch("/reservations/BOOKA1", json={"starts_at_local": fx.local(DATE, "20:30")}), 200)
    assert_status(batch.ada.post("/reservations/BOOKB1/cancel"), 200)
    after = bookings(batch.ada)
    assert assert_status(move(batch.ada, *moves, key=key), 200).json() == original
    assert bookings(batch.ada) == after


def test_the_same_key_with_another_body_is_reuse_before_any_check(batch):
    """R52/R74/R78: a used key with a different body is 409 idempotency_key_reuse, even
    when the new body has an invalid shape; nothing changes."""
    key = new_key()
    assert_status(move(batch.ada, item("BOOKA1", at="20:30"), key=key), 201)
    before = snapshot(batch)
    for payload in ({"moves": [item("BOOKA1", at="21:00")]}, {"moves": []}, {"nothing": True}):
        resp = batch.ada.post("/reservation-moves", json=payload, idempotency_key=key)
        assert_error(resp, 409, "idempotency_key_reuse")
    unchanged(before, batch)


def test_a_replay_is_the_same_json_value(batch):
    """R80: key order and whitespace do not matter."""
    key = new_key()
    payload = {"moves": [{"reference": "BOOKA1", "starts_at_local": fx.local(DATE, "20:30")}]}
    original = assert_status(batch.ada.post("/reservation-moves", json=payload,
                                            idempotency_key=key), 201).json()
    spaced = json.dumps({"moves": [dict(reversed(list(payload["moves"][0].items())))]},
                        indent=3).encode()
    replay = batch.ada.post("/reservation-moves", content=spaced, idempotency_key=key)
    assert assert_status(replay, 200).json() == original


def test_the_same_key_and_body_on_another_path_is_another_request(batch):
    """R73/D2: the same key with the same body on /reservations and /reservation-moves
    are different requests; each succeeds normally and replays on its own path."""
    key = new_key()
    payload = {"restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": fx.local(DATE, "21:00"),
               "party_size": 2, "moves": [item("BOOKA1", at="20:30")]}
    created = assert_status(batch.ada.post("/reservations", json=payload, idempotency_key=key), 201).json()
    moved = assert_status(batch.ada.post("/reservation-moves", json=payload, idempotency_key=key),
                          201).json()
    assert created["table_id"] == "t_2" and moved["reservations"][0]["reference"] == "BOOKA1"
    assert assert_status(batch.ada.post("/reservations", json=payload, idempotency_key=key),
                         200).json() == created
    assert assert_status(batch.ada.post("/reservation-moves", json=payload, idempotency_key=key),
                         200).json() == moved


def test_keys_for_moves_belong_to_one_user(batch):
    """R72: another user may use the same key string."""
    key = new_key()
    assert_status(move(batch.ada, item("BOOKA1", at="20:30"), key=key), 201)
    assert_status(move(batch.bob, item("BOBB01", at="18:00"), key=key), 201)


# ---- no 5xx on odd input (§5) ----------------------------------------------------------------------

ODD_MOVES = [
    b'{"moves": [{"reference": "BOOKA1", "party_size": 1e400}]}',
    b'{"moves": [{"reference": "BOOKA1", "starts_at_local": "9999-12-31T23:30"}]}',
    b'{"moves": [{"reference": "BOOKA1", "starts_at_local": "0001-01-01T00:00"}]}',
    b'{"moves": [{"reference": "\\u00fc\\u0000\\ud800"}]}',
    b'{"moves": [{"reference": "BOOKA1", "table_id": {"id": "t_2"}, "party_size": []}]}',
    b'{"moves": [[[[[[[[["BOOKA1"]]]]]]]]]}',
]


@pytest.mark.parametrize("raw", ODD_MOVES, ids=[f"m{i}" for i in range(len(ODD_MOVES))])
def test_odd_batches_never_answer_5xx(batch, raw):
    """R60: requests must not produce 5xx; a refusal carries the error envelope."""
    resp = batch.ada.post("/reservation-moves", content=raw, idempotency_key=new_key())
    assert resp.status_code < 500, f"-> {resp.status_code} {resp.text[:200]}"
    if resp.status_code >= 400:
        error_code(resp)
