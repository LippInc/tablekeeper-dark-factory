"""S1-I3 acceptance checks (verifier seat), written from the stage-1 specification.

The booking lifecycle (§8): POST /reservations with its rules and idempotency (§7),
reads, cancel and PATCH, the cutoff (§4), time zones on booking (§9), and that every
slot availability lists can be booked. R.. and D.. name the room plan's requirement
lines and decisions. The races at 50 in flight are in test_s1_i3_races.py (run alone).
"""
from __future__ import annotations

import datetime as dt
import json
import re
from zoneinfo import ZoneInfo

import pytest

import fixtures as fx
from harness.http import assert_error, assert_status, error_code, new_key

pytestmark = pytest.mark.stage(1)

REFERENCE = re.compile(r"[A-Z0-9]{6,12}")
RFC3339 = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:\d{2}|Z)")
SHAPE = {"reservation_id", "reference", "restaurant_id", "table_id", "party_size", "status",
         "starts_at_local", "starts_at", "ends_at", "created_at"}
BERLIN_SPRING, BERLIN_FALL = "2026-03-29", "2026-10-25"
NY_SPRING, NY_FALL = "2026-03-08", "2026-11-01"


def body(date: str, at: str = "19:00", *, table_id: str = "t_2", party_size=4,
         restaurant_id: str = "r_anker") -> dict:
    return {"restaurant_id": restaurant_id, "table_id": table_id,
            "starts_at_local": fx.local(date, at), "party_size": party_size}


def create(client, payload: dict, key: str | None = None):
    return client.post("/reservations", json=payload, idempotency_key=key or new_key())


def free_tables(client, date: str, at: str, party_size: int = 1, restaurant_id: str = "r_anker"):
    slots = assert_status(client.get("/availability", params={
        "restaurant_id": restaurant_id, "date": date, "party_size": party_size}), 200).json()["slots"]
    return next(s["available_table_ids"] for s in slots if s["starts_at_local"].endswith(at))


def reservation(client, reference: str) -> dict:
    return assert_status(client.get(f"/reservations/{reference}"), 200).json()


def references(client) -> list[str]:
    return [r["reference"] for r in
            assert_status(client.get("/reservations"), 200).json()["reservations"]]


def instant(value: str) -> tuple[str, str]:
    """(local wall time YYYY-MM-DDTHH:MM, offset) of an RFC 3339 timestamp."""
    assert RFC3339.fullmatch(value), f"not RFC 3339 with an offset: {value!r}"
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=None).isoformat(timespec="minutes"), parsed.isoformat()[-6:]


def minutes_until(date: str, at: str, zone: str = "Europe/Berlin") -> int:
    start = dt.datetime.fromisoformat(fx.local(date, at)).replace(tzinfo=ZoneInfo(zone))
    return int((start - dt.datetime.now(dt.timezone.utc)).total_seconds() // 60)


def other_restaurant() -> dict:
    return fx.restaurant("r_other", name="Other", tables=[
        {"id": "t_x", "label": "X", "capacity": 8}])


# ---- create (§8 POST /reservations) ------------------------------------------------------

def test_a_booking_answers_the_documented_shape_and_reads_back(world, book):
    """R2/R96/R97/R28: 201 with every documented field, a 6-12 character A-Z0-9
    reference, offsets in the restaurant zone, and the same body on every read."""
    resp = assert_status(book(table_id="t_3", at="19:30", party_size=5), 201)
    created = resp.json()
    assert SHAPE <= set(created), SHAPE - set(created)
    assert REFERENCE.fullmatch(created["reference"]), created["reference"]
    assert isinstance(created["reservation_id"], str) and 1 <= len(created["reservation_id"]) <= 64
    assert (created["restaurant_id"], created["table_id"], created["party_size"],
            created["status"], created["starts_at_local"]) == \
        (world.rid, "t_3", 5, "confirmed", fx.local(world.date, "19:30"))
    offset = dt.datetime.fromisoformat(fx.local(world.date, "19:30")).replace(
        tzinfo=ZoneInfo("Europe/Berlin")).isoformat()[-6:]
    assert instant(created["starts_at"]) == (fx.local(world.date, "19:30"), offset)
    assert instant(created["ends_at"]) == (fx.local(world.date, "21:00"), offset)
    made = dt.datetime.fromisoformat(created["created_at"].replace("Z", "+00:00"))
    assert RFC3339.fullmatch(created["created_at"])
    assert abs(made - dt.datetime.now(dt.timezone.utc)) < dt.timedelta(minutes=10)
    assert reservation(world.ada, created["reference"]) == created
    assert assert_status(world.ada.get("/reservations"), 200).json() == {"reservations": [created]}


def test_every_booking_gets_its_own_reference(world, book):
    """R97: references are unique across all reservations."""
    made = [assert_status(book(table_id=table, at=at, party_size=1), 201).json()["reference"]
            for table in ("t_1", "t_2", "t_3") for at in ("18:00", "19:30", "21:00")]
    assert len(set(made)) == len(made) and all(REFERENCE.fullmatch(r) for r in made)


def _invalid_bodies(date: str) -> list[tuple[str, dict, int, str]]:
    ok = body(date)
    without = lambda name: {k: v for k, v in ok.items() if k != name}  # noqa: E731
    return [
        ("off_grid_19_15", body(date, "19:15"), 422, "not_on_slot_grid"),
        ("off_grid_19_01", body(date, "19:01"), 422, "not_on_slot_grid"),
        ("before_opens", body(date, "17:30"), 422, "outside_opening_hours"),
        ("ends_after_closes", body(date, "22:00"), 422, "outside_opening_hours"),
        ("at_closes", body(date, "23:00"), 422, "outside_opening_hours"),
        ("party_over_capacity", body(date, table_id="t_1", party_size=3), 422, "party_exceeds_capacity"),
        ("party_zero", body(date, party_size=0), 422, "validation_failed"),
        ("party_negative", body(date, party_size=-1), 422, "validation_failed"),
        ("party_string", body(date, party_size="4"), 422, "validation_failed"),
        ("party_true", body(date, party_size=True), 422, "validation_failed"),
        ("party_float", body(date, party_size=4.5), 422, "validation_failed"),
        ("party_null", body(date, party_size=None), 422, "validation_failed"),
        ("party_list", body(date, party_size=[4]), 422, "validation_failed"),
        ("party_missing", without("party_size"), 422, "validation_failed"),
        ("local_with_seconds", {**ok, "starts_at_local": f"{date}T19:00:00"}, 422, "validation_failed"),
        ("local_with_space", {**ok, "starts_at_local": f"{date} 19:00"}, 422, "validation_failed"),
        ("local_with_z", {**ok, "starts_at_local": f"{date}T19:00Z"}, 422, "validation_failed"),
        ("local_with_offset", {**ok, "starts_at_local": f"{date}T19:00+02:00"}, 422, "validation_failed"),
        ("local_time_only", {**ok, "starts_at_local": "19:00"}, 422, "validation_failed"),
        ("local_bad_date", {**ok, "starts_at_local": "2026-02-30T19:00"}, 422, "validation_failed"),
        ("local_24_00", {**ok, "starts_at_local": f"{date}T24:00"}, 422, "validation_failed"),
        ("local_missing", without("starts_at_local"), 422, "validation_failed"),
        ("local_number", {**ok, "starts_at_local": 1900}, 400, "malformed_request"),
        ("restaurant_number", {**ok, "restaurant_id": 7}, 400, "malformed_request"),
        ("table_number", {**ok, "table_id": 2}, 400, "malformed_request"),
        ("restaurant_missing", without("restaurant_id"), 422, "validation_failed"),
        ("table_missing", without("table_id"), 422, "validation_failed"),
        ("restaurant_65_chars", {**ok, "restaurant_id": "r" * 65}, 422, "validation_failed"),
        ("table_65_chars", {**ok, "table_id": "t" * 65}, 422, "validation_failed"),
        ("unknown_restaurant", {**ok, "restaurant_id": "r_nope"}, 404, "not_found"),
        ("unknown_table", {**ok, "table_id": "t_9"}, 404, "not_found"),
        ("other_restaurants_table", {**ok, "table_id": "t_x"}, 404, "not_found"),
    ]


INVALID_IDS = [case[0] for case in _invalid_bodies("2026-10-08")]


@pytest.mark.parametrize("case", INVALID_IDS)
def test_a_booking_that_breaks_a_rule_is_refused_and_leaves_nothing(reset, api, anon, case):
    """R98-R104/R55/R56/R58/D12/R9: each rule's status and code; a refused booking
    leaves no reservation and no occupancy behind."""
    date = fx.booking_date()
    reset(fx.fixture(restaurants=[fx.restaurant(), other_restaurant()]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    _, payload, status, code = next(c for c in _invalid_bodies(date) if c[0] == case)
    assert_error(create(ada, payload), status, code)
    assert references(ada) == []
    assert free_tables(anon, date, "19:00") == ["t_1", "t_2", "t_3"]


def test_the_table_is_taken_for_any_overlapping_interval(world, book):
    """R98/R8: occupancy is half-open: 19:00-20:30 blocks 18:00 and 20:00 on the same
    table, not 17:30 (ends at 19:00) or 20:30, and never another table."""
    assert_status(book(table_id="t_2", at="19:00"), 201)
    for at in ("18:00", "19:00", "20:00"):
        assert_error(book(table_id="t_2", at=at), 409, "table_unavailable")
    for at in ("20:30",):
        assert_status(book(table_id="t_2", at=at), 201)
    assert_status(book(table_id="t_3", at="19:00"), 201)


def test_a_booking_ending_exactly_when_the_next_starts_is_accepted(reset, api):
    """R8: a 90-minute booking ending at 19:00 does not overlap one starting at 19:00."""
    reset(fx.fixture(restaurants=[fx.restaurant(opening_hours=fx.all_week("17:00", "23:00"))]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    date = fx.booking_date()
    assert_status(create(ada, body(date, "19:00")), 201)
    assert_status(create(ada, body(date, "17:30")), 201)


def test_a_booking_in_the_past_is_accepted(world):
    """R45: a booking is not rejected solely because its start is in the past."""
    past = (dt.date.fromisoformat(world.date) - dt.timedelta(days=30)).isoformat()
    assert_status(create(world.ada, body(past)), 201)


@pytest.mark.parametrize("zone,date,at,start,end", [
    ("Europe/Berlin", BERLIN_FALL, "01:30", ("01:30", "+02:00"), ("02:00", "+01:00")),
    ("Europe/Berlin", BERLIN_FALL, "02:30", ("02:30", "+02:00"), ("03:00", "+01:00")),
    ("America/New_York", NY_FALL, "01:30", ("01:30", "-04:00"), ("02:00", "-05:00")),
    ("America/New_York", NY_FALL, "00:30", ("00:30", "-04:00"), ("01:00", "-05:00")),
    ("Europe/Berlin", BERLIN_SPRING, "01:30", ("01:30", "+01:00"), ("04:00", "+02:00")),
    ("America/New_York", NY_SPRING, "01:30", ("01:30", "-05:00"), ("04:00", "-04:00")),
])
def test_a_booking_resolves_the_first_occurrence_for_absolute_minutes(reset, api, zone, date,
                                                                      at, start, end):
    """R95/R123/R125/R126/R128: starts_at_local resolves in the restaurant zone, a
    repeated wall time to its first occurrence; the duration is absolute time."""
    reset(fx.fixture(restaurants=[fx.restaurant(timezone=zone,
                                                opening_hours=fx.all_week("00:00", "23:30"))]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    created = assert_status(create(ada, body(date, at)), 201).json()
    assert instant(created["starts_at"]) == (f"{date}T{start[0]}", start[1])
    assert instant(created["ends_at"]) == (f"{date}T{end[0]}", end[1])


@pytest.mark.parametrize("zone,date,at", [
    ("Europe/Berlin", BERLIN_SPRING, "02:00"), ("Europe/Berlin", BERLIN_SPRING, "02:30"),
    ("America/New_York", NY_SPRING, "02:00"), ("America/New_York", NY_SPRING, "02:30"),
])
def test_a_skipped_local_time_is_invalid_local_time(reset, api, zone, date, at):
    """R103/R122: a local time that does not exist is 422 invalid_local_time."""
    reset(fx.fixture(restaurants=[fx.restaurant(timezone=zone,
                                                opening_hours=fx.all_week("00:00", "23:30"))]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    assert_error(create(ada, body(date, at)), 422, "invalid_local_time")


def test_the_repeated_hour_is_bookable_once(reset, api):
    """R125: the second occurrence of 02:30 is not bookable: a second booking of that
    wall time is the same instant, and the table is taken until 02:00 UTC."""
    reset(fx.fixture(restaurants=[fx.restaurant(opening_hours=fx.all_week("00:00", "23:30"))]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    first = assert_status(create(ada, body(BERLIN_FALL, "02:30", table_id="t_2")), 201).json()
    assert_error(create(ada, body(BERLIN_FALL, "02:30", table_id="t_2")), 409, "table_unavailable")
    other = assert_status(create(ada, body(BERLIN_FALL, "02:30", table_id="t_3")), 201).json()
    assert other["starts_at"] == first["starts_at"]
    assert_status(create(ada, body(BERLIN_FALL, "03:00", table_id="t_2")), 201)


# ---- listed slots are bookable (§8, §9; the item's R88 block) ------------------------------

def _grid(step: int) -> list[str]:
    return [f"{m // 60:02d}:{m % 60:02d}" for m in range(0, 23 * 60 + 30, step)]


@pytest.mark.parametrize("step", [30, 45])
@pytest.mark.parametrize("zone,date", [("Europe/Berlin", BERLIN_SPRING),
                                       ("Europe/Berlin", BERLIN_FALL),
                                       ("America/New_York", NY_SPRING),
                                       ("America/New_York", NY_FALL)])
def test_every_listed_slot_books_and_every_skipped_grid_time_is_invalid(reset, api, anon,
                                                                        zone, date, step):
    """R88/R121/R122/R124: each slot availability lists books 201 unchanged on an empty
    table, at the listed instant; a grid time in the skipped hour is invalid_local_time."""
    tables = [{"id": f"t_{n}", "label": str(n), "capacity": 4} for n in range(50)]
    reset(fx.fixture(restaurants=[fx.restaurant(
        timezone=zone, slot_minutes=step, tables=tables,
        opening_hours=fx.all_week("00:00", "23:30"))]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    slots = assert_status(anon.get("/availability", params={
        "restaurant_id": "r_anker", "date": date, "party_size": 2}), 200).json()["slots"]
    assert slots
    for n, slot in enumerate(slots):
        created = create(ada, {"restaurant_id": "r_anker", "table_id": f"t_{n}",
                               "starts_at_local": slot["starts_at_local"], "party_size": 2})
        assert_status(created, 201)
        assert created.json()["starts_at"] == slot["starts_at"], (slot, created.json())
    listed = {slot["starts_at_local"][-5:] for slot in slots}
    skipped = [t for t in _grid(step) if "02:00" <= t < "03:00"]
    if date in (BERLIN_SPRING, NY_SPRING):
        assert skipped and not listed & set(skipped)
        for at in skipped:
            assert_error(create(ada, body(date, at, table_id="t_49", party_size=2)),
                         422, "invalid_local_time")


# ---- idempotency (§7) ----------------------------------------------------------------------

def test_the_key_is_required_and_bounded(world):
    """R48/R59/R75/R94: absent or empty key 400 missing_idempotency_key; 256
    characters 422 validation_failed; 255 characters is a valid first use."""
    payload = body(world.date)
    assert_error(world.ada.post("/reservations", json=payload), 400, "missing_idempotency_key")
    assert_error(world.ada.post("/reservations", json=payload, idempotency_key=""),
                 400, "missing_idempotency_key")
    assert_error(create(world.ada, payload, key="k" * 256), 422, "validation_failed")
    assert references(world.ada) == []
    assert_status(create(world.ada, payload, key="k" * 255), 201)


def test_a_replay_is_the_same_json_value_whatever_the_key_order_and_spacing(world):
    """R77/R80: a replay with the members reordered and re-spaced returns 200 with the
    original body and creates nothing."""
    key = new_key()
    payload = body(world.date)
    first = assert_status(create(world.ada, payload, key), 201).json()
    reordered = json.dumps(dict(reversed(list(payload.items()))), indent=4).encode()
    replay = world.ada.post("/reservations", content=reordered, idempotency_key=key)
    assert assert_status(replay, 200).json() == first
    assert references(world.ada) == [first["reference"]]


def test_the_same_key_with_a_different_body_is_reuse_even_if_invalid(world):
    """R52/R74/R78: a used key with another body is 409 idempotency_key_reuse, before
    any field or resource check; nothing is created."""
    key = new_key()
    assert_status(create(world.ada, body(world.date), key), 201)
    for other in (body(world.date, "20:30"), body(world.date, party_size=0),
                  body(world.date, party_size=True), {"restaurant_id": "r_nope"}):
        assert_error(create(world.ada, other, key), 409, "idempotency_key_reuse")
    assert len(references(world.ada)) == 1


def test_one_is_not_the_same_json_value_as_true(world):
    """R80: `1` and `true` are different JSON values, so the body is different."""
    key = new_key()
    assert_status(create(world.ada, body(world.date, party_size=1), key), 201)
    assert_error(create(world.ada, body(world.date, party_size=True), key), 409,
                 "idempotency_key_reuse")


def test_a_key_whose_request_failed_is_a_first_use(world, book):
    """R79/R9: after a 4xx the same key is a first use; a failed request left nothing."""
    key = new_key()
    assert_error(create(world.ada, body(world.date, "19:15"), key), 422, "not_on_slot_grid")
    assert_status(book(client=world.bob, table_id="t_2", at="19:00"), 201)
    assert_error(create(world.ada, body(world.date, "19:00"), key), 409, "table_unavailable")
    assert_status(create(world.ada, body(world.date, "20:30"), key), 201)
    assert len(references(world.ada)) == 1


def test_keys_belong_to_one_user(world):
    """R72: two users may use the same key string with no interaction."""
    key = new_key()
    assert_status(create(world.ada, body(world.date, table_id="t_2"), key), 201)
    assert_status(create(world.bob, body(world.date, table_id="t_3"), key), 201)
    assert len(references(world.bob)) == 1


def test_a_replay_returns_the_original_after_changes_and_changes_nothing(world, anon):
    """R82: a replay after a PATCH and after a cancel returns the original response,
    and it neither re-books the table nor undoes the changes."""
    key = new_key()
    payload = body(world.date, table_id="t_2")
    original = assert_status(create(world.ada, payload, key), 201).json()
    ref = original["reference"]
    assert_status(world.ada.patch(f"/reservations/{ref}", json={"table_id": "t_3"}), 200)
    assert assert_status(create(world.ada, payload, key), 200).json() == original
    assert reservation(world.ada, ref)["table_id"] == "t_3"
    assert "t_2" in free_tables(anon, world.date, "19:00")
    assert_status(world.ada.post(f"/reservations/{ref}/cancel"), 200)
    assert assert_status(create(world.ada, payload, key), 200).json() == original
    assert reservation(world.ada, ref)["status"] == "cancelled"
    assert free_tables(anon, world.date, "19:00") == ["t_1", "t_2", "t_3"]
    assert references(world.ada) == [ref]


def test_keyed_write_precedence(world, api):
    """D3: 401 before a bad body; a bad body before a missing key; a missing key before
    field checks."""
    assert_error(api().post("/reservations", content=b"{", token=None), 401, "unauthenticated")
    assert_error(world.ada.post("/reservations", content=b"{"), 400, "malformed_request")
    assert_error(world.ada.post("/reservations", content=b"[]", idempotency_key=new_key()),
                 400, "malformed_request")
    assert_error(world.ada.post("/reservations", json={"party_size": 0}), 400,
                 "missing_idempotency_key")


# ---- reads (§8) ------------------------------------------------------------------------------

def test_the_list_holds_confirmed_and_cancelled_latest_start_first(world, book):
    """R105: the caller's reservations, starts_at descending, cancelled included."""
    early = assert_status(book(table_id="t_1", at="18:00", party_size=2), 201).json()["reference"]
    late = assert_status(book(table_id="t_2", at="21:00"), 201).json()["reference"]
    middle = assert_status(book(table_id="t_3", at="19:30"), 201).json()["reference"]
    assert_status(world.ada.post(f"/reservations/{middle}/cancel"), 200)
    assert references(world.ada) == [late, middle, early]
    assert references(world.bob) == []


def test_someone_elses_booking_is_invisible_to_every_verb(world, book, api):
    """R106/R111/R119: another user's reservation is 404 on read, cancel and PATCH, and
    stays unchanged; without a token it is 401."""
    ref = assert_status(book(table_id="t_2"), 201).json()["reference"]
    before = reservation(world.ada, ref)
    assert_error(world.bob.get(f"/reservations/{ref}"), 404, "not_found")
    assert_error(world.bob.post(f"/reservations/{ref}/cancel"), 404, "not_found")
    assert_error(world.bob.patch(f"/reservations/{ref}", json={"party_size": 2}), 404, "not_found")
    anon = api()
    assert_error(anon.post(f"/reservations/{ref}/cancel", token=None), 401, "unauthenticated")
    assert_error(anon.patch(f"/reservations/{ref}", json={}, token=None), 401, "unauthenticated")
    assert reservation(world.ada, ref) == before


# ---- cancel (§8) -------------------------------------------------------------------------------

def test_cancel_answers_the_cancelled_booking_and_frees_the_table(world, book, anon):
    """R107/R108/R109: 200 with the booking as cancelled; the slot is offered again and
    bookable by someone else; cancelling twice answers the same state."""
    created = assert_status(book(table_id="t_2"), 201).json()
    ref = created["reference"]
    cancelled = assert_status(world.ada.post(f"/reservations/{ref}/cancel"), 200).json()
    assert cancelled == {**created, "status": "cancelled"}
    assert "t_2" in free_tables(anon, world.date, "19:00", 4)
    assert assert_status(world.ada.post(f"/reservations/{ref}/cancel"), 200).json() == cancelled
    assert_status(create(world.bob, body(world.date, table_id="t_2")), 201)
    assert reservation(world.ada, ref) == cancelled


@pytest.mark.parametrize("margin,expected", [(30, 409), (-30, 200)])
def test_cancel_is_refused_within_the_cutoff(reset, api, margin, expected):
    """R110/R36: cancelling within cancellation_cutoff_minutes of starts_at is 409
    cutoff_passed; outside it, 200."""
    date = fx.booking_date()
    cutoff = minutes_until(date, "19:00") + margin
    reset(fx.fixture(restaurants=[fx.restaurant(cancellation_cutoff_minutes=cutoff)]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    ref = assert_status(create(ada, body(date)), 201).json()["reference"]
    resp = ada.post(f"/reservations/{ref}/cancel")
    if expected == 409:
        assert_error(resp, 409, "cutoff_passed")
        assert reservation(ada, ref)["status"] == "confirmed"
    else:
        assert assert_status(resp, 200).json()["status"] == "cancelled"


def test_an_unknown_reference_cannot_be_cancelled(world):
    """R111: no such reservation is 404."""
    assert_error(world.ada.post("/reservations/NOPE99/cancel"), 404, "not_found")


# ---- PATCH (§8) --------------------------------------------------------------------------------

@pytest.mark.parametrize("change,expected", [
    ({"table_id": "t_3"}, {"table_id": "t_3"}),
    ({"starts_at_local": "20:30"}, {"starts_at_local": "20:30"}),
    ({"party_size": 2}, {"party_size": 2}),
    ({"table_id": "t_3", "starts_at_local": "18:00", "party_size": 6},
     {"table_id": "t_3", "starts_at_local": "18:00", "party_size": 6}),
    ({}, {}),
    ({"party_size": 4, "table_id": "t_2"}, {}),
])
def test_patch_changes_any_subset_and_keeps_the_identity(world, book, anon, change, expected):
    """R112/R116/R118: any subset of the three fields, no key needed; reference,
    reservation_id and created_at survive; the old slot is freed and the new one held."""
    created = assert_status(book(table_id="t_2", at="19:00", party_size=4), 201).json()
    ref = created["reference"]
    request = {k: fx.local(world.date, v) if k == "starts_at_local" else v for k, v in change.items()}
    amended = assert_status(world.ada.patch(f"/reservations/{ref}", json=request), 200).json()
    want = {**created, **{k: fx.local(world.date, v) if k == "starts_at_local" else v
                          for k, v in expected.items()}}
    for field in ("reference", "reservation_id", "created_at", "restaurant_id", "table_id",
                  "party_size", "starts_at_local", "status"):
        assert amended[field] == want[field], field
    assert reservation(world.ada, ref) == amended
    at = want["starts_at_local"][-5:]
    assert want["table_id"] not in free_tables(anon, world.date, at)
    if expected.get("table_id") or expected.get("starts_at_local"):
        assert "t_2" in free_tables(anon, world.date, "19:00")


def test_patch_onto_its_own_occupancy_moves_the_booking(world, book, anon):
    """R116: releasing the old slot and reserving the new one happen together, so a
    booking can move into time it held itself."""
    ref = assert_status(book(table_id="t_2", at="19:00"), 201).json()["reference"]
    amended = world.ada.patch(f"/reservations/{ref}",
                              json={"starts_at_local": fx.local(world.date, "19:30")})
    assert assert_status(amended, 200).json()["starts_at_local"] == fx.local(world.date, "19:30")
    assert "t_2" in free_tables(anon, world.date, "18:00")
    assert "t_2" not in free_tables(anon, world.date, "20:30")


def _failed_patches(date: str) -> list[tuple[str, dict, int, str]]:
    return [
        ("off_grid", {"starts_at_local": fx.local(date, "19:15")}, 422, "not_on_slot_grid"),
        ("ends_after_closes", {"starts_at_local": fx.local(date, "22:00")}, 422, "outside_opening_hours"),
        ("party_over_capacity", {"table_id": "t_1"}, 422, "party_exceeds_capacity"),
        ("party_zero", {"party_size": 0}, 422, "validation_failed"),
        ("party_string", {"party_size": "3"}, 422, "validation_failed"),
        ("local_bad_format", {"starts_at_local": f"{date}T19:00:00"}, 422, "validation_failed"),
        ("local_number", {"starts_at_local": 1900}, 400, "malformed_request"),
        ("table_number", {"table_id": 3}, 400, "malformed_request"),
        ("unknown_table", {"table_id": "t_9"}, 404, "not_found"),
        ("other_restaurants_table", {"table_id": "t_x"}, 404, "not_found"),
        ("taken", {"table_id": "t_3"}, 409, "table_unavailable"),
        ("skipped_time", {"starts_at_local": f"{BERLIN_SPRING}T02:30"}, 422, "invalid_local_time"),
    ]


PATCH_IDS = [case[0] for case in _failed_patches("2026-10-08")]


@pytest.mark.parametrize("case", PATCH_IDS)
def test_a_failed_patch_leaves_the_booking_and_its_occupancy(reset, api, anon, case):
    """R113/R117/R122: PATCH validates like POST /reservations; a refused change leaves
    the booking and its table exactly as they were."""
    date = fx.booking_date()
    reset(fx.fixture(restaurants=[fx.restaurant(opening_hours=fx.all_week("00:00", "23:00")),
                                  other_restaurant()]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    bob = api().authenticate(fx.BOB["email"], fx.BOB["password"])
    ref = assert_status(create(ada, body(date, table_id="t_2")), 201).json()["reference"]
    assert_status(create(bob, body(date, table_id="t_3")), 201)
    before = reservation(ada, ref)
    _, change, status, code = next(c for c in _failed_patches(date) if c[0] == case)
    assert_error(ada.patch(f"/reservations/{ref}", json=change), status, code)
    assert reservation(ada, ref) == before
    assert free_tables(anon, date, "19:00") == ["t_1"]


def test_patch_cutoff_is_measured_against_the_current_start(reset, api):
    """R114/R36: a booking whose current start is outside the cutoff may move inside it;
    once its start is inside the cutoff it cannot change (409 cutoff_passed)."""
    near = fx.booking_date()
    far = fx.booking_date(lead=21)
    reset(fx.fixture(restaurants=[fx.restaurant(
        cancellation_cutoff_minutes=minutes_until(near, "19:00") + 60)]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    ref = assert_status(create(ada, body(far)), 201).json()["reference"]
    moved = ada.patch(f"/reservations/{ref}", json={"starts_at_local": fx.local(near, "19:00")})
    assert assert_status(moved, 200).json()["starts_at_local"] == fx.local(near, "19:00")
    assert_error(ada.patch(f"/reservations/{ref}", json={"starts_at_local": fx.local(far, "19:00")}),
                 409, "cutoff_passed")
    assert_error(ada.patch(f"/reservations/{ref}", json={"party_size": 2}), 409, "cutoff_passed")
    assert reservation(ada, ref)["starts_at_local"] == fx.local(near, "19:00")


def test_a_cancelled_booking_cannot_be_amended(world, book):
    """R115: PATCH on a cancelled reservation is 409 reservation_cancelled."""
    ref = assert_status(book(table_id="t_2"), 201).json()["reference"]
    assert_status(world.ada.post(f"/reservations/{ref}/cancel"), 200)
    assert_error(world.ada.patch(f"/reservations/{ref}", json={"table_id": "t_3"}), 409,
                 "reservation_cancelled")
    assert reservation(world.ada, ref)["table_id"] == "t_2"


def test_patch_on_an_unknown_reference_is_404(world):
    """R51: no such reservation is 404."""
    assert_error(world.ada.patch("/reservations/NOPE99", json={"party_size": 2}), 404, "not_found")


# ---- no 5xx on odd input (§5) ------------------------------------------------------------------

ODD_CREATES = [
    b'{"restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": "2026-10-08T19:00", "party_size": 1e400}',
    b'{"restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": "9999-12-31T23:30", "party_size": 2}',
    b'{"restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": "0001-01-01T00:00", "party_size": 2}',
    b'{"restaurant_id": "r_\\u00fc\\u0000", "table_id": "t_\\ud800", "starts_at_local": "2026-10-08T19:00", "party_size": 2}',
    b'{"restaurant_id": {"id": "r_anker"}, "table_id": ["t_2"], "starts_at_local": {}, "party_size": {}}',
    b'{"restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": "2026-10-08T19:00", "party_size": 99999999999999999999999999}',
]


@pytest.mark.parametrize("raw", ODD_CREATES, ids=[f"c{i}" for i in range(len(ODD_CREATES))])
def test_odd_bookings_never_answer_5xx(world, raw):
    """R60: requests must not produce 5xx; a refusal carries the error envelope."""
    for send in (lambda: world.ada.post("/reservations", content=raw, idempotency_key=new_key()),
                 lambda: world.ada.patch("/reservations/NOPE99", content=raw)):
        resp = send()
        assert resp.status_code < 500, f"{resp.request.method} -> {resp.status_code} {resp.text[:200]}"
        if resp.status_code >= 400:
            error_code(resp)
