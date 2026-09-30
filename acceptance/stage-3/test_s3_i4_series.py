"""S3-I4 acceptance checks (verifier seat): recurring reservations, from the stage-3
specification ("Recurring reservations", "Collective moves under policies and agreements")
with the plan's H4, P5, the critic's B1 (the anchor's accepted cutoff) and B2 (each
occurrence's own duration), and S3N-3 (the series path's keyed-write basics).

R.., H.. and P.. name the room plan's requirement lines and decisions.
"""
from __future__ import annotations

import datetime as dt

import pytest

import fixtures as fx
from harness.http import assert_error, assert_status, new_key

pytestmark = pytest.mark.stage(3)

DATE = fx.booking_date()                     # 7 days ahead
NEAR = fx.booking_date(lead=3)               # inside a 7-day (10080-minute) cutoff
SERIES_KEYS = {"series_id", "revision", "interval_weeks", "occurrences"}
POLICY_0 = {"policy_version": 0, "slot_minutes": 30, "reservation_duration_minutes": 90,
            "cancellation_cutoff_minutes": 120, "opening_hours": fx.all_week(),
            "capacities": {"t_1": 2, "t_2": 4, "t_3": 6}}


def weeks(date: str, n: int) -> str:
    return (dt.date.fromisoformat(date) + dt.timedelta(weeks=n)).isoformat()


def restaurant(**overrides) -> dict:
    return {**fx.managed_restaurant(**overrides), "combinable": [["t_1", "t_2"]]}


@pytest.fixture
def world(reset, api):
    reset(fx.fixture(restaurants=[restaurant()]))
    return (api().authenticate(fx.ADA["email"], fx.ADA["password"]),
            api().authenticate(fx.BOB["email"], fx.BOB["password"]))


def book(client, date=DATE, hhmm="19:00", party=2, key=None, **tables):
    return client.post("/reservations", idempotency_key=key or new_key(), json={
        "restaurant_id": "r_anker", **(tables or {"table_id": "t_2"}), "starts_at_local": fx.local(date, hhmm),
        "party_size": party})


def adopt(client, reference, count=3, interval=1, key=None, **extra):
    return client.post("/series", idempotency_key=key or new_key(), json={
        "anchor_reference": reference, "count": count, "interval_weeks": interval, **extra})


def publish(client, date, **overrides):
    assert_status(client.post("/restaurants/r_anker/policies", idempotency_key=new_key(),
                              json=fx.policy(date, **overrides)), 201)


def mine(client) -> list:
    return assert_status(client.get("/reservations"), 200).json()["reservations"]


def read_series(client, series_id) -> dict:
    return assert_status(client.get(f"/series/{series_id}"), 200).json()


def history(client, reference) -> list:
    return assert_status(client.get(f"/reservations/{reference}/history"), 200).json()["entries"]


def minutes(booking) -> int:
    return int((dt.datetime.fromisoformat(booking["ends_at"])
                - dt.datetime.fromisoformat(booking["starts_at"])).total_seconds() // 60)


# ---- adoption (R343, R346, R347, R350, R352, R353) -------------------------------------------------

def test_adoption_answers_the_series_with_the_anchor_as_occurrence_zero(world):
    """R343/R346/R347/R352/R353: 201 with series_id, revision 1, interval_weeks and every
    occurrence in index order, each `exception` false with its ordinary reservation; occurrence
    0 is the anchor exactly as its create answered (reference, identity, revision, terms,
    timestamps), and its history and original key are untouched; occurrence i starts on the
    anchor's date plus i x interval x 7 days at the same clock time, with distinct references."""
    ada, _ = world
    key = new_key()
    created = assert_status(book(ada, party=4, key=key), 201).json()
    before = history(ada, created["reference"])
    answer = assert_status(adopt(ada, created["reference"], count=3, interval=2), 201).json()
    assert set(answer) == SERIES_KEYS and isinstance(answer["series_id"], str)
    assert (answer["revision"], answer["interval_weeks"]) == (1, 2)
    occurrences = answer["occurrences"]
    assert [o["index"] for o in occurrences] == [0, 1, 2]
    assert all(set(o) == {"index", "reference", "exception", "reservation"} and o["exception"] is False
               and o["reservation"]["reference"] == o["reference"] for o in occurrences)
    assert occurrences[0]["reservation"] == created
    assert len({o["reference"] for o in occurrences}) == 3
    for index, occurrence in enumerate(occurrences[1:], start=1):
        booking = occurrence["reservation"]
        assert (booking["starts_at_local"], booking["table_id"], booking["party_size"], booking["status"],
                booking["revision"], booking["accepted_terms"]) == (
            fx.local(weeks(DATE, 2 * index)), "t_2", 4, "confirmed", 1, POLICY_0), index
    assert history(ada, created["reference"]) == before
    assert assert_status(book(ada, party=4, key=key), 200).json() == created


def test_a_pair_anchor_repeats_its_table_selection_and_party(world):
    """R350: generated occurrences use the anchor's party size and table selection, a pair in
    declared order included."""
    ada, _ = world
    anchor = assert_status(book(ada, party=5, table_ids=["t_2", "t_1"]), 201).json()
    answer = assert_status(adopt(ada, anchor["reference"], count=3), 201).json()
    assert [(o["reservation"]["table_ids"], o["reservation"]["party_size"]) for o in answer["occurrences"]] == \
        [(["t_1", "t_2"], 5)] * 3


def test_occurrences_are_ordinary_bookings(world, anon):
    """R354/R355: occurrences appear in the owner's list as their ordinary reservations, occupy
    their tables and have ordinary `created` histories; GET /series answers the same shape."""
    ada, bob = world
    anchor = assert_status(book(ada), 201).json()
    answer = assert_status(adopt(ada, anchor["reference"], count=3), 201).json()
    listed = {b["reference"]: b for b in mine(ada)}
    for occurrence in answer["occurrences"]:
        assert listed[occurrence["reference"]] == occurrence["reservation"]
    for index, occurrence in enumerate(answer["occurrences"][1:], start=1):
        [entry] = history(ada, occurrence["reference"])
        assert (entry["event"], entry["revision"], entry["changes"][1]["to"]) == (
            "created", 1, fx.local(weeks(DATE, index)))
        slots = assert_status(anon.get("/availability", params={"restaurant_id": "r_anker", "date": weeks(DATE, index),
                                                                "party_size": 2}), 200).json()["slots"]
        assert "t_2" not in next(s for s in slots if s["starts_at_local"].endswith("T19:00"))["available_table_ids"]
        assert_error(book(bob, weeks(DATE, index)), 409, "table_unavailable")
    assert read_series(ada, answer["series_id"]) == answer


def test_only_the_owner_reads_a_series(world, anon, api):
    """R355: another user, no token or an unknown token gets 404 not_found; so does an unknown
    series id."""
    ada, bob = world
    answer = assert_status(adopt(ada, assert_status(book(ada), 201).json()["reference"], count=2), 201).json()
    for client in (bob, anon, api("not-a-token")):
        assert_error(client.get(f"/series/{answer['series_id']}"), 404, "not_found")
    assert_error(ada.get("/series/ser_nope"), 404, "not_found")


# ---- dates, policies, DST (R347, R348, R349) --------------------------------------------------------

def open_all_day(reset, api):
    reset(fx.fixture(restaurants=[restaurant(opening_hours=fx.all_week("00:00", "23:30"))]))
    return api().authenticate(fx.ADA["email"], fx.ADA["password"])


def test_occurrences_keep_the_local_clock_time_across_a_dst_change(reset, api):
    """R347/R348: occurrences keep the anchor's local clock time when the offset changes
    (Europe/Berlin leaves summer time on 2026-10-25)."""
    ada = open_all_day(reset, api)
    anchor = assert_status(book(ada, "2026-10-14"), 201).json()
    answer = assert_status(adopt(ada, anchor["reference"], count=3), 201).json()
    assert [o["reservation"]["starts_at"] for o in answer["occurrences"]] == [
        "2026-10-14T19:00:00+02:00", "2026-10-21T19:00:00+02:00", "2026-10-28T19:00:00+01:00"]


def test_a_nonexistent_local_time_rejects_the_whole_adoption(reset, api):
    """R349/R351: an occurrence falling in the spring-forward gap (2027-03-28 02:30 in Berlin)
    rejects the adoption with 422 invalid_local_time and creates nothing; the anchor can still
    be adopted with another interval."""
    ada = open_all_day(reset, api)
    anchor = assert_status(book(ada, "2027-03-21", "02:30"), 201).json()
    key = new_key()
    assert_error(adopt(ada, anchor["reference"], count=2, key=key), 422, "invalid_local_time")
    assert [b["reference"] for b in mine(ada)] == [anchor["reference"]]
    answer = assert_status(adopt(ada, anchor["reference"], count=2, interval=2, key=new_key()), 201).json()
    assert answer["occurrences"][1]["reservation"]["starts_at"] == "2027-04-04T02:30:00+02:00"


def test_a_repeated_local_time_takes_its_first_occurrence(reset, api):
    """R349: an occurrence in the repeated hour (2026-10-25 02:30 in Berlin) takes the first
    occurrence, summer time."""
    ada = open_all_day(reset, api)
    anchor = assert_status(book(ada, "2026-10-18", "02:30"), 201).json()
    answer = assert_status(adopt(ada, anchor["reference"], count=2), 201).json()
    assert answer["occurrences"][1]["reservation"]["starts_at"] == "2026-10-25T02:30:00+02:00"


def test_each_occurrence_selects_its_own_dates_policy(world):
    """R348: each generated occurrence takes the policy of its own date (duration, terms); the
    anchor keeps its own; a capacity the party exceeds on a later date refuses the adoption."""
    ada, _ = world
    anchor = assert_status(book(ada, party=3), 201).json()
    publish(ada, weeks(DATE, 1), reservation_duration_minutes=30)
    publish(ada, weeks(DATE, 2), reservation_duration_minutes=60)
    answer = assert_status(adopt(ada, anchor["reference"], count=3), 201).json()
    assert [(o["reservation"]["accepted_terms"]["policy_version"], minutes(o["reservation"]))
            for o in answer["occurrences"]] == [(0, 90), (1, 30), (2, 60)]
    other = assert_status(book(ada, hhmm="21:00", party=3), 201).json()
    publish(ada, weeks(DATE, 3), capacities={"t_1": 2, "t_2": 2, "t_3": 6})
    assert_error(adopt(ada, other["reference"], count=4), 422, "party_exceeds_capacity")
    assert len(mine(ada)) == 4


# ---- failure (R351, P5) ----------------------------------------------------------------------------------

def test_a_failure_at_the_third_occurrence_leaves_nothing_and_the_key_reusable(world, anon):
    """R351: occurrence 3's table is taken: 409 table_unavailable; no occurrence, history,
    series or receipt survives (occurrences 1 and 2 hold nothing); once the table is free, the
    same key and body adopt."""
    ada, bob = world
    anchor = assert_status(book(ada), 201).json()
    blocker = assert_status(book(bob, weeks(DATE, 3)), 201).json()
    key = new_key()
    assert_error(adopt(ada, anchor["reference"], count=4, key=key), 409, "table_unavailable")
    assert [b["reference"] for b in mine(ada)] == [anchor["reference"]]
    for n in (1, 2):
        slots = assert_status(anon.get("/availability", params={"restaurant_id": "r_anker", "date": weeks(DATE, n),
                                                                "party_size": 2}), 200).json()["slots"]
        assert "t_2" in next(s for s in slots if s["starts_at_local"].endswith("T19:00"))["available_table_ids"], n
    assert len(history(ada, anchor["reference"])) == 1
    assert_status(bob.post(f"/reservations/{blocker['reference']}/cancel"), 200)
    answer = assert_status(adopt(ada, anchor["reference"], count=4, key=key), 201).json()
    assert len(answer["occurrences"]) == 4


def rule_then_occupancy(ada, bob):
    publish(ada, weeks(DATE, 1), opening_hours=fx.all_week("12:00", "16:00"))
    publish(ada, weeks(DATE, 2))
    assert_status(book(bob, weeks(DATE, 2)), 201)
    return 422, "outside_opening_hours"


def occupancy_then_rule(ada, bob):
    assert_status(book(bob, weeks(DATE, 1)), 201)
    publish(ada, weeks(DATE, 2), opening_hours=fx.all_week("12:00", "16:00"))
    return 409, "table_unavailable"


@pytest.mark.parametrize("arrange", [rule_then_occupancy, occupancy_then_rule], ids=lambda f: f.__name__)
def test_the_first_failing_occurrence_in_index_order_decides(world, arrange):
    """R351/P5: when occurrence 1 breaks a booking rule and occurrence 2 is occupied, the rule's
    error is answered; when occurrence 1 is occupied and occurrence 2 breaks a rule, 409
    table_unavailable; nothing is created either way."""
    ada, bob = world
    anchor = assert_status(book(ada), 201).json()
    status, code = arrange(ada, bob)
    assert_error(adopt(ada, anchor["reference"], count=3), status, code)
    assert [b["reference"] for b in mine(ada)] == [anchor["reference"]]


# ---- the anchor and the fields (R344, R345) ---------------------------------------------------------------

def test_the_anchor_must_be_the_callers_confirmed_unadopted_booking(world, reset, api, anon):
    """R344/R345: an unknown or another owner's anchor 404; a cancelled one 409
    reservation_cancelled; an adopted anchor or a generated occurrence 409 already_in_series;
    no token 401; an anchor inside its cutoff 409 cutoff_passed."""
    ada, bob = world
    assert_error(adopt(ada, "NOPE9999"), 404, "not_found")
    theirs = assert_status(book(bob, table_id="t_3"), 201).json()
    assert_error(adopt(ada, theirs["reference"]), 404, "not_found")
    cancelled = assert_status(book(ada, hhmm="21:00"), 201).json()
    assert_status(ada.post(f"/reservations/{cancelled['reference']}/cancel"), 200)
    assert_error(adopt(ada, cancelled["reference"]), 409, "reservation_cancelled")
    anchor = assert_status(book(ada), 201).json()
    answer = assert_status(adopt(ada, anchor["reference"], count=2), 201).json()
    assert_error(adopt(ada, anchor["reference"]), 409, "already_in_series")
    assert_error(adopt(ada, answer["occurrences"][1]["reference"]), 409, "already_in_series")
    assert_error(adopt(anon, anchor["reference"]), 401, "unauthenticated")
    reset(fx.fixture(restaurants=[restaurant()], reservations=[{
        "id": "res_PAST01", "reference": "PAST01", "user_id": "u_ada", "restaurant_id": "r_anker", "table_id": "t_2",
        "starts_at_local": fx.local(fx.booking_date(lead=-1)), "party_size": 2}]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    assert_error(adopt(ada, "PAST01"), 409, "cutoff_passed")


INVALID = {
    "count_1": {"count": 1}, "count_13": {"count": 13}, "count_string": {"count": "3"}, "count_float": {"count": 2.5},
    "count_null": {"count": None}, "count_missing": {"count": ...},
    "interval_0": {"interval_weeks": 0}, "interval_5": {"interval_weeks": 5}, "interval_true": {"interval_weeks": True},
    "interval_string": {"interval_weeks": "1"}, "interval_float": {"interval_weeks": 1.5},
    "interval_missing": {"interval_weeks": ...},
    "anchor_missing": {"anchor_reference": ...}, "anchor_number": {"anchor_reference": 7},
    "anchor_65_chars": {"anchor_reference": "A" * 65},
}


@pytest.mark.parametrize("case", list(INVALID))
def test_invalid_count_interval_or_anchor_is_422_and_creates_nothing(world, case):
    """R345/D12: `count` outside 2..12, `interval_weeks` outside 1..4, a boolean interval,
    strings, fractions, null, missing fields and an anchor reference over 64 characters are 422
    validation_failed; nothing is created."""
    ada, _ = world
    anchor = assert_status(book(ada), 201).json()
    body = {"anchor_reference": anchor["reference"], "count": 3, "interval_weeks": 1}
    for name, value in INVALID[case].items():
        if value is ...:
            body.pop(name)
        else:
            body[name] = value
    assert_error(ada.post("/series", idempotency_key=new_key(), json=body), 422, "validation_failed")
    assert len(mine(ada)) == 1


@pytest.mark.parametrize("count,interval", [(2, 1), (12, 4)])
def test_the_range_bounds_are_accepted(world, count, interval):
    """R345: count 2 and 12, interval_weeks 1 and 4 are valid; unknown fields are ignored."""
    ada, _ = world
    anchor = assert_status(book(ada), 201).json()
    answer = assert_status(adopt(ada, anchor["reference"], count=count, interval=interval, note="weekly"), 201).json()
    assert len(answer["occurrences"]) == count
    assert answer["occurrences"][-1]["reservation"]["starts_at_local"] == fx.local(weeks(DATE, (count - 1) * interval))


# ---- series effects (R356, R357, R358, R369) --------------------------------------------------------

def test_patches_and_cancels_change_the_series_as_specified(world):
    """R356/R357/R358: a no-op or failed PATCH changes neither the series revision nor any
    exception; each real PATCH marks the occurrence an exception for good and adds one
    revision; a cancel adds one revision, keeps the occurrence and marks no exception; a
    repeated cancel nothing; cancelling the anchor leaves its siblings confirmed."""
    ada, _ = world
    anchor = assert_status(book(ada), 201).json()
    sid = assert_status(adopt(ada, anchor["reference"], count=3), 201).json()["series_id"]
    first, second = (o["reference"] for o in read_series(ada, sid)["occurrences"][1:])

    def state():
        found = read_series(ada, sid)
        return found["revision"], [o["exception"] for o in found["occurrences"]]

    assert_status(ada.patch(f"/reservations/{first}", json={}), 200)
    assert_status(ada.patch(f"/reservations/{first}", json={"party_size": 2}), 200)
    assert_error(ada.patch(f"/reservations/{first}", json={"party_size": 0}), 422, "validation_failed")
    assert state() == (1, [False, False, False])
    assert_status(ada.patch(f"/reservations/{first}", json={"party_size": 3}), 200)
    assert state() == (2, [False, True, False])
    assert_status(ada.patch(f"/reservations/{first}", json={"party_size": 2}), 200)
    assert state() == (3, [False, True, False])
    assert_status(ada.post(f"/reservations/{second}/cancel"), 200)
    assert_status(ada.post(f"/reservations/{second}/cancel"), 200)
    assert state() == (4, [False, True, False])
    assert_status(ada.post(f"/reservations/{anchor['reference']}/cancel"), 200)
    found = read_series(ada, sid)
    assert (found["revision"], [o["exception"] for o in found["occurrences"]]) == (5, [False, True, False])
    assert [o["reservation"]["status"] for o in found["occurrences"]] == ["cancelled", "confirmed", "cancelled"]


def test_a_move_changes_each_series_once(world):
    """R369: a move changing two occurrences of one series adds one series revision and marks
    both exceptions; its replay and a failed batch change nothing."""
    ada, bob = world
    anchor = assert_status(book(ada), 201).json()
    sid = assert_status(adopt(ada, anchor["reference"], count=3), 201).json()["series_id"]
    first, second = (o["reference"] for o in read_series(ada, sid)["occurrences"][1:])
    key = new_key()
    body = {"moves": [{"reference": first, "party_size": 3}, {"reference": second, "starts_at_local":
                                                                fx.local(weeks(DATE, 2), "20:00")}]}
    assert_status(ada.post("/reservation-moves", idempotency_key=key, json=body), 201)
    after = read_series(ada, sid)
    assert (after["revision"], [o["exception"] for o in after["occurrences"]]) == (2, [False, True, True])
    assert_status(ada.post("/reservation-moves", idempotency_key=key, json=body), 200)
    assert_status(book(bob, weeks(DATE, 1), "21:00"), 201)
    assert_error(ada.post("/reservation-moves", idempotency_key=new_key(), json={"moves": [
        {"reference": anchor["reference"], "party_size": 3},
        {"reference": first, "starts_at_local": fx.local(weeks(DATE, 1), "20:30")}]}), 409, "table_unavailable")
    assert read_series(ada, sid) == after


def test_a_replayed_adoption_answers_the_original_and_changes_nothing(world):
    """R360: after later changes, the same key and body answer 200 with the original series
    body; no counter changes."""
    ada, _ = world
    anchor = assert_status(book(ada), 201).json()
    key = new_key()
    original = assert_status(adopt(ada, anchor["reference"], count=2, key=key), 201).json()
    assert_status(ada.patch(f"/reservations/{original['occurrences'][1]['reference']}", json={"party_size": 3}), 200)
    now = read_series(ada, original["series_id"])
    assert assert_status(adopt(ada, anchor["reference"], count=2, key=key), 200).json() == original
    assert read_series(ada, original["series_id"]) == now and now["revision"] == 2


# ---- B1, B2 and the keyed-write basics -------------------------------------------------------------------

def test_the_anchors_accepted_cutoff_decides(world):
    """R344 (B1): an anchor accepted under cutoff 120 is still adoptable after a same-date
    policy with cutoff 10080; one accepted under 10080 stays refused (409 cutoff_passed) after a
    same-date policy with cutoff 0."""
    ada, _ = world
    short = assert_status(book(ada, NEAR), 201).json()
    publish(ada, NEAR, cancellation_cutoff_minutes=10080)
    assert_status(adopt(ada, short["reference"], count=2), 201)
    long = assert_status(book(ada, NEAR, table_id="t_3"), 201).json()
    publish(ada, NEAR, cancellation_cutoff_minutes=0)
    assert_error(adopt(ada, long["reference"], count=2), 409, "cutoff_passed")


def test_occurrences_occupy_their_own_duration(world, anon):
    """R348 (B2): occurrences under a 30-minute policy hold 19:00-19:30 only, while the anchor
    keeps its 90 minutes: availability with and without explain equals the reference; a create
    just inside each end is 409, just after it 201."""
    ada, bob = world
    anchor = assert_status(book(ada), 201).json()
    publish(ada, weeks(DATE, 1), reservation_duration_minutes=30)
    assert_status(adopt(ada, anchor["reference"], count=3), 201)
    for n in (1, 2):
        date = weeks(DATE, n)
        params = {"restaurant_id": "r_anker", "date": date, "party_size": 1}
        plain = assert_status(anon.get("/availability", params=params), 200).json()["slots"]
        explained = assert_status(anon.get("/availability", params={**params, "explain": "true"}), 200).json()["slots"]
        for slot, why in zip(plain, explained, strict=True):
            start = int(slot["starts_at_local"][11:13]) * 60 + int(slot["starts_at_local"][14:16])
            free = start + 30 <= 19 * 60 or start >= 19 * 60 + 30
            assert ("t_2" in slot["available_table_ids"]) is free, slot["starts_at_local"]
            assert next(e for e in why["explain"] if e["table_id"] == "t_2")["rules"][1]["holds"] is free
        assert_error(book(bob, date, "19:00", party=1), 409, "table_unavailable")
        assert_status(book(bob, date, "19:30", party=1), 201)
    assert_error(book(bob, DATE, "20:00", party=1), 409, "table_unavailable")
    assert_status(book(bob, DATE, "20:30", party=1), 201)


def test_the_series_path_follows_the_keyed_write_rules(world):
    """R360/S3N-3/D3: a missing key 400, a key over 255 characters 422, a reused key with
    another body 409; the same key and body on /reservations and /series do not interact."""
    ada, _ = world
    anchor = assert_status(book(ada), 201).json()
    body = {"anchor_reference": anchor["reference"], "count": 2, "interval_weeks": 1}
    assert_error(ada.post("/series", json=body), 400, "missing_idempotency_key")
    assert_error(ada.post("/series", json=body, idempotency_key="k" * 256), 422, "validation_failed")
    key = new_key()
    assert_status(book(ada, hhmm="21:00", key=key), 201)
    assert_status(ada.post("/series", json=body, idempotency_key=key), 201)
    assert_error(ada.post("/series", json={**body, "count": 3}, idempotency_key=key), 409, "idempotency_key_reuse")
