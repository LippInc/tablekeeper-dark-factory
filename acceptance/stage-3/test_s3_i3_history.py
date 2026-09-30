"""S3-I3 acceptance checks (verifier seat): reservation history, from the stage-3
specification ("Reservation history", "Policies and accepted terms", "Combined-table
history", "Collective moves under policies and agreements") with the plan's P3, P4 and P10.

R.. and P.. name the room plan's requirement lines and decisions.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

import fixtures as fx
from harness.http import assert_error, assert_status, new_key

pytestmark = pytest.mark.stage(3)

DATE = fx.booking_date()
ZONE = ZoneInfo("Europe/Berlin")
ENTRY_KEYS = {"seq", "at", "event", "changes", "revision", "accepted_terms"}
POLICY_0 = {"policy_version": 0, "slot_minutes": 30, "reservation_duration_minutes": 90,
            "cancellation_cutoff_minutes": 120, "opening_hours": fx.all_week(),
            "capacities": {"t_1": 2, "t_2": 4, "t_3": 6}}


def world_fixture(reservations=()) -> dict:
    return fx.fixture(restaurants=[{**fx.managed_restaurant(), "combinable": [["t_1", "t_2"]]}],
                      reservations=list(reservations))


@pytest.fixture
def world(reset, api):
    reset(world_fixture())
    return (api().authenticate(fx.ADA["email"], fx.ADA["password"]),
            api().authenticate(fx.BOB["email"], fx.BOB["password"]))


def book(client, hhmm="19:00", party=2, key=None, **tables):
    tables = tables or {"table_id": "t_2"}
    return client.post("/reservations", idempotency_key=key or new_key(), json={
        "restaurant_id": "r_anker", **tables, "starts_at_local": fx.local(DATE, hhmm), "party_size": party})


def move(client, *items, key=None):
    return client.post("/reservation-moves", idempotency_key=key or new_key(), json={"moves": list(items)})


def history(client, reference) -> dict:
    return assert_status(client.get(f"/reservations/{reference}/history"), 200).json()


def entries(client, reference) -> list:
    return history(client, reference)["entries"]


def changes(client, reference) -> list:
    return [(e["event"], e["changes"]) for e in entries(client, reference)]


def publish(client, **overrides):
    assert_status(client.post("/restaurants/r_anker/policies", idempotency_key=new_key(),
                              json=fx.policy(DATE, **overrides)), 201)


def local(hhmm: str) -> str:
    return fx.local(DATE, hhmm)


# ---- created (R312, R314, R363, P3) -------------------------------------------------------------

def test_created_names_all_three_fields_from_null(world):
    """R311/R312/R314/P3: a new booking's history is one `created` entry: seq 1, `at` its
    creation in the restaurant's zone with its offset, all three fields from null in order,
    revision 1 and the complete accepted terms."""
    ada, _ = world
    booking = assert_status(book(ada, party=4), 201).json()
    record = history(ada, booking["reference"])
    assert set(record) == {"reference", "entries"} and record["reference"] == booking["reference"]
    [entry] = record["entries"]
    assert set(entry) == ENTRY_KEYS
    assert (entry["seq"], entry["event"], entry["revision"], entry["accepted_terms"]) == (1, "created", 1, POLICY_0)
    assert entry["changes"] == [{"field": "table_id", "from": None, "to": "t_2"},
                                {"field": "starts_at_local", "from": None, "to": local("19:00")},
                                {"field": "party_size", "from": None, "to": 4}]
    at = dt.datetime.fromisoformat(entry["at"])
    created = dt.datetime.fromisoformat(booking["created_at"].replace("Z", "+00:00"))
    assert at.utcoffset() == ZONE.utcoffset(at.replace(tzinfo=None)), entry["at"]
    assert abs(at - created) < dt.timedelta(seconds=2), (entry["at"], booking["created_at"])


def test_a_pair_is_created_as_table_ids_in_declared_order(world):
    """R363: a pair's creation names `table_ids` from null to the pair in declared order,
    even when named in reverse."""
    ada, _ = world
    booking = assert_status(book(ada, party=5, table_ids=["t_2", "t_1"]), 201).json()
    assert changes(ada, booking["reference"]) == [("created", [
        {"field": "table_ids", "from": None, "to": ["t_1", "t_2"]},
        {"field": "starts_at_local", "from": None, "to": local("19:00")},
        {"field": "party_size", "from": None, "to": 5}])]


# ---- changed (R315, R363) ------------------------------------------------------------------------

def test_changed_names_only_the_fields_that_changed_in_order(world):
    """R313/R315: each real PATCH adds one `changed` entry naming only the fields whose value
    changed, in the order table_id, starts_at_local, party_size (a field sent with its current
    value is not named); seq and revision count 1, 2, 3, 4."""
    ada, _ = world
    ref = assert_status(book(ada), 201).json()["reference"]
    assert_status(ada.patch(f"/reservations/{ref}", json={"party_size": 3}), 200)
    assert_status(ada.patch(f"/reservations/{ref}", json={"starts_at_local": local("20:00"), "table_id": "t_2",
                                                          "party_size": 3}), 200)
    assert_status(ada.patch(f"/reservations/{ref}", json={"party_size": 4, "table_id": "t_3",
                                                          "starts_at_local": local("18:00")}), 200)
    found = entries(ada, ref)
    assert [(e["seq"], e["revision"], e["event"]) for e in found] == [
        (1, 1, "created"), (2, 2, "changed"), (3, 3, "changed"), (4, 4, "changed")]
    assert [e["changes"] for e in found[1:]] == [
        [{"field": "party_size", "from": 2, "to": 3}],
        [{"field": "starts_at_local", "from": local("19:00"), "to": local("20:00")}],
        [{"field": "table_id", "from": "t_2", "to": "t_3"},
         {"field": "starts_at_local", "from": local("20:00"), "to": local("18:00")},
         {"field": "party_size", "from": 3, "to": 4}]]


def test_a_change_involving_a_pair_names_complete_table_ids(world):
    """R363: single to pair, pair to single: `table_ids` with the complete before and after
    lists in declared order; single to single stays `table_id`."""
    ada, _ = world
    ref = assert_status(book(ada, table_id="t_1"), 201).json()["reference"]
    for change in ({"table_ids": ["t_2", "t_1"]}, {"table_id": "t_3"}, {"table_id": "t_2"}):
        assert_status(ada.patch(f"/reservations/{ref}", json=change), 200)
    assert [e["changes"] for e in entries(ada, ref)[1:]] == [
        [{"field": "table_ids", "from": ["t_1"], "to": ["t_1", "t_2"]}],
        [{"field": "table_ids", "from": ["t_1", "t_2"], "to": ["t_3"]}],
        [{"field": "table_id", "from": "t_3", "to": "t_2"}]]


# ---- nothing recorded (R315, R336, R364, R367, P10) -------------------------------------------

def test_a_no_op_records_nothing(world):
    """R315/R336/R364/P10: after a same-date policy, a PATCH with nothing, with the current
    values, with only `expected_revision`, with only an unknown field, naming a pair in
    reverse, and a no-op move item all succeed and record nothing."""
    ada, _ = world
    single = assert_status(book(ada), 201).json()
    pair = assert_status(book(ada, hhmm="21:00", party=5, table_ids=["t_1", "t_2"]), 201).json()
    publish(ada, reservation_duration_minutes=30)
    before = (history(ada, single["reference"]), history(ada, pair["reference"]))
    for change in ({}, {"table_id": "t_2", "starts_at_local": local("19:00"), "party_size": 2},
                   {"expected_revision": 1}, {"note": "window seat"}):
        assert_status(ada.patch(f"/reservations/{single['reference']}", json=change), 200)
    assert_status(ada.patch(f"/reservations/{pair['reference']}", json={"table_ids": ["t_2", "t_1"]}), 200)
    assert_status(move(ada, {"reference": single["reference"], "party_size": 2},
                       {"reference": pair["reference"], "table_ids": ["t_2", "t_1"]}), 201)
    assert (history(ada, single["reference"]), history(ada, pair["reference"])) == before


def test_a_refused_amendment_records_nothing(world):
    """R337/R315: refused PATCHes (a field error, a taken table, a stale revision) record
    nothing."""
    ada, bob = world
    ref = assert_status(book(ada), 201).json()["reference"]
    assert_status(book(bob, table_id="t_3"), 201)
    before = history(ada, ref)
    assert_error(ada.patch(f"/reservations/{ref}", json={"party_size": 0}), 422, "validation_failed")
    assert_error(ada.patch(f"/reservations/{ref}", json={"table_id": "t_3"}), 409, "table_unavailable")
    assert_error(ada.patch(f"/reservations/{ref}", json={"party_size": 3, "expected_revision": 2}), 409, "stale_revision")
    assert history(ada, ref) == before


# ---- cancelled (R316, R311) --------------------------------------------------------------------------

def test_cancelled_is_the_last_entry_with_empty_changes(world):
    """R311/R316/R337: cancel appends `cancelled` with empty changes at the next revision;
    a repeated cancel and a later refused PATCH add nothing; the history stays readable."""
    ada, _ = world
    ref = assert_status(book(ada), 201).json()["reference"]
    assert_status(ada.patch(f"/reservations/{ref}", json={"party_size": 3}), 200)
    assert_status(ada.post(f"/reservations/{ref}/cancel"), 200)
    after_cancel = history(ada, ref)
    assert [(e["seq"], e["event"], e["revision"]) for e in after_cancel["entries"]] == [
        (1, "created", 1), (2, "changed", 2), (3, "cancelled", 3)]
    assert after_cancel["entries"][-1]["changes"] == []
    assert_status(ada.post(f"/reservations/{ref}/cancel"), 200)
    assert_error(ada.patch(f"/reservations/{ref}", json={"party_size": 4}), 409, "reservation_cancelled")
    assert history(ada, ref) == after_cancel


# ---- order (R313) ----------------------------------------------------------------------------------------

def test_seq_orders_writes_that_land_in_one_second(world):
    """R313: six writes in quick succession (several in one second) are numbered 1..6 and
    returned in seq order, which is also `at` order; each entry's revision is its seq."""
    ada, _ = world
    ref = assert_status(book(ada), 201).json()["reference"]
    for party in (3, 2, 3, 2):
        assert_status(ada.patch(f"/reservations/{ref}", json={"party_size": party}), 200)
    assert_status(ada.post(f"/reservations/{ref}/cancel"), 200)
    found = entries(ada, ref)
    assert [(e["seq"], e["event"]) for e in found] == [(1, "created")] + [(n, "changed") for n in range(2, 6)] + [
        (6, "cancelled")]
    stamps = [dt.datetime.fromisoformat(e["at"]) for e in found]
    assert stamps == sorted(stamps)
    assert [e["revision"] for e in found] == [1, 2, 3, 4, 5, 6]


# ---- terms per entry (R340, R333) ----------------------------------------------------------------------

def test_each_entry_keeps_the_revision_and_terms_of_its_moment(world):
    """R340/R333: a publication changes no history; a real amendment's entry carries the
    terms it adopted; old entries never acquire newer terms."""
    ada, _ = world
    ref = assert_status(book(ada), 201).json()["reference"]
    first = history(ada, ref)
    publish(ada, reservation_duration_minutes=45)
    assert history(ada, ref) == first
    assert_status(ada.patch(f"/reservations/{ref}", json={"party_size": 3}), 200)
    publish(ada, reservation_duration_minutes=30, cancellation_cutoff_minutes=60)
    assert_status(ada.patch(f"/reservations/{ref}", json={"starts_at_local": local("20:00")}), 200)
    found = entries(ada, ref)
    assert found[0] == first["entries"][0]
    assert [(e["revision"], e["accepted_terms"]["policy_version"], e["accepted_terms"]["reservation_duration_minutes"],
             e["accepted_terms"]["cancellation_cutoff_minutes"]) for e in found] == [
        (1, 0, 90, 120), (2, 1, 45, 120), (3, 2, 30, 60)]
    assert all(set(e["accepted_terms"]) == set(POLICY_0) for e in found)


# ---- moves (R367, R368) -------------------------------------------------------------------------------

def test_moves_record_one_changed_entry_per_changed_booking(world):
    """R367/R368: a swap adds one `changed` entry to each swapped booking and none to a no-op
    item; a failed batch adds nothing to any booking."""
    ada, bob = world
    a = assert_status(book(ada, table_id="t_2"), 201).json()["reference"]
    b = assert_status(book(ada, table_id="t_3"), 201).json()["reference"]
    c = assert_status(book(ada, hhmm="18:00", table_id="t_1"), 201).json()["reference"]
    assert_status(move(ada, {"reference": a, "table_id": "t_3"}, {"reference": b, "table_id": "t_2"},
                       {"reference": c, "party_size": 2}), 201)
    assert changes(ada, a)[1:] == [("changed", [{"field": "table_id", "from": "t_2", "to": "t_3"}])]
    assert changes(ada, b)[1:] == [("changed", [{"field": "table_id", "from": "t_3", "to": "t_2"}])]
    assert len(entries(ada, c)) == 1
    assert_status(book(bob, hhmm="21:30", table_id="t_2"), 201)
    before = [history(ada, ref) for ref in (a, b, c)]
    assert_error(move(ada, {"reference": a, "party_size": 3}, {"reference": b, "starts_at_local": local("20:30")}),
                 409, "table_unavailable")
    assert [history(ada, ref) for ref in (a, b, c)] == before


# ---- replays (R317) ------------------------------------------------------------------------------------

def test_replays_record_nothing(world):
    """R317/§7: replaying a create or a move with its key and body answers the original and
    records nothing."""
    ada, _ = world
    key = new_key()
    created = assert_status(book(ada, key=key), 201).json()
    ref = created["reference"]
    assert assert_status(book(ada, key=key), 200).json() == created
    assert len(entries(ada, ref)) == 1
    move_key = new_key()
    moved = assert_status(move(ada, {"reference": ref, "party_size": 3}, key=move_key), 201).json()
    before = history(ada, ref)
    assert assert_status(move(ada, {"reference": ref, "party_size": 3}, key=move_key), 200).json() == moved
    assert history(ada, ref) == before and len(before["entries"]) == 2


# ---- seeded (P4) ---------------------------------------------------------------------------------------

def test_seeded_bookings_have_one_created_entry(reset, api):
    """P4/R331: seeded bookings, confirmed or cancelled, single or pair, have one `created`
    entry at their `created_at`, revision 1 under policy 0."""
    def seed(reference, status="confirmed", **tables):
        return {"id": f"res_{reference}", "reference": reference, "user_id": "u_ada", "restaurant_id": "r_anker",
                **(tables or {"table_id": "t_3"}), "starts_at_local": local("19:00"), "party_size": 2, "status": status}

    reset(world_fixture([seed("HIS001"), seed("HIS002", status="cancelled", table_id="t_2"),
                         seed("HIS003", table_ids=["t_1", "t_2"], ), ]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    for reference, first in (("HIS001", {"field": "table_id", "from": None, "to": "t_3"}),
                             ("HIS002", {"field": "table_id", "from": None, "to": "t_2"}),
                             ("HIS003", {"field": "table_ids", "from": None, "to": ["t_1", "t_2"]})):
        [entry] = entries(ada, reference)
        booking = assert_status(ada.get(f"/reservations/{reference}"), 200).json()
        assert (entry["seq"], entry["event"], entry["revision"], entry["accepted_terms"]) == (1, "created", 1, POLICY_0)
        assert entry["changes"] == [first, {"field": "starts_at_local", "from": None, "to": local("19:00")},
                                    {"field": "party_size", "from": None, "to": 2}], reference
        assert dt.datetime.fromisoformat(entry["at"]) == dt.datetime.fromisoformat(
            booking["created_at"].replace("Z", "+00:00")), reference


# ---- owner only (R311, R320, R342) -----------------------------------------------------------------------

def test_only_the_owner_reads_the_history(world, anon, api):
    """R311/R320/R342: another diner, a manager of the restaurant, no token, a malformed or
    unknown token and an unknown reference all get 404 not_found; the owner reads it."""
    ada, bob = world
    ref = assert_status(book(bob), 201).json()["reference"]
    assert entries(bob, ref)[0]["event"] == "created"
    for client in (ada, anon, api("not-a-token")):
        assert_error(client.get(f"/reservations/{ref}/history"), 404, "not_found")
    for header in ("Basic abc", "Bearer", "bearer"):
        assert_error(anon.get(f"/reservations/{ref}/history", headers={"Authorization": header}), 404, "not_found")
    assert_error(bob.get("/reservations/NOPE99/history"), 404, "not_found")
