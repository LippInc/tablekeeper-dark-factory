"""S4-I5 acceptance checks (verifier seat): export and import across stages 1-4, from the stage-4
specification ("A stage-4 service must accept exports produced by the same team's stages 1-3.
These operations must support imported series, including moved and cancelled occurrences.
Earlier booking and series receipts, histories and retries remain valid."; R462-R464) with the
plan's J6, Q24, Q28, Q29 and the earlier stages' D18, D20, E8, H6, P4.

The worlds are built through the running stage-3, stage-2 and stage-1 services' own APIs
(TABLEKEEPER_STAGE3_URL, _STAGE2_URL, _STAGE1_URL) with the builders of acceptance/stage-3 and
acceptance/stage-2, exported there and imported into this service; the stage-4 world is built
here and imported into the second stage-4 (TABLEKEEPER_SECOND_URL). Resets all of them: run it
alone against other files that reset them.
"""
from __future__ import annotations

import copy
import datetime as dt
import importlib.util
import pathlib
import time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import fixtures as fx
from harness.http import RESET_TIMEOUT, Api, assert_error, assert_status, new_key

pytestmark = pytest.mark.stage(4)

_spec = importlib.util.spec_from_file_location(
    "s3_import", pathlib.Path(__file__).resolve().parents[1] / "stage-3" / "test_s3_i5_import.py")
s3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s3)
s2 = s3.stage2  # acceptance/stage-2/test_s2_i2_upgrade.py
DATE, weeks, url, export, import_into = s3.DATE, s3.weeks, s3.url, s3.export, s3.import_into


def berlin(date: str, hhmm: str) -> str:
    """The instant of a local time at the restaurant, with its offset."""
    return dt.datetime.combine(dt.date.fromisoformat(date), dt.time.fromisoformat(hhmm), ZoneInfo("Europe/Berlin")).isoformat()


def schema4_start(base: str) -> None:
    """R462/Q5/Q24: an earlier stage's world arrives at schema 4, every restaurant at revision 0,
    no closures and no stored plans."""
    state = export(base)["state"]
    assert state["schema"] == 4 and state["plans"] == []
    assert [(r["revision"], r["closures"]) for r in state["restaurants"]] == [(0, [])] * len(state["restaurants"])


def replays(base: str, sent: dict) -> None:
    """R464/E8/D18: every recorded key replays 200 with its original body, changing nothing."""
    before = export(base)
    for name, s in sent.items():
        if s.response is None or "error" in s.response:
            continue
        with Api(base, token=s.token) as client:
            assert assert_status(client.post(s.path, json=s.body, idempotency_key=s.key), 200).json() == s.response, name
    assert export(base) == before


def series_of(client, series_id) -> list[tuple]:
    body = assert_status(client.get(f"/series/{series_id}"), 200).json()
    return [(o["exception"], o["reservation"]["status"], o["reservation"]["starts_at_local"], o["reservation"]["table_ids"])
            for o in body["occurrences"]]


# ---- a running stage-3 service's export (R462, R463, R464) -----------------------------------------------------

@pytest.fixture
def from_stage_3(base_url):
    """The acceptance/stage-3 world (managers, a policy, revisions, histories, a series whose
    occurrence 1 a diner moved) built on the running stage-3 service, with the series'
    occurrence 2 then cancelled there; its reads and export, imported here."""
    source = url("TABLEKEEPER_STAGE3_URL")
    made = []

    def api(token=None):
        made.append(Api(source, token=token))
        return made[-1]

    def reset(fixture):
        with Api(source, timeout=RESET_TIMEOUT) as control:
            assert_status(control.post("/_test/reset", json=fixture), 204)

    world = s3.stage3_world(reset, api)
    world.refs = [o["reference"] for o in world.sent["adoption"].response["occurrences"]]
    assert_status(world.ada.post(f"/reservations/{world.refs[2]}/cancel"), 200)
    world.views = s3.views(lambda token: api(token), world)
    world.exported = export(source)
    assert world.exported["state"]["schema"] == 3
    time.sleep(1.1)
    import_into(base_url, world.exported)
    yield world
    for client in made:
        client.close()


def test_a_stage_3_export_arrives_whole(from_stage_3, base_url):
    """R462/R464/Q24: at schema 4 with revision 0 and no closures or plans; both users log in;
    their old tokens read the same lists, reservations, histories, decisions, series, policies
    and explained availability as the stage-3 service did; every key replays its original body."""
    world = from_stage_3
    schema4_start(base_url)
    for user in (fx.ADA, fx.BOB):
        with Api(base_url) as client:
            client.authenticate(user["email"], user["password"])
    assert s3.views(lambda token: Api(base_url, token=token), world) == world.views
    replays(base_url, world.sent)


def test_an_imported_series_is_repaired_and_amended(from_stage_3, base_url):
    """R463/R459/R460/Q29: on the imported stage-3 world a manager previews and applies a plan
    that moves the diner-moved occurrence 1 (an exception) to t_3: its flag, date, time and
    terms stay, the series rises once; then the series (occurrence 1 moved, 2 cancelled) is
    amended from index 0: only occurrence 0 changes, the flags stay [F, T, F]."""
    world = from_stage_3
    with Api(base_url, token=world.ada.token) as ada:
        before = assert_status(ada.get(f"/reservations/{world.refs[1]}"), 200).json()
        revision = assert_status(ada.get(f"/series/{world.series_id}"), 200).json()["revision"]
        plan = assert_status(ada.post("/restaurants/r_anker/replans", idempotency_key=new_key(), json={
            "table_id": "t_2", "from": berlin(weeks(1), "19:30"), "to": berlin(weeks(1), "21:00")}), 201).json()
        assert [(a["reference"], a["table_ids"], a["changed"]) for a in plan["assignments"]] == [(world.refs[1], ["t_3"], True)]
        assert_status(ada.post(f"/restaurants/r_anker/replans/{plan['plan_id']}/apply", idempotency_key=new_key(), json={}), 201)
        moved = assert_status(ada.get(f"/reservations/{world.refs[1]}"), 200).json()
        assert moved["table_ids"] == ["t_3"]
        assert {k: moved[k] for k in ("starts_at_local", "ends_at", "accepted_terms", "party_size", "status")} == \
            {k: before[k] for k in ("starts_at_local", "ends_at", "accepted_terms", "party_size", "status")}
        series = assert_status(ada.get(f"/series/{world.series_id}"), 200).json()
        assert series["revision"] == revision + 1 and [o["exception"] for o in series["occurrences"]] == [False, True, False]
        assert_status(ada.post(f"/series/{world.series_id}/amend", idempotency_key=new_key(), json={
            "expected_revision": revision + 1, "from_index": 0, "local_time": "21:30"}), 201)
        assert series_of(ada, world.series_id) == [
            (False, "confirmed", f"{DATE}T21:30", ["t_2"]),
            (True, "confirmed", f"{weeks(1)}T20:00", ["t_3"]),
            (False, "cancelled", f"{weeks(2)}T19:00", ["t_2"])]


# ---- running stage-2 and stage-1 services' exports (R462, R464, Q29) -------------------------------------------

@pytest.fixture
def from_stage_2(base_url):
    world = s3.stage2_world(url("TABLEKEEPER_STAGE2_URL"))
    time.sleep(1.1)
    import_into(base_url, world.exported)
    return world


@pytest.fixture
def from_stage_1(base_url):
    with Api(url("TABLEKEEPER_STAGE1_URL"), timeout=RESET_TIMEOUT) as stage1:
        world = s2.stage1_world(stage1)
    time.sleep(1.1)
    import_into(base_url, world.exported)
    return world


def earlier_world_arrives(world, base_url, keys_of):
    schema4_start(base_url)
    for name, token in world.tokens.items():
        with Api(base_url, token=token) as client:
            listed = {b["reference"]: b for b in assert_status(client.get("/reservations"), 200).json()["reservations"]}
        before = {b["reference"]: b for b in world.lists[name]}
        assert sorted(listed) == sorted(before), name
        for ref, booking in before.items():
            assert {k: listed[ref][k] for k in keys_of(booking)} == {k: booking[k] for k in keys_of(booking)}, ref
    for user in (fx.ADA, fx.BOB, s2.CY):
        with Api(base_url) as client:
            client.authenticate(user["email"], user["password"])
    with Api(base_url) as anon:
        for party, slots in world.availability.items():
            assert [(s["starts_at_local"], s["available_table_ids"]) for s in s3.slots_without_explain(anon, DATE, party)] == \
                [(s["starts_at_local"], s["available_table_ids"]) for s in slots], party
    replays(base_url, {n: s for n, s in world.sent.items() if n != "failed"})


def amend_a_series_adopted_after_import(base_url, token, anchor):
    """R463 on an imported world without series (Q29): a series adopted in stage 4 from an
    imported booking, occurrence 1 moved by the diner, occurrence 2 cancelled, is amended from
    index 0 to 12:30 (201): occurrence 0 moves, the flags read [F, T, F]."""
    with Api(base_url, token=token) as ada:
        series = assert_status(ada.post("/series", idempotency_key=new_key(), json={
            "anchor_reference": anchor, "count": 3, "interval_weeks": 1}), 201).json()
        refs = [o["reference"] for o in series["occurrences"]]
        assert_status(ada.patch(f"/reservations/{refs[1]}", json={"starts_at_local": fx.local(weeks(1), "19:00")}), 200)
        assert_status(ada.post(f"/reservations/{refs[2]}/cancel"), 200)
        revision = assert_status(ada.get(f"/series/{series['series_id']}"), 200).json()["revision"]
        assert_status(ada.post(f"/series/{series['series_id']}/amend", idempotency_key=new_key(), json={
            "expected_revision": revision, "from_index": 0, "local_time": "12:30"}), 201)
        got = series_of(ada, series["series_id"])
        assert [(flag, status, start[11:]) for flag, status, start, _ in got] == [
            (False, "confirmed", "12:30"), (True, "confirmed", "19:00"), (False, "cancelled", "18:00")]


def a_preview_is_forbidden(base_url, token):
    """Q29: a migrated restaurant has no managers, so a preview there is 403 forbidden."""
    with Api(base_url, token=token) as ada:
        assert_error(ada.post("/restaurants/r_anker/replans", idempotency_key=new_key(), json={
            "table_id": "t_1", "from": berlin(DATE, "12:00"), "to": berlin(DATE, "13:00")}), 403, "forbidden")


def test_a_stage_2_export_arrives_whole_and_supports_the_stage_4_operations(from_stage_2, base_url):
    """R462/R463/R464/Q29/E8: a running stage-2 service's export arrives at schema 4, revision 0,
    no closures; lists read the same on stage 2's keys, the users log in, availability is the
    same, every key replays verbatim; a preview is 403; a series adopted from an imported
    booking is amended."""
    world = from_stage_2
    earlier_world_arrives(world, base_url, lambda booking: list(booking))
    a_preview_is_forbidden(base_url, world.tokens["ada"])
    amend_a_series_adopted_after_import(base_url, world.tokens["ada"], world.sent["ada_single"].response["reference"])


def test_a_stage_1_export_arrives_whole_and_supports_the_stage_4_operations(from_stage_1, base_url):
    """R462/R463/R464/Q29/E8: the same for a running stage-1 service's export (stage-1 keys)."""
    world = from_stage_1
    earlier_world_arrives(world, base_url, lambda booking: list(booking))
    a_preview_is_forbidden(base_url, world.tokens["ada"])
    amend_a_series_adopted_after_import(base_url, world.tokens["ada"], world.sent["ada_create"].response["reference"])


# ---- stage 4 to stage 4 (R464, Q24, J6) ------------------------------------------------------------------------

@pytest.fixture
def stage4_world(reset, api, base_url):
    """The stage-3 world built here, plus an unapplied preview, an applied plan moving series
    occurrence 2 to t_3 (a `reassigned` entry, a closure), and an amendment of the series; each
    keyed request recorded for replay."""
    world = s3.stage3_world(reset, api)
    refs = [o["reference"] for o in world.sent["adoption"].response["occurrences"]]

    def keyed(name, path, payload):
        key = new_key()
        response = assert_status(world.ada.post(path, json=payload, idempotency_key=key), 201).json()
        world.sent[name] = SimpleNamespace(token=world.ada.token, path=path, body=payload, key=key, response=response)
        return response

    def closure(table, date, start, end):
        return {"table_id": table, "from": berlin(date, start), "to": berlin(date, end)}

    keyed("preview", "/restaurants/r_anker/replans", closure("t_1", DATE, "12:00", "13:00"))
    plan = keyed("repair_preview", "/restaurants/r_anker/replans", closure("t_2", weeks(2), "18:30", "20:00"))
    assert [(a["reference"], a["table_ids"]) for a in plan["assignments"]] == [(refs[2], ["t_3"])]
    keyed("repair", f"/restaurants/r_anker/replans/{plan['plan_id']}/apply", {})
    revision = assert_status(world.ada.get(f"/series/{world.series_id}"), 200).json()["revision"]
    keyed("amend", f"/series/{world.series_id}/amend", {"expected_revision": revision, "from_index": 0, "local_time": "21:30"})
    world.refs, world.body = refs, export(base_url)
    return world


def test_a_stage_4_export_restores_unchanged_in_another_stage_4(stage4_world, base_url):
    """R464/Q24/J6: the stage-4 export (restaurant revisions, a closure, stored and applied plans,
    a `reassigned` entry, an amended series, receipts of previews, an application and an
    amendment) re-exports equal from a fresh stage-4; every read (lists, reservations,
    histories, decisions, series, policies, explained availability on three dates) is equal;
    every key, the preview's, application's and amendment's included, replays 200 with its
    original body there and changes nothing."""
    world, second = stage4_world, url("TABLEKEEPER_SECOND_URL")
    state = world.body["state"]
    closures = next(r for r in state["restaurants"] if r["id"] == "r_anker")["closures"]
    assert len(closures) == 1 and len(state["plans"]) == 2
    assert any(e["event"] == "reassigned" and "plan_id" in e for r in state["reservations"] for e in r["history"])
    import_into(second, world.body)
    assert export(second) == world.body

    def reads(base):
        found = s3.views(lambda token: Api(base, token=token), world)
        found["closed day"] = s3.explained_ids(Api(base), weeks(2), 2)
        return found

    assert reads(second) == reads(base_url)
    replays(second, world.sent)


def _restaurant(body):
    return next(r for r in body["state"]["restaurants"] if r["id"] == "r_anker")


def _into_the_closure(body):
    """Q28: bob's confirmed booking (t_3, the first day, 90 minutes) moved onto the closed t_2 at
    the closure's start - nothing else holds t_2 then."""
    closure = _restaurant(body)["closures"][0]
    booking = next(r for r in body["state"]["reservations"]
                   if r["user_id"] == "u_bob" and r["status"] == "confirmed" and r["reference"] != "SEED31")
    booking.update(table_ids=[closure["table_id"]], starts_at=closure["from"])


INVALID = {
    "closure_on_an_unknown_table": lambda b: _restaurant(b)["closures"][0].update(table_id="t_9"),
    "closure_from_after_to": lambda b: _restaurant(b)["closures"][0].update(
        {"from": _restaurant(b)["closures"][0]["to"], "to": _restaurant(b)["closures"][0]["from"]}),
    "plan_of_an_unknown_restaurant": lambda b: b["state"]["plans"][0].update(restaurant_id="r_nope"),
    "reassigned_without_plan_id": lambda b: next(e for r in b["state"]["reservations"] for e in r["history"]
                                                 if e["event"] == "reassigned").pop("plan_id"),
    "negative_restaurant_revision": lambda b: _restaurant(b).update(revision=-1),
    "schema_5": lambda b: b["state"].update(schema=5),
    "confirmed_booking_inside_a_closure": _into_the_closure,
}


@pytest.mark.parametrize("case", list(INVALID))
def test_an_invalid_stage_4_export_is_refused_and_changes_nothing(stage4_world, case):
    """J6/Q24/Q28/D20: a closure on an unknown table or running backwards, a plan of an unknown
    restaurant, a `reassigned` entry without `plan_id`, a negative restaurant revision, schema 5,
    and a confirmed booking inside a closure on its table are 422 validation_failed, the
    destination unchanged (the unedited export imports there)."""
    second = url("TABLEKEEPER_SECOND_URL")
    import_into(second, stage4_world.body)
    before = export(second)
    bad = copy.deepcopy(stage4_world.body)
    INVALID[case](bad)
    with Api(second, timeout=RESET_TIMEOUT) as control:
        assert_error(control.post("/_test/import", json=bad), 422, "validation_failed")
    assert export(second) == before
