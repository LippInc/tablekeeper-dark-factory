"""S4-I3 acceptance checks (verifier seat): applying a plan and the closure it records, from
the stage-4 specification's "Seating changes after a table closure" (R403, R408, R410, R412,
R414-R416, R422, R423, R426-R438, R440, R459, R460) with the plan's Q4, Q6, Q13-Q17, Q24,
Q26, Q27 and the stage-1/3 keyed-write, history and series rules (D3, D11, H2, H4).

The world helpers come from test_s4_i2_preview.py. Races are in test_s4_i3_races.py. Uses a
second stage-4 service (TABLEKEEPER_SECOND_URL) and the stage-3 service (TABLEKEEPER_STAGE3_URL)
and resets them: run it alone against other files that reset them.
"""
from __future__ import annotations

import copy
import importlib.util
import pathlib

import pytest

import fixtures as fx
from harness.http import RESET_TIMEOUT, Api, assert_error, assert_status, new_key

pytestmark = pytest.mark.stage(4)

_spec = importlib.util.spec_from_file_location("s4i2_preview", pathlib.Path(__file__).with_name("test_s4_i2_preview.py"))
w = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(w)
make = w.make  # the reset-world fixture
DATE, closure, seed, exported, url, planned, create, publish = (
    w.DATE, w.closure, w.seed, w.exported, w.url, w.planned, w.create, w.publish)

# r_anker: t_1 2, t_2 4, t_3 6, t_4 4 seats; pairs t_1+t_2 and t_3+t_4. Closing t_2 over
# [19:00, 21:00) moves MOVE01 (t_2, 19:00, party 2) to t_1 and keeps KEEP01 (t_3, 19:30);
# FIXD01 (t_4, 12:00) is not considered.
CAPS, PAIRS = (2, 4, 6, 4), [("t_1", "t_2"), ("t_3", "t_4")]
SEEDS = [seed("MOVE01", ["t_2"], "19:00", party=2), seed("KEEP01", ["t_3"], "19:30", party=4),
         seed("FIXD01", ["t_4"], "12:00", party=2)]
CLOSED = closure(table="t_2", start="19:00", end="21:00")


def weeks(n: int) -> str:
    return (w.dt.date.fromisoformat(DATE) + w.dt.timedelta(weeks=n)).isoformat()


def apply(client, plan_id, key=None, body=None, rid="r_anker"):
    return client.post(f"/restaurants/{rid}/replans/{plan_id}/apply", json={} if body is None else body,
                       idempotency_key=key or new_key())


def applied(client, plan_id, key=None) -> dict:
    return assert_status(apply(client, plan_id, key), 201).json()


def world(make, caps=CAPS, pairs=PAIRS, seeds=SEEDS, **kw):
    return make(caps=caps, pairs=pairs, seeds=seeds, **kw)


def read(world, reference) -> dict:
    return assert_status(world.bob.get(f"/reservations/{reference}"), 200).json()


def history(world, reference) -> list:
    return assert_status(world.bob.get(f"/reservations/{reference}/history"), 200).json()["entries"]


def revision(world, rid="r_anker") -> int:
    return next(r["revision"] for r in exported(world.base)["state"]["restaurants"] if r["id"] == rid)


def closures(world, rid="r_anker") -> list:
    return next(r["closures"] for r in exported(world.base)["state"]["restaurants"] if r["id"] == rid)


def slot(world, hhmm, party=2, date=DATE, explain=False) -> dict:
    params = {"restaurant_id": "r_anker", "date": date, "party_size": party, **({"explain": "true"} if explain else {})}
    body = assert_status(world.bob.get("/availability", params=params), 200).json()
    return next(s for s in body["slots"] if s["starts_at_local"].endswith(hhmm))


def closed_world(make):
    """The standard world with CLOSED applied."""
    world_ = world(make)
    applied(world_.ada, planned(world_.ada, CLOSED)["plan_id"])
    return world_


# ---- the keyed write and its order (R426, Q4, D3, D11) -------------------------------------------------------

def test_the_keyed_write_basics_come_first(make):
    """R426/D3: no token 401; a body that is not a JSON object 400; a missing key 400; a key
    over 255 characters 422; the same key and body replays 200 with the original body; the
    same key with another body is 409 idempotency_key_reuse; unknown body fields are ignored."""
    world_ = world(make)
    plan_id = planned(world_.ada, CLOSED)["plan_id"]
    path = f"/restaurants/r_anker/replans/{plan_id}/apply"
    assert_error(Api(world_.base).post(path, json={}, idempotency_key=new_key()), 401, "unauthenticated")
    for raw in ("[]", "{", "null", '"x"'):
        assert_error(world_.ada.post(path, content=raw, idempotency_key=new_key()), 400, "malformed_request")
    assert_error(world_.ada.post(path, json={}), 400, "missing_idempotency_key")
    assert_error(apply(world_.ada, plan_id, key="k" * 256), 422, "validation_failed")
    assert revision(world_) == 0 and closures(world_) == []
    key = new_key()
    original = assert_status(apply(world_.ada, plan_id, key, body={"note": "unknown fields are ignored"}), 201).json()
    assert assert_status(apply(world_.ada, plan_id, key, body={"note": "unknown fields are ignored"}), 200).json() == original
    assert_error(apply(world_.ada, plan_id, key), 409, "idempotency_key_reuse")


def test_a_replay_returns_the_original_response_even_after_later_changes(make):
    """R431: after later writes (a create and a PATCH of the moved booking) the successful key
    replays 200 with the original body and changes nothing."""
    world_ = world(make)
    plan_id, key = planned(world_.ada, CLOSED)["plan_id"], new_key()
    original = applied(world_.ada, plan_id, key)
    create(world_, ["t_4"], "20:00", 2)
    assert_status(world_.bob.patch("/reservations/MOVE01", json={"party_size": 1}), 200)
    before = exported(world_.base)
    assert assert_status(apply(world_.ada, plan_id, key), 200).json() == original
    assert exported(world_.base) == before


def test_404_restaurant_then_403_manager_then_404_plan_changing_nothing(make):
    """R426/R428/Q4: an unknown restaurant is 404; a diner, or the manager of another
    restaurant, is 403 even for an unknown plan; an unknown plan, and a plan of another
    restaurant applied under this one, are 404, both ways; nothing changes."""
    world_ = world(make)
    mine = planned(world_.ada, CLOSED)["plan_id"]
    other = assert_status(w.preview(world_.bob, closure(table="t_4"), path="/restaurants/r_other/replans"), 201).json()["plan_id"]
    before = exported(world_.base)
    assert_error(apply(world_.ada, mine, rid="r_nope"), 404, "not_found")
    for plan_id in (mine, "plan_nope"):
        assert_error(apply(world_.bob, plan_id), 403, "forbidden")
    assert_error(apply(world_.ada, "plan_nope"), 404, "not_found")
    assert_error(apply(world_.ada, other), 404, "not_found")
    assert_error(apply(world_.bob, mine, rid="r_other"), 404, "not_found")
    assert exported(world_.base) == before


def test_an_applied_plan_is_409_plan_already_applied_under_another_key(make):
    """R430/Q4: once applied, the plan under another key is 409 plan_already_applied (not
    stale_plan, though the application raised the revision), also after a later write;
    nothing changes."""
    world_ = world(make)
    plan_id = planned(world_.ada, CLOSED)["plan_id"]
    applied(world_.ada, plan_id)
    before = exported(world_.base)
    assert_error(apply(world_.ada, plan_id), 409, "plan_already_applied")
    create(world_, ["t_4"], "20:00", 2)
    after_create = exported(world_.base)
    assert_error(apply(world_.ada, plan_id), 409, "plan_already_applied")
    assert exported(world_.base) == after_create and len(closures(world_)) == 1 and before != after_create


INTERVENING = {
    "create": lambda world_: create(world_, ["t_4"], "14:00", 2),
    "patch": lambda world_: assert_status(world_.bob.patch("/reservations/FIXD01", json={"party_size": 3}), 200),
    "cancel": lambda world_: assert_status(world_.bob.post("/reservations/FIXD01/cancel"), 200),
    "move": lambda world_: assert_status(world_.bob.post("/reservation-moves", idempotency_key=new_key(), json={
        "moves": [{"reference": "FIXD01", "party_size": 3}]}), 201),
    "adoption": lambda world_: assert_status(world_.bob.post("/series", idempotency_key=new_key(), json={
        "anchor_reference": "FIXD01", "count": 2, "interval_weeks": 1}), 201),
    "policy_publication": lambda world_: publish(world_, weeks(3), capacities={"t_1": 2, "t_2": 4, "t_3": 6, "t_4": 4}),
    "another_plans_application": lambda world_: applied(world_.ada, planned(
        world_.ada, closure(table="t_4", start="12:00", end="13:00", date=weeks(2)))["plan_id"]),
}


@pytest.mark.parametrize("write", list(INTERVENING))
def test_any_intervening_write_at_the_restaurant_makes_the_plan_stale_changing_nothing(make, write):
    """R429/Q4/Q5: after a create, a real PATCH, a cancel, a move, an adoption, a policy
    publication or another plan's application at this restaurant, applying the plan is 409
    stale_plan and the export is unchanged (no closure, history, revision)."""
    world_ = world(make)
    plan_id = planned(world_.ada, CLOSED)["plan_id"]
    INTERVENING[write](world_)
    before = exported(world_.base)
    assert_error(apply(world_.ada, plan_id), 409, "stale_plan")
    assert exported(world_.base) == before


def test_writes_and_a_closure_at_another_restaurant_leave_the_plan_valid(make):
    """R440/Q4: a create at r_other and a plan applied there (a closure) do not stale r_anker's
    plan: it applies (201)."""
    world_ = world(make)
    plan_id = planned(world_.ada, CLOSED)["plan_id"]
    assert_status(world_.bob.post("/reservations", idempotency_key=new_key(), json={
        "restaurant_id": "r_other", "table_id": "t_1", "starts_at_local": fx.local(DATE), "party_size": 2}), 201)
    other = assert_status(w.preview(world_.bob, closure(table="t_2"), path="/restaurants/r_other/replans"), 201).json()
    assert_status(apply(world_.bob, other["plan_id"], rid="r_other"), 201)
    assert len(closures(world_, "r_other")) == 1
    applied(world_.ada, plan_id)


# ---- what an application does (R427, R433-R436, R412, R415, R416, Q13, Q14, Q26) ----------------------------------

def test_the_response_is_the_plan_the_new_revision_and_every_considered_booking(make):
    """R427/R436/Q14: 201 with exactly plan_id, restaurant_revision (one more than before) and
    reservations: the current body of every considered booking, moved or not, in reference
    order (KEEP01, MOVE01), equal to what the owner reads."""
    world_ = world(make)
    create(world_, ["t_4"], "14:00", 2)
    plan_id = planned(world_.ada, CLOSED)["plan_id"]
    body = applied(world_.ada, plan_id)
    assert set(body) == {"plan_id", "restaurant_revision", "reservations"}
    assert body["plan_id"] == plan_id and body["restaurant_revision"] == 2 == revision(world_)
    assert body["reservations"] == [read(world_, "KEEP01"), read(world_, "MOVE01")]


def test_a_moved_booking_changes_only_its_tables_and_gains_one_reassigned_entry(make):
    """R403/R412/R434/Q13: the moved booking reads t_1 (`table_ids` and `table_id`), its
    revision one higher, and everything else as before: reference, owner, party, start,
    `ends_at`, status and accepted terms. Its history gains exactly one entry: `reassigned`,
    one `table_ids` change with the complete lists (a single to a single included), the
    `plan_id`, the new revision and the same accepted terms."""
    world_ = world(make)
    before, entries = read(world_, "MOVE01"), history(world_, "MOVE01")
    plan_id = planned(world_.ada, CLOSED)["plan_id"]
    applied(world_.ada, plan_id)
    after, now = read(world_, "MOVE01"), history(world_, "MOVE01")
    assert after["table_ids"] == ["t_1"] and after.get("table_id") == "t_1"
    assert after["revision"] == before["revision"] + 1
    assert {k: v for k, v in after.items() if k not in ("table_ids", "table_id", "revision")} \
        == {k: v for k, v in before.items() if k not in ("table_ids", "table_id", "revision")}
    assert now[:-1] == entries and len(now) == len(entries) + 1
    entry = now[-1]
    assert entry["event"] == "reassigned" and entry["plan_id"] == plan_id
    assert entry["changes"] == [{"field": "table_ids", "from": ["t_2"], "to": ["t_1"]}]
    assert entry["revision"] == after["revision"] and entry["accepted_terms"] == before["accepted_terms"]
    assert entry["seq"] == len(now)


def test_a_booking_moved_onto_a_pair_reads_it_in_declared_order(make):
    """R434/E2/Q13: a party of 5 on the pair t_1+t_2 closed out of t_2 goes to the pair
    declared as t_4+t_3; the entry's change lists both sets completely."""
    world_ = world(make, caps=(2, 4, 3, 3), pairs=[("t_1", "t_2"), ("t_4", "t_3")],
                   seeds=[seed("PAIR01", ["t_1", "t_2"], "19:00", party=5)])
    applied(world_.ada, planned(world_.ada, CLOSED)["plan_id"])
    assert read(world_, "PAIR01")["table_ids"] == ["t_4", "t_3"] and "table_id" not in read(world_, "PAIR01")
    assert history(world_, "PAIR01")[-1]["changes"] == [{"field": "table_ids", "from": ["t_1", "t_2"], "to": ["t_4", "t_3"]}]


def test_unmoved_bookings_gain_nothing(make):
    """R410/R435: the considered but unmoved KEEP01 and the fixed FIXD01 read the same and have
    the same history after the application."""
    world_ = world(make)
    before = {ref: (read(world_, ref), history(world_, ref)) for ref in ("KEEP01", "FIXD01")}
    applied(world_.ada, planned(world_.ada, CLOSED)["plan_id"])
    assert {ref: (read(world_, ref), history(world_, ref)) for ref in ("KEEP01", "FIXD01")} == before


def test_the_restaurant_revision_rises_once_for_a_plan_that_moves_several_bookings(make):
    """R436: a plan moving three bookings raises the restaurant revision by exactly one."""
    world_ = world(make, caps=(2, 4, 6, 4), pairs=[],
                   seeds=[seed("MOVEA1", ["t_2"], "12:00"), seed("MOVEB1", ["t_2"], "15:00"),
                          seed("MOVEC1", ["t_2"], "19:00")])
    plan = planned(world_.ada, closure(start="12:00", end="23:00"))
    assert plan["moved_count"] == 3
    body = applied(world_.ada, plan["plan_id"])
    assert body["restaurant_revision"] == 1 == revision(world_)


def test_a_booking_inside_its_cutoff_is_still_moved(make):
    """R415: a booking whose diner may no longer cancel it (7-day cutoff, tomorrow: 409
    cutoff_passed) is moved by the application (201)."""
    tomorrow = fx.booking_date(lead=1)
    world_ = world(make, seeds=[seed("MOVE01", ["t_2"], "19:00", date=tomorrow)], cancellation_cutoff_minutes=10080)
    assert_error(world_.bob.post("/reservations/MOVE01/cancel"), 409, "cutoff_passed")
    applied(world_.ada, planned(world_.ada, closure(start="19:00", end="21:00", date=tomorrow))["plan_id"])
    assert read(world_, "MOVE01")["table_ids"] == ["t_1"] and read(world_, "MOVE01")["status"] == "confirmed"


def test_series_occurrences_keep_flags_dates_references_and_terms_and_the_series_rises_once(make):
    """R459/R460/Q13/Q16: a closure across three weeks moves all three occurrences of a series
    (one of them already an exception): references, local starts and accepted terms are
    kept, the exception flags stay [False, True, False], the series revision rises once and
    the restaurant revision once; a later diner PATCH of a moved occurrence still makes it an
    exception."""
    world_ = world(make, seeds=[seed("OCC000", ["t_2"], "19:00")])
    series = assert_status(world_.bob.post("/series", idempotency_key=new_key(), json={
        "anchor_reference": "OCC000", "count": 3, "interval_weeks": 1}), 201).json()
    sid = series["series_id"] if "series_id" in series else series["id"]
    refs = [o["reference"] for o in series["occurrences"]]
    assert_status(world_.bob.patch(f"/reservations/{refs[1]}", json={"party_size": 3}), 200)
    before = assert_status(world_.bob.get(f"/series/{sid}"), 200).json()
    reads = {ref: read(world_, ref) for ref in refs}
    restaurant_revision = revision(world_)
    plan = planned(world_.ada, closure(start="18:00", end="23:00", date=DATE)
                   | {"to": w.instant("23:00", weeks(2)).isoformat()})
    assert plan["moved_count"] == 3
    applied(world_.ada, plan["plan_id"])
    after = assert_status(world_.bob.get(f"/series/{sid}"), 200).json()
    assert after["revision"] == before["revision"] + 1 and revision(world_) == restaurant_revision + 1
    assert [o["exception"] for o in after["occurrences"]] == [o["exception"] for o in before["occurrences"]] \
        == [False, True, False]
    assert [o["reference"] for o in after["occurrences"]] == refs
    for ref in refs:
        now = read(world_, ref)
        assert now["table_ids"] != reads[ref]["table_ids"]
        assert (now["starts_at_local"], now["ends_at"], now["accepted_terms"], now["party_size"]) == \
            (reads[ref]["starts_at_local"], reads[ref]["ends_at"], reads[ref]["accepted_terms"], reads[ref]["party_size"])
    assert_status(world_.bob.patch(f"/reservations/{refs[2]}", json={"party_size": 1}), 200)
    later = assert_status(world_.bob.get(f"/series/{sid}"), 200).json()
    assert [o["exception"] for o in later["occurrences"]] == [False, True, True]


def test_a_zero_move_application_records_the_closure_raises_the_revision_and_changes_availability(make):
    """R433/R436/Q26/Q27: a plan that moves nothing (t_4 at 12:00-13:00, empty) applies: 201
    with no reservations, the revision one higher, the closure recorded; an availability
    request asked twice before (t_4 offered at 12:00, same answer) answers without t_4 after."""
    world_ = world(make, seeds=[])
    first, second = slot(world_, "12:00"), slot(world_, "12:00")
    assert first == second and "t_4" in first["available_table_ids"]
    body = applied(world_.ada, planned(world_.ada, closure(table="t_4", start="12:00", end="13:00"))["plan_id"])
    assert body["reservations"] == [] and body["restaurant_revision"] == 1 == revision(world_)
    assert len(closures(world_)) == 1
    assert "t_4" not in slot(world_, "12:00")["available_table_ids"]


# ---- what a closure does afterwards (R408, R414, R437, R438, Q6, Q15) ---------------------------------------------

@pytest.mark.parametrize("hhmm,inside", [("17:30", False), ("18:00", True), ("20:30", True), ("21:00", False)])
def test_the_closure_takes_the_table_and_its_pairs_out_of_availability_exactly_during_it(make, hhmm, inside):
    """R408/R437/R438/Q6/Q15: for 90-minute bookings, a start at 18:00 or 20:30 overlaps the
    closure of t_2 over [19:00, 21:00): t_2 and the pair t_1+t_2 are not offered and explain
    says t_2's no_overlap does not hold and it is not available; at 17:30 (ending at 19:00)
    and 21:00 both are offered and no_overlap holds. The pair t_3+t_4 is unaffected."""
    world_ = closed_world(make)
    plain, explained = slot(world_, hhmm), slot(world_, hhmm, explain=True)
    options = [option["table_ids"] for option in plain["available_options"]]
    t2 = next(e for e in explained["explain"] if e["table_id"] == "t_2")
    no_overlap = next(r["holds"] for r in t2["rules"] if r["rule"] == "no_overlap")
    assert ("t_2" in plain["available_table_ids"]) is (not inside)
    assert (["t_1", "t_2"] in options) is (not inside and "t_1" in plain["available_table_ids"])
    assert no_overlap is (not inside) and t2["available"] is (not inside)
    assert ["t_3", "t_4"] in options or "t_3" not in plain["available_table_ids"] or "t_4" not in plain["available_table_ids"]


WRITES = {
    "create_inside_start": (lambda x: x.bob.post("/reservations", idempotency_key=new_key(), json={
        "restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": fx.local(DATE, "18:00"), "party_size": 2}), True),
    "create_inside_end": (lambda x: x.bob.post("/reservations", idempotency_key=new_key(), json={
        "restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": fx.local(DATE, "20:30"), "party_size": 2}), True),
    "create_pair_inside": (lambda x: x.bob.post("/reservations", idempotency_key=new_key(), json={
        "restaurant_id": "r_anker", "table_ids": ["t_2", "t_1"], "starts_at_local": fx.local(DATE, "20:30"),
        "party_size": 5}), True),
    "create_just_before": (lambda x: x.bob.post("/reservations", idempotency_key=new_key(), json={
        "restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": fx.local(DATE, "17:30"), "party_size": 2}), False),
    "create_just_after": (lambda x: x.bob.post("/reservations", idempotency_key=new_key(), json={
        "restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": fx.local(DATE, "21:00"), "party_size": 2}), False),
    "patch_inside": (lambda x: x.bob.patch("/reservations/FIXD01", json={
        "table_id": "t_2", "starts_at_local": fx.local(DATE, "19:30")}), True),
    "patch_outside": (lambda x: x.bob.patch("/reservations/FIXD01", json={
        "table_id": "t_2", "starts_at_local": fx.local(DATE, "15:00")}), False),
    "move_inside": (lambda x: x.bob.post("/reservation-moves", idempotency_key=new_key(), json={"moves": [
        {"reference": "FIXD01", "table_id": "t_2", "starts_at_local": fx.local(DATE, "20:00")}]}), True),
    "move_outside": (lambda x: x.bob.post("/reservation-moves", idempotency_key=new_key(), json={"moves": [
        {"reference": "FIXD01", "table_id": "t_2", "starts_at_local": fx.local(DATE, "12:30")}]}), False),
}


@pytest.mark.parametrize("write", list(WRITES))
def test_writes_onto_the_closure_are_refused_just_inside_and_allowed_just_outside(make, write):
    """R437/Q6/Q15: after the closure of t_2 over [19:00, 21:00), a create on t_2 at 18:00 or
    20:30, a create on the pair t_2+t_1 at 20:30, a PATCH onto t_2 at 19:30 and a move onto t_2
    at 20:00 are 409 table_unavailable; at 17:30, 21:00, 15:00 and 12:30 they succeed."""
    world_ = closed_world(make)
    send, inside = WRITES[write]
    response = send(world_)
    if inside:
        assert_error(response, 409, "table_unavailable")
    else:
        assert response.status_code in (200, 201), response.text


@pytest.mark.parametrize("anchor,inside", [("19:30", True), ("17:30", False)])
def test_an_adoption_whose_occurrence_falls_in_a_closure_is_refused(make, anchor, inside):
    """R437/Q15: with t_2 closed over [19:00, 21:00) a week after the anchor, adopting a series
    of two from an anchor at 19:30 is 409 table_unavailable; from 17:30 it succeeds."""
    world_ = world(make, seeds=[seed("ANCH01", ["t_2"], anchor)])
    applied(world_.ada, planned(world_.ada, closure(start="19:00", end="21:00", date=weeks(1)))["plan_id"])
    response = world_.bob.post("/series", idempotency_key=new_key(), json={
        "anchor_reference": "ANCH01", "count": 2, "interval_weeks": 1})
    if inside:
        assert_error(response, 409, "table_unavailable")
    else:
        assert_status(response, 201)


def test_a_later_preview_treats_an_applied_closure_as_taken(make):
    """R414/Q15: with t_2 closed, closing t_3 over the same time moves KEEP01 (party 4) to t_4
    (rank 3), never to the free-looking t_2 (rank 1)."""
    world_ = closed_world(make)
    plan = planned(world_.ada, closure(table="t_3", start="19:00", end="21:00"))
    assert w.seats(plan) == [("KEEP01", ["t_4"], True), ("MOVE01", ["t_1"], False)]


# ---- export and import (Q24, J6) -----------------------------------------------------------------------------------

def test_closures_and_reassignments_restore_in_another_stage_4_and_still_block(make):
    """Q24/J6: the export carries the closure (with its plan) and the `reassigned` entry (with
    `plan_id`); imported into a second stage-4 it re-exports equal, the closure still refuses
    a create inside it, and the application's key replays there with the original body."""
    world_ = world(make)
    plan_id, key = planned(world_.ada, CLOSED)["plan_id"], new_key()
    original = applied(world_.ada, plan_id, key)
    body = exported(world_.base)
    restaurant = next(r for r in body["state"]["restaurants"] if r["id"] == "r_anker")
    assert [c["plan_id"] for c in restaurant["closures"]] == [plan_id] and restaurant["closures"][0]["table_id"] == "t_2"
    moved = next(r for r in body["state"]["reservations"] if r["reference"] == "MOVE01")
    assert moved["history"][-1]["event"] == "reassigned" and moved["history"][-1]["plan_id"] == plan_id
    second = url("TABLEKEEPER_SECOND_URL")
    with Api(second, timeout=RESET_TIMEOUT) as control:
        assert_status(control.post("/_test/import", json=body), 204)
    assert exported(second) == body
    with Api(second, token=world_.bob.token) as bob2:
        assert_error(bob2.post("/reservations", idempotency_key=new_key(), json={
            "restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": fx.local(DATE, "20:30"), "party_size": 2}),
            409, "table_unavailable")
    with Api(second, token=world_.ada.token) as ada2:
        assert assert_status(apply(ada2, plan_id, key), 200).json() == original
    assert exported(second) == body


def _closure_of(body):
    return next(r for r in body["state"]["restaurants"] if r["id"] == "r_anker")["closures"][0]


BROKEN = {
    "unknown_table": lambda b: _closure_of(b).update(table_id="t_9"),
    "from_after_to": lambda b: _closure_of(b).update({"from": _closure_of(b)["to"], "to": _closure_of(b)["from"]}),
    "naive_from": lambda b: _closure_of(b).update({"from": _closure_of(b)["from"][:19]}),
    "unknown_plan": lambda b: _closure_of(b).update(plan_id="plan_nope"),
    "not_the_plans_interval": lambda b: _closure_of(b).update(to=w.instant("22:00").isoformat()),
    "reassigned_without_plan_id": lambda b: next(r for r in b["state"]["reservations"]
                                                 if r["reference"] == "MOVE01")["history"][-1].pop("plan_id"),
}


@pytest.mark.parametrize("case", list(BROKEN))
def test_a_broken_closure_or_reassignment_is_refused_on_import(make, case):
    """J6/Q24: an export whose closure names an unknown table, runs backwards, has a naive
    instant, names an unknown plan or is not its plan's interval, or whose `reassigned` entry
    has no `plan_id`, is 422 validation_failed, the destination unchanged."""
    world_ = closed_world(make)
    body = exported(world_.base)
    bad = copy.deepcopy(body)
    BROKEN[case](bad)
    with Api(world_.base, timeout=RESET_TIMEOUT) as control:
        assert_error(control.post("/_test/import", json=bad), 422, "validation_failed")
    assert exported(world_.base) == body


def test_an_earlier_stage_export_imports_with_no_closures(base_url):
    """Q24/J6: a stage-3 export imports into stage 4 with every restaurant's closures empty."""
    with Api(url("TABLEKEEPER_STAGE3_URL"), timeout=RESET_TIMEOUT) as previous:
        assert_status(previous.post("/_test/reset", json=fx.fixture()), 204)
        body = assert_status(previous.get("/_test/export"), 200).json()
    with Api(base_url, timeout=RESET_TIMEOUT) as control:
        assert_status(control.post("/_test/import", json=body), 204)
        state = assert_status(control.get("/_test/export"), 200).json()["state"]
    assert [r["closures"] for r in state["restaurants"]] == [[]]
