"""S3-I1 acceptance checks (verifier seat): accepted terms and revisions, from the stage-3
specification ("Policies and accepted terms", "Combined-table history" capacity, "Collective
moves under policies and agreements") with the plan's H1, H3, P10 and the critic's B1
(the accepted cutoff, not the current one) and B2 (each booking's own duration).

R.., H.. and P.. name the room plan's requirement lines and decisions.
"""
from __future__ import annotations

import datetime as dt

import pytest

import fixtures as fx
from harness.http import assert_error, assert_status, new_key

pytestmark = pytest.mark.stage(3)

DATE = fx.booking_date()                     # 7 days ahead: outside every cutoff up to 7 days
NEAR = fx.booking_date(lead=3)               # 3 days ahead: inside a 7-day (10080-minute) cutoff
TERMS = {"policy_version", "slot_minutes", "reservation_duration_minutes", "cancellation_cutoff_minutes",
         "opening_hours", "capacities"}
POLICY_0 = {"policy_version": 0, "slot_minutes": 30, "reservation_duration_minutes": 90,
            "cancellation_cutoff_minutes": 120, "opening_hours": fx.all_week(),
            "capacities": {"t_1": 2, "t_2": 4, "t_3": 6}}


def seed(reference, table, date, hhmm, user="u_ada", party=2) -> dict:
    return {"id": f"res_{reference}", "reference": reference, "user_id": user, "restaurant_id": "r_anker",
            "table_id": table, "starts_at_local": fx.local(date, hhmm), "party_size": party}


def world_fixture(reservations=()) -> dict:
    return fx.fixture(restaurants=[{**fx.managed_restaurant(), "combinable": [["t_1", "t_2"]]}],
                      reservations=list(reservations))


@pytest.fixture
def world(reset, api):
    reset(world_fixture())
    return (api().authenticate(fx.ADA["email"], fx.ADA["password"]),
            api().authenticate(fx.BOB["email"], fx.BOB["password"]))


def publish(client, body):
    return assert_status(client.post("/restaurants/r_anker/policies", json=body, idempotency_key=new_key()), 201).json()


def book(client, table, date=DATE, hhmm="19:00", party=2, key=None, **extra):
    return client.post("/reservations", idempotency_key=key or new_key(), json={
        "restaurant_id": "r_anker", "table_id": table, "starts_at_local": fx.local(date, hhmm), "party_size": party, **extra})


def move(client, *items):
    return client.post("/reservation-moves", idempotency_key=new_key(), json={"moves": list(items)})


def read(client, reference) -> dict:
    return assert_status(client.get(f"/reservations/{reference}"), 200).json()


def minutes(booking) -> int:
    return int((dt.datetime.fromisoformat(booking["ends_at"])
                - dt.datetime.fromisoformat(booking["starts_at"])).total_seconds() // 60)


# ---- revision and accepted_terms on every response (R330, R331, R332, R337) ---------------------

def test_every_reservation_response_carries_revision_and_accepted_terms(world):
    """R330/R337: create, read and list answer revision 1 and the whole policy 0 without
    `effective_from`; each real PATCH, move and cancel adds one; a repeated cancel adds none."""
    ada, _ = world
    created = assert_status(book(ada, "t_2"), 201).json()
    ref = created["reference"]
    assert created["revision"] == 1 and created["accepted_terms"] == POLICY_0
    assert set(created["accepted_terms"]) == TERMS
    assert read(ada, ref)["revision"] == 1
    listed = assert_status(ada.get("/reservations"), 200).json()["reservations"]
    assert [(b["revision"], b["accepted_terms"]) for b in listed] == [(1, POLICY_0)]
    assert assert_status(ada.patch(f"/reservations/{ref}", json={"party_size": 3}), 200).json()["revision"] == 2
    moved = assert_status(move(ada, {"reference": ref, "starts_at_local": fx.local(DATE, "20:00")}), 201).json()
    assert moved["reservations"][0]["revision"] == 3
    assert assert_status(ada.post(f"/reservations/{ref}/cancel"), 200).json()["revision"] == 4
    again = assert_status(ada.post(f"/reservations/{ref}/cancel"), 200).json()
    assert (again["revision"], again["status"]) == (4, "cancelled")
    assert all(set(b) >= {"revision", "accepted_terms"} for b in (created, moved["reservations"][0], again))


def test_cancel_answers_the_cancelled_booking_at_the_next_revision_and_frees_the_table(world, anon):
    """R107-R109/R334/R337 (replaces acceptance/stage-1 test_s1_i3_bookings.py::
    test_cancel_answers_the_cancelled_booking_and_frees_the_table): after a same-date policy,
    cancel answers 200 with the booking as cancelled at revision 2, its terms and end kept; the
    slot is offered again and bookable by someone else; cancelling twice answers the same state."""
    ada, bob = world
    created = assert_status(book(ada, "t_2", party=4), 201).json()
    ref = created["reference"]
    publish(ada, fx.policy(DATE, reservation_duration_minutes=30))
    cancelled = assert_status(ada.post(f"/reservations/{ref}/cancel"), 200).json()
    assert cancelled == {**created, "status": "cancelled", "revision": 2}
    slots = assert_status(anon.get("/availability", params={"restaurant_id": "r_anker", "date": DATE,
                                                            "party_size": 4}), 200).json()["slots"]
    assert "t_2" in next(s for s in slots if s["starts_at_local"].endswith("T19:00"))["available_table_ids"]
    assert assert_status(ada.post(f"/reservations/{ref}/cancel"), 200).json() == cancelled
    assert_status(book(bob, "t_2", party=4), 201)
    assert read(ada, ref) == cancelled


def test_seeded_bookings_are_revision_1_under_policy_0(reset, api):
    """R331: a seeded booking starts at revision 1 under policy 0."""
    reset(world_fixture([seed("SEED01", "t_3", DATE, "19:00")]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    booking = read(ada, "SEED01")
    assert (booking["revision"], booking["accepted_terms"]) == (1, POLICY_0)


def test_an_old_receipt_replays_its_original_revision_and_terms(world):
    """R332/§7: after a change and a new policy, the original key and body replay the original
    response, with revision 1 and policy 0."""
    ada, _ = world
    key = new_key()
    original = assert_status(book(ada, "t_2", key=key), 201).json()
    assert_status(ada.patch(f"/reservations/{original['reference']}", json={"party_size": 3}), 200)
    publish(ada, fx.policy(DATE, reservation_duration_minutes=45))
    assert assert_status(book(ada, "t_2", key=key), 200).json() == original


# ---- publication changes no accepted booking (R324, R333, H1) ---------------------------------------

def test_a_publication_leaves_every_accepted_booking_as_it_was(world, api):
    """R324/R333: after a same-date policy with another duration, cutoff and capacities, an
    existing booking's body, end and decision are unchanged, and it still holds its own 90
    minutes: a 30-minute create at 20:00 against it (19:00) is 409, at 20:30 201."""
    ada, bob = world
    booking = assert_status(book(ada, "t_2"), 201).json()
    decision = assert_status(ada.get(f"/reservations/{booking['reference']}/decision"), 200).json()
    publish(ada, fx.policy(DATE, reservation_duration_minutes=30, cancellation_cutoff_minutes=10080,
                           capacities={"t_1": 1, "t_2": 1, "t_3": 1}))
    assert read(ada, booking["reference"]) == booking
    assert assert_status(ada.get(f"/reservations/{booking['reference']}/decision"), 200).json() == decision
    assert_error(book(bob, "t_2", hhmm="20:00", party=1), 409, "table_unavailable")
    assert minutes(assert_status(book(bob, "t_2", hhmm="20:30", party=1), 201).json()) == 30


# ---- the accepted cutoff (R334, R335, R365, critic's B1) ---------------------------------------------

def attempt(client, operation, reference):
    if operation == "cancel":
        return client.post(f"/reservations/{reference}/cancel")
    if operation == "patch":
        return client.patch(f"/reservations/{reference}", json={"party_size": 3})
    return move(client, {"reference": reference, "party_size": 3})


@pytest.mark.parametrize("operation", ["cancel", "patch", "move"])
def test_a_booking_accepted_under_a_short_cutoff_keeps_it(world, operation):
    """R334/R335/R365 (B1): accepted under cutoff 120, a booking 3 days ahead may still be
    cancelled, amended and moved after a same-date policy with cutoff 10080."""
    ada, _ = world
    booking = assert_status(book(ada, "t_2", NEAR), 201).json()
    publish(ada, fx.policy(NEAR, cancellation_cutoff_minutes=10080))
    assert attempt(ada, operation, booking["reference"]).status_code in (200, 201)


@pytest.mark.parametrize("operation", ["cancel", "patch", "move"])
def test_a_booking_accepted_under_a_long_cutoff_stays_refused(world, operation):
    """R334/R335/R365 (B1): accepted under cutoff 10080, a booking 3 days ahead stays refused
    (409 cutoff_passed) after a same-date policy with cutoff 0, and is unchanged."""
    ada, _ = world
    publish(ada, fx.policy(NEAR, cancellation_cutoff_minutes=10080))
    booking = assert_status(book(ada, "t_2", NEAR), 201).json()
    publish(ada, fx.policy(NEAR, cancellation_cutoff_minutes=0))
    assert_error(attempt(ada, operation, booking["reference"]), 409, "cutoff_passed")
    assert read(ada, booking["reference"]) == booking


# ---- amendments (R335, R336, R337) ---------------------------------------------------------------

def test_a_real_amendment_adopts_the_policy_of_its_resulting_date(world):
    """R335: a real change is judged, in every resulting field, by the policy of the resulting
    start date, and takes its terms and end, one revision on."""
    ada, _ = world
    later = (dt.date.fromisoformat(DATE) + dt.timedelta(days=7)).isoformat()
    booking = assert_status(book(ada, "t_2"), 201).json()
    publish(ada, fx.policy(later, reservation_duration_minutes=60, capacities={"t_1": 2, "t_2": 3, "t_3": 6}))
    moved = assert_status(ada.patch(f"/reservations/{booking['reference']}",
                                    json={"starts_at_local": fx.local(later, "19:00")}), 200).json()
    assert (moved["revision"], moved["accepted_terms"]["policy_version"], minutes(moved)) == (2, 1, 60)
    assert_error(ada.patch(f"/reservations/{booking['reference']}", json={"party_size": 4}), 422, "party_exceeds_capacity")
    assert read(ada, booking["reference"]) == moved


def test_a_no_op_amendment_keeps_terms_end_and_revision(world):
    """R336: after a same-date policy, a PATCH with nothing or the same values is 200 with the
    booking as it was (revision, terms, end); on a cancelled booking it is still refused."""
    ada, _ = world
    booking = assert_status(book(ada, "t_2"), 201).json()
    publish(ada, fx.policy(DATE, reservation_duration_minutes=30))
    ref = booking["reference"]
    for change in ({}, {"party_size": 2, "table_id": "t_2", "starts_at_local": booking["starts_at_local"]},
                   {"table_ids": ["t_2"]}):
        assert assert_status(ada.patch(f"/reservations/{ref}", json=change), 200).json() == booking
    assert_status(ada.post(f"/reservations/{ref}/cancel"), 200)
    assert_error(ada.patch(f"/reservations/{ref}", json={}), 409, "reservation_cancelled")


def test_a_no_op_still_needs_an_editable_booking(reset, api):
    """R336/H3: a no-op PATCH (nothing, the same value, only `expected_revision`) or no-op move
    item on a booking inside its accepted cutoff is 409 cutoff_passed, as a real change is."""
    reset(world_fixture([seed("PAST02", "t_2", fx.booking_date(lead=-1), "19:00")]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    booking = read(ada, "PAST02")
    for change in ({}, {"party_size": 2}, {"expected_revision": 1}):
        assert_error(ada.patch("/reservations/PAST02", json=change), 409, "cutoff_passed")
    assert_error(move(ada, {"reference": "PAST02"}), 409, "cutoff_passed")
    assert read(ada, "PAST02") == booking


def test_a_reversed_pair_is_not_an_amendment(world):
    """R336 and "Combined-table history": after a same-date policy, a PATCH or move item naming
    the booked pair in reverse order is a no-op: body, revision and terms stay as they were."""
    ada, _ = world
    booked = assert_status(ada.post("/reservations", idempotency_key=new_key(), json={
        "restaurant_id": "r_anker", "table_ids": ["t_1", "t_2"], "starts_at_local": fx.local(DATE),
        "party_size": 3}), 201).json()
    publish(ada, fx.policy(DATE, reservation_duration_minutes=30))
    ref = booked["reference"]
    assert assert_status(ada.patch(f"/reservations/{ref}", json={"table_ids": ["t_2", "t_1"]}), 200).json() == booked
    assert assert_status(move(ada, {"reference": ref, "table_ids": ["t_2", "t_1"]}), 201).json()["reservations"] == [booked]
    assert read(ada, ref) == booked


def test_a_failed_amendment_changes_nothing(world):
    """R337: a refused PATCH leaves revision, terms and occupancy as they were."""
    ada, bob = world
    booking = assert_status(book(ada, "t_2"), 201).json()
    assert_status(book(bob, "t_3"), 201)
    publish(ada, fx.policy(DATE, reservation_duration_minutes=30))
    assert_error(ada.patch(f"/reservations/{booking['reference']}", json={"table_id": "t_3"}), 409, "table_unavailable")
    assert read(ada, booking["reference"]) == booking
    assert_error(book(bob, "t_2", hhmm="20:00", party=1), 409, "table_unavailable")


# ---- expected_revision (R338, R339, H3, P10) ------------------------------------------------------------

@pytest.mark.parametrize("value", [0, -1, 1.5, "1", True, None], ids=["zero", "negative", "float", "string", "true", "null"])
def test_an_invalid_expected_revision_is_422(world, value):
    """R338/H3: `expected_revision` other than a positive integer is 422 validation_failed."""
    ada, _ = world
    booking = assert_status(book(ada, "t_2"), 201).json()
    assert_error(ada.patch(f"/reservations/{booking['reference']}", json={"party_size": 3, "expected_revision": value}),
                 422, "validation_failed")
    assert read(ada, booking["reference"]) == booking


def test_a_stale_expected_revision_is_409_before_cutoff_and_fields(world, reset, api):
    """R338/H3: a positive `expected_revision` other than the current one is 409
    stale_revision, before a field error and before the cutoff; the right one lets a real
    change through; one that changes nothing else is a no-op (P10); unknown fields aside."""
    ada, _ = world
    booking = assert_status(book(ada, "t_2"), 201).json()
    ref = booking["reference"]
    assert_error(ada.patch(f"/reservations/{ref}", json={"party_size": 0, "expected_revision": 2}), 409, "stale_revision")
    assert assert_status(ada.patch(f"/reservations/{ref}", json={"expected_revision": 1}), 200).json() == booking
    changed = assert_status(ada.patch(f"/reservations/{ref}", json={"party_size": 3, "expected_revision": 1,
                                                                     "note": "window seat"}), 200).json()
    assert changed["revision"] == 2
    assert_error(ada.patch(f"/reservations/{ref}", json={"party_size": 4, "expected_revision": 1}), 409, "stale_revision")
    assert_error(ada.patch("/reservations/NOPE99", json={"expected_revision": 0}), 404, "not_found")
    reset(world_fixture([seed("PAST01", "t_2", fx.booking_date(lead=-1), "19:00")]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    assert_error(ada.patch("/reservations/PAST01", json={"party_size": 3}), 409, "cutoff_passed")
    assert_error(ada.patch("/reservations/PAST01", json={"party_size": 3, "expected_revision": 5}), 409, "stale_revision")


# ---- moves under policies (R365, R366, R367) ------------------------------------------------------------

def test_moves_apply_patch_semantics_per_item(world):
    """R365-R367: per-move `expected_revision` (stale 409, invalid 422, both changing nothing);
    a real item adopts its resulting date's policy while a no-op item keeps revision and
    terms; a failed batch changes no revision."""
    ada, bob = world
    first = assert_status(book(ada, "t_2"), 201).json()
    second = assert_status(book(ada, "t_3"), 201).json()
    publish(ada, fx.policy(DATE, reservation_duration_minutes=45))
    item = {"reference": first["reference"], "starts_at_local": fx.local(DATE, "20:30")}
    assert_error(move(ada, {**item, "expected_revision": 2}), 409, "stale_revision")
    assert_error(move(ada, {**item, "expected_revision": True}), 422, "validation_failed")
    assert (read(ada, first["reference"]), read(ada, second["reference"])) == (first, second)
    moved = assert_status(move(ada, {**item, "expected_revision": 1},
                               {"reference": second["reference"], "party_size": 2}), 201).json()["reservations"]
    assert (moved[0]["revision"], moved[0]["accepted_terms"]["policy_version"], minutes(moved[0])) == (2, 1, 45)
    assert moved[1] == second
    assert_status(book(bob, "t_3", hhmm="21:00"), 201)
    assert_error(move(ada, {"reference": first["reference"], "party_size": 3},
                      {"reference": second["reference"], "starts_at_local": fx.local(DATE, "20:30")}),
                 409, "table_unavailable")
    assert (read(ada, first["reference"]), read(ada, second["reference"])) == (moved[0], second)


# ---- combinations (R362) -----------------------------------------------------------------------------

def test_a_pair_seats_the_selected_policys_summed_capacity(world, anon):
    """R362: a pair seats the sum of the selected policy's capacities."""
    ada, _ = world
    publish(ada, fx.policy(DATE, capacities={"t_1": 1, "t_2": 1, "t_3": 6}))
    pair = {"table_ids": ["t_1", "t_2"]}
    assert_error(ada.post("/reservations", idempotency_key=new_key(), json={
        "restaurant_id": "r_anker", **pair, "starts_at_local": fx.local(DATE), "party_size": 3}), 422, "party_exceeds_capacity")
    options = assert_status(anon.get("/availability", params={"restaurant_id": "r_anker", "date": DATE,
                                                              "party_size": 2}), 200).json()["slots"][0]["available_options"]
    assert {"table_ids": ["t_1", "t_2"], "capacity": 2} in options
    booked = assert_status(ada.post("/reservations", idempotency_key=new_key(), json={
        "restaurant_id": "r_anker", **pair, "starts_at_local": fx.local(DATE), "party_size": 2}), 201).json()
    assert booked["accepted_terms"]["capacities"] == {"t_1": 1, "t_2": 1, "t_3": 6}
    earlier = (dt.date.fromisoformat(DATE) - dt.timedelta(days=1)).isoformat()
    assert_status(ada.post("/reservations", idempotency_key=new_key(), json={
        "restaurant_id": "r_anker", **pair, "starts_at_local": fx.local(earlier), "party_size": 6}), 201)


# ---- the decision (R341, R342) -----------------------------------------------------------------------

def test_the_decision_is_the_owners_current_revision_and_terms(world, anon, api):
    """R341/R342: the owner reads the current revision and terms, after cancellation too;
    another user, no token, a bad token and an unknown reference get the same 404."""
    ada, bob = world
    booking = assert_status(book(ada, "t_2"), 201).json()
    ref = booking["reference"]
    decision = assert_status(ada.get(f"/reservations/{ref}/decision"), 200).json()
    assert decision == {"reference": ref, "revision": 1, "accepted_terms": booking["accepted_terms"]}
    assert_status(ada.post(f"/reservations/{ref}/cancel"), 200)
    assert assert_status(ada.get(f"/reservations/{ref}/decision"), 200).json()["revision"] == 2
    for client in (bob, anon, api("not-a-token")):
        assert_error(client.get(f"/reservations/{ref}/decision"), 404, "not_found")
    assert_error(ada.get("/reservations/NOPE99/decision"), 404, "not_found")


# ---- occupancy with each booking's own duration after every writer (B2) ------------------------------

SLOTS = [f"{h:02d}:{m:02d}" for h in range(18, 23) for m in (0, 30)]


def free_at(booked: dict[str, list[tuple[int, int]]], table: str, hhmm: str, duration: int) -> bool:
    start = int(hhmm[:2]) * 60 + int(hhmm[3:])
    return all(start + duration <= b or start >= b + length for b, length in booked[table])


def test_each_booking_holds_its_own_duration_after_every_writer(reset, api, anon):
    """B2/R335/R365: with policy 0 (90 minutes) bookings in place, a same-date policy of 30
    minutes, then a create, a real PATCH and a move placed under it: after each writer,
    availability equals the reference built from each booking's own duration; a create just
    inside a booking's end is 409 and just after it 201."""
    reset(world_fixture([seed("OWN001", "t_1", DATE, "19:00"), seed("OWN002", "t_2", DATE, "18:00"),
                         seed("OWN003", "t_3", DATE, "18:00")]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    bob = api().authenticate(fx.BOB["email"], fx.BOB["password"])
    booked = {"t_1": [(19 * 60, 90)], "t_2": [(18 * 60, 90)], "t_3": [(18 * 60, 90)]}

    def matches(step):
        slots = assert_status(anon.get("/availability", params={"restaurant_id": "r_anker", "date": DATE,
                                                                "party_size": 1}), 200).json()["slots"]
        assert [s["starts_at_local"][-5:] for s in slots] == [s for s in SLOTS if s <= "22:30"], step
        expected = [[t for t in ("t_1", "t_2", "t_3") if free_at(booked, t, s["starts_at_local"][-5:], 30)] for s in slots]
        assert [s["available_table_ids"] for s in slots] == expected, step

    publish(ada, fx.policy(DATE, reservation_duration_minutes=30))
    matches("a 30-minute policy")
    assert_status(book(ada, "t_1", hhmm="21:00", party=1), 201)
    booked["t_1"].append((21 * 60, 30))
    matches("a create")
    assert_status(ada.patch("/reservations/OWN002", json={"starts_at_local": fx.local(DATE, "19:30")}), 200)
    booked["t_2"] = [(19 * 60 + 30, 30)]
    matches("a real PATCH")
    assert_status(move(ada, {"reference": "OWN003", "starts_at_local": fx.local(DATE, "20:00")}), 201)
    booked["t_3"] = [(20 * 60, 30)]
    matches("a move")
    for table, inside, after in (("t_1", "20:00", "20:30"), ("t_2", "19:30", "20:00"), ("t_3", "20:00", "20:30"),
                                 ("t_1", "21:00", "21:30")):
        assert_error(book(bob, table, hhmm=inside, party=1), 409, "table_unavailable")
        assert_status(book(bob, table, hhmm=after, party=1), 201)
        booked[table].append((int(after[:2]) * 60 + int(after[3:]), 30))
    matches("the creates beside each end")
