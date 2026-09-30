"""S3-I1 acceptance checks (verifier seat): publishing dated policies, their validation, the
managers, and which policy governs a date, from the stage-3 specification ("Policies and
accepted terms") with the plan's P1, P2, P6-P8 and D2/D3.

R.., H.. and P.. name the room plan's requirement lines and decisions.
"""
from __future__ import annotations

import datetime as dt

import pytest

import fixtures as fx
from harness.http import assert_error, assert_status, new_key

pytestmark = pytest.mark.stage(3)

DATE = fx.booking_date()


def shifted(days: int) -> str:
    return (dt.date.fromisoformat(DATE) + dt.timedelta(days=days)).isoformat()


def managed(rid="r_anker", name="Zum Anker", managers=("u_ada",), **overrides) -> dict:
    return {**fx.restaurant(rid, name=name, **overrides), "combinable": [["t_1", "t_2"]],
            "manager_user_ids": list(managers)}


@pytest.fixture
def world(reset, api):
    reset(fx.fixture(restaurants=[managed(), managed("r_other", name="Zum Anderen")]))
    return (api().authenticate(fx.ADA["email"], fx.ADA["password"]),
            api().authenticate(fx.BOB["email"], fx.BOB["password"]))


def publish(client, body, rid="r_anker", key=None):
    return client.post(f"/restaurants/{rid}/policies", json=body, idempotency_key=key or new_key())


def book(client, table: str, date: str, hhmm: str = "19:00", party: int = 2, rid="r_anker"):
    return client.post("/reservations", idempotency_key=new_key(), json={
        "restaurant_id": rid, "table_id": table, "starts_at_local": fx.local(date, hhmm), "party_size": party})


def listed(anon, rid="r_anker") -> list:
    return assert_status(anon.get(f"/restaurants/{rid}/policies"), 200).json()["policies"]


# ---- the endpoint (R319, R321, R322, P2, D2, D3) --------------------------------------------------

def test_publishing_needs_a_token_a_known_restaurant_and_a_manager(world, anon):
    """R319/P2: no token 401; unknown restaurant 404; a signed-in non-manager 403, before any
    field check; a manager 201 with the supplied policy plus `policy_version` 1."""
    ada, bob = world
    body = fx.policy(DATE, reservation_duration_minutes=60)
    assert_error(anon.post("/restaurants/r_anker/policies", json=body, idempotency_key=new_key()),
                 401, "unauthenticated")
    assert_error(publish(ada, body, rid="r_nope"), 404, "not_found")
    assert_error(publish(bob, body), 403, "forbidden")
    assert_error(publish(bob, {"effective_from": "not a date"}), 403, "forbidden")
    created = assert_status(publish(ada, body), 201).json()
    assert created == {**body, "policy_version": 1}


def test_a_replay_answers_the_same_body_and_allocates_nothing(world, anon):
    """R321/R322/§7: the same key and body replays 200 with the original body; the same key
    with another body is 409 idempotency_key_reuse; neither allocates a version."""
    ada, _ = world
    key, body = new_key(), fx.policy(DATE)
    first = assert_status(publish(ada, body, key=key), 201).json()
    assert assert_status(publish(ada, body, key=key), 200).json() == first
    assert_error(publish(ada, fx.policy(shifted(1)), key=key), 409, "idempotency_key_reuse")
    assert assert_status(publish(ada, fx.policy(shifted(2))), 201).json()["policy_version"] == 2
    assert [p["policy_version"] for p in listed(anon)] == [1, 2]


def test_the_policy_path_follows_the_keyed_write_rules(world):
    """R321/D3/D2: a missing key is 400, a key over 255 characters 422, a body that is not an
    object 400; one key and body on /policies and on /reservations do not interact."""
    ada, _ = world
    assert_error(ada.post("/restaurants/r_anker/policies", json=fx.policy(DATE)), 400, "missing_idempotency_key")
    assert_error(publish(ada, fx.policy(DATE), key="k" * 256), 422, "validation_failed")
    assert_error(ada.post("/restaurants/r_anker/policies", json=[fx.policy(DATE)], idempotency_key=new_key()),
                 400, "malformed_request")
    key = new_key()
    assert_status(publish(ada, fx.policy(DATE), key=key), 201)
    assert_status(ada.post("/reservations", idempotency_key=key, json={
        "restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": fx.local(DATE), "party_size": 2}), 201)


def test_versions_count_per_restaurant(world, anon):
    """R322: versions start at 1 and grow by one per restaurant, another restaurant's
    publications aside."""
    ada, _ = world
    versions = [assert_status(publish(ada, fx.policy(shifted(i))), 201).json()["policy_version"] for i in range(3)]
    other = assert_status(publish(ada, fx.policy(DATE), rid="r_other"), 201).json()["policy_version"]
    assert (versions, other) == ([1, 2, 3], 1)
    assert [p["policy_version"] for p in listed(anon, "r_other")] == [1]


# ---- validation (R325, R326, P1, P7) -------------------------------------------------------------

def without(field):
    return lambda body: body.pop(field)


def put(field, value):
    return lambda body: body.__setitem__(field, value)


def cap(table, value):
    return lambda body: body["capacities"].__setitem__(table, value)


INVALID = {
    **{f"missing_{f}": without(f) for f in ("effective_from", "slot_minutes", "reservation_duration_minutes",
                                             "cancellation_cutoff_minutes", "opening_hours", "capacities")},
    "effective_from_not_a_date": put("effective_from", "2026-02-30"),
    "effective_from_short": put("effective_from", "2026-9-1"),
    "effective_from_basic_format": put("effective_from", "20260901"),
    "effective_from_number": put("effective_from", 20260901),
    "effective_from_null": put("effective_from", None),
    "slot_0": put("slot_minutes", 0), "slot_1441": put("slot_minutes", 1441),
    "slot_true": put("slot_minutes", True), "slot_string": put("slot_minutes", "30"), "slot_float": put("slot_minutes", 30.5),
    "duration_0": put("reservation_duration_minutes", 0), "duration_1441": put("reservation_duration_minutes", 1441),
    "duration_true": put("reservation_duration_minutes", True),
    "cutoff_negative": put("cancellation_cutoff_minutes", -1), "cutoff_10081": put("cancellation_cutoff_minutes", 10081),
    "cutoff_false": put("cancellation_cutoff_minutes", False), "cutoff_float": put("cancellation_cutoff_minutes", 60.5),
    "hours_not_a_list": put("opening_hours", "mon 18-23"),
    "hours_duplicate_weekday": put("opening_hours", [{"weekday": "mon", "opens": "12:00", "closes": "14:00"},
                                                     {"weekday": "mon", "opens": "18:00", "closes": "23:00"}]),
    "hours_bad_weekday": put("opening_hours", [{"weekday": "monday", "opens": "18:00", "closes": "23:00"}]),
    "hours_closes_before_opens": put("opening_hours", [{"weekday": "mon", "opens": "23:00", "closes": "18:00"}]),
    "hours_bad_time": put("opening_hours", [{"weekday": "mon", "opens": "25:00", "closes": "26:00"}]),
    "capacities_missing_a_table": lambda body: body["capacities"].pop("t_3"),
    "capacities_extra_table": cap("t_9", 4),
    "capacity_0": cap("t_1", 0), "capacity_101": cap("t_1", 101), "capacity_true": cap("t_1", True),
    "capacity_string": cap("t_1", "2"), "capacity_float": cap("t_1", 2.5),
    "capacities_not_an_object": put("capacities", [2, 4, 6]),
}


@pytest.mark.parametrize("case", list(INVALID))
def test_an_invalid_policy_is_422_and_allocates_nothing(world, anon, case):
    """R325/P1/P7: every missing, mistyped or out-of-range field (booleans are not integers,
    `effective_from` a real YYYY-MM-DD date, capacities exactly the tables with 1..100, no
    weekday twice) is 422 validation_failed, lists nothing and allocates no version."""
    ada, _ = world
    body = fx.policy(DATE)
    INVALID[case](body)
    assert_error(publish(ada, body), 422, "validation_failed")
    assert listed(anon) == []
    assert assert_status(publish(ada, fx.policy(DATE)), 201).json()["policy_version"] == 1


BOUNDS = {"slot_1": ("slot_minutes", 1), "slot_1440": ("slot_minutes", 1440),
          "duration_1": ("reservation_duration_minutes", 1), "duration_1440": ("reservation_duration_minutes", 1440),
          "cutoff_0": ("cancellation_cutoff_minutes", 0), "cutoff_10080": ("cancellation_cutoff_minutes", 10080)}


@pytest.mark.parametrize("case", [*BOUNDS, "capacity_1", "capacity_100"])
def test_the_range_bounds_are_accepted(world, anon, case):
    """R325: grid and duration of 1 and 1440, a cutoff of 0 and 10080, a capacity of 1 and 100
    are valid: 201 with the policy as supplied, listed as version 1."""
    ada, _ = world
    body = fx.policy(DATE)
    if case in BOUNDS:
        field, value = BOUNDS[case]
        body[field] = value
    else:
        body["capacities"]["t_1"] = int(case.split("_")[1])
    created = assert_status(publish(ada, body), 201).json()
    assert created == {**body, "policy_version": 1}
    assert listed(anon) == [created]


def test_unknown_fields_are_ignored_and_change_no_restaurant_setting(world, anon):
    """R326: unknown fields do not refuse a policy, and a policy cannot change the restaurant's
    table ids, labels, timezone or declared combinations: availability under it keeps the
    restaurant's timezone and its declared pair, and the detail is unchanged."""
    ada, _ = world
    before = assert_status(anon.get("/restaurants/r_anker"), 200).json()
    body = {**fx.policy(DATE), "label": "Winter", "timezone": "Asia/Tokyo", "combinable": [],
            "tables": [{"id": "t_9", "label": "9", "capacity": 4}], "name": "Renamed"}
    created = assert_status(publish(ada, body), 201).json()
    assert created["policy_version"] == 1
    day = assert_status(anon.get("/availability", params={"restaurant_id": "r_anker", "date": DATE,
                                                          "party_size": 2}), 200).json()
    assert day["timezone"] == before["timezone"]
    pair = {"table_ids": ["t_1", "t_2"], "capacity": created["capacities"]["t_1"] + created["capacities"]["t_2"]}
    assert pair in day["slots"][0]["available_options"]
    assert assert_status(anon.get("/restaurants/r_anker"), 200).json() == before


# ---- reading (R327, R328, P8) --------------------------------------------------------------------

def test_the_list_is_public_in_publication_order_without_policy_0(world, anon):
    """R327/P8: anyone may list; the list holds the published policies in publication order
    (not effective order), each the 201 body, and never policy 0; unknown restaurant 404."""
    ada, _ = world
    later = assert_status(publish(ada, fx.policy(shifted(20))), 201).json()
    earlier = assert_status(publish(ada, fx.policy(shifted(-5), slot_minutes=15)), 201).json()
    assert assert_status(anon.get("/restaurants/r_anker/policies"), 200).json() == {"policies": [later, earlier]}
    assert_error(anon.get("/restaurants/r_nope/policies"), 404, "not_found")


def test_the_restaurant_detail_keeps_the_fixture_configuration(world, anon):
    """R328: publishing changes nothing in the restaurant detail."""
    ada, _ = world
    before = assert_status(anon.get("/restaurants/r_anker"), 200).json()
    assert_status(publish(ada, fx.policy(DATE, slot_minutes=15, reservation_duration_minutes=45,
                                         capacities={"t_1": 9, "t_2": 9, "t_3": 9})), 201)
    assert assert_status(anon.get("/restaurants/r_anker"), 200).json() == before


@pytest.mark.parametrize("managers,status", [(["u_nobody"], 422), (["u_ada", "u_ada"], 422),
                                             ("u_ada", 400), ([7], 400)],
                         ids=["unknown_user", "duplicate", "not_a_list", "not_strings"])
def test_managers_are_checked_at_reset(reset, managers, status):
    """R319/P6: `manager_user_ids` lists existing users once each; a wrong JSON type is 400,
    any other problem 422."""
    code = "validation_failed" if status == 422 else "malformed_request"
    assert_error(reset(fx.fixture(restaurants=[{**fx.restaurant(), "manager_user_ids": managers}]), raw=True),
                 status, code)


def test_without_managers_nobody_publishes(reset, api):
    """R319: `manager_user_ids` defaults to none."""
    reset(fx.fixture())
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    assert_error(publish(ada, fx.policy(DATE)), 403, "forbidden")


# ---- selection (R323, R324, R305, R328) ------------------------------------------------------------

def terms_of(response) -> dict:
    return assert_status(response, 201).json()["accepted_terms"]


def test_a_booking_takes_the_policy_in_force_on_its_date(world):
    """R323/R324: for a booking's local start date, the greatest effective date not later
    than it, ties to the greatest version; past effective dates count; publication order is
    not effective order; the booking's end follows its policy's duration."""
    ada, _ = world
    for effective, duration in ((shifted(14), 60), (shifted(-30), 120), (DATE, 45), (DATE, 75)):
        assert_status(publish(ada, fx.policy(effective, reservation_duration_minutes=duration)), 201)
    cases = {DATE: (4, 75), shifted(7): (4, 75), shifted(14): (1, 60), shifted(-1): (2, 120)}
    for table, (date, (version, duration)) in zip(("t_1", "t_2", "t_3", "t_1"), cases.items()):
        booking = assert_status(book(ada, table, date), 201).json()
        assert (booking["accepted_terms"]["policy_version"],
                booking["accepted_terms"]["reservation_duration_minutes"]) == (version, duration), date
        ends = dt.datetime.fromisoformat(booking["ends_at"]) - dt.datetime.fromisoformat(booking["starts_at"])
        assert ends == dt.timedelta(minutes=duration), date


def test_a_date_before_every_published_policy_keeps_policy_0(world):
    """R323: policy 0, the fixture's rules, applies before any published policy."""
    ada, _ = world
    assert_status(publish(ada, fx.policy(shifted(14), reservation_duration_minutes=60)), 201)
    assert terms_of(book(ada, "t_2", DATE)) == {
        "policy_version": 0, "slot_minutes": 30, "reservation_duration_minutes": 90,
        "cancellation_cutoff_minutes": 120, "opening_hours": fx.all_week(),
        "capacities": {"t_1": 2, "t_2": 4, "t_3": 6}}


def test_availability_and_booking_follow_the_policy_in_force(world, anon):
    """R305/R328: on a date under a published policy, the slot grid, hours, duration and
    capacities are that policy's, for availability and for booking; the day before keeps
    policy 0."""
    ada, _ = world
    assert_status(publish(ada, fx.policy(DATE, slot_minutes=45, reservation_duration_minutes=60,
                                         opening_hours=fx.all_week("12:00", "16:00"),
                                         capacities={"t_1": 1, "t_2": 3, "t_3": 8})), 201)

    def slots(date):
        return assert_status(anon.get("/availability", params={
            "restaurant_id": "r_anker", "date": date, "party_size": 3}), 200).json()["slots"]

    under = slots(DATE)
    assert [s["starts_at_local"][-5:] for s in under] == ["12:00", "12:45", "13:30", "14:15", "15:00"]
    assert all(s["available_table_ids"] == ["t_2", "t_3"] for s in under)
    assert under[0]["available_options"] == [{"table_ids": ["t_2"], "capacity": 3}, {"table_ids": ["t_3"], "capacity": 8},
                                             {"table_ids": ["t_1", "t_2"], "capacity": 4}]
    before = slots(shifted(-1))
    assert [s["starts_at_local"][-5:] for s in before] == fx.expected_slots()
    assert before[0]["available_table_ids"] == ["t_2", "t_3"]
    assert_status(book(ada, "t_2", DATE, "12:45", 3), 201)
    assert_error(book(ada, "t_3", DATE, "13:00", 3), 422, "not_on_slot_grid")
    assert_error(book(ada, "t_3", DATE, "19:00", 3), 422, "outside_opening_hours")
    assert_error(book(ada, "t_2", DATE, "14:15", 4), 422, "party_exceeds_capacity")
