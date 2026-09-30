"""S4-I1 acceptance checks (verifier seat): the restaurant revision, from the stage-4
specification ("A restaurant revision starts at 0 after reset and increments once for each
successful new booking, real amendment, cancellation, policy publication or plan application.
No-op writes, failures, previews and replays do not increment it.") with stage-3 R359/R368 and
the plan's J1, J6, Q5 and Q24. Read through the schema-4 export until previews carry it.

Uses a second stage-4 service (TABLEKEEPER_SECOND_URL) and the stage-3, stage-2 and stage-1
services of the same checkout (TABLEKEEPER_STAGE3_URL, _STAGE2_URL, _STAGE1_URL), and resets
them: run it alone against other files that reset them.
"""
from __future__ import annotations

import copy
import datetime as dt
import importlib.util
import os
import pathlib

import pytest

import fixtures as fx
from harness.http import RESET_TIMEOUT, Api, assert_error, assert_status, new_key

pytestmark = pytest.mark.stage(4)

DATE = fx.booking_date()
RESTAURANTS = [{**fx.managed_restaurant(), "combinable": [["t_1", "t_2"]]},
               {**fx.managed_restaurant(rid="r_other", name="Zum Anderen"), "combinable": [["t_1", "t_2"]]}]


def weeks(n: int) -> str:
    return (dt.date.fromisoformat(DATE) + dt.timedelta(weeks=n)).isoformat()


def seed(reference, tables, hhmm="19:00", user="u_ada", party=2, status="confirmed", rid="r_anker") -> dict:
    return {"id": f"res_{reference}", "reference": reference, "user_id": user, "restaurant_id": rid,
            **({"table_id": tables[0]} if len(tables) == 1 else {"table_ids": tables}),
            "starts_at_local": fx.local(DATE, hhmm), "party_size": party, "status": status}


SEEDS = [seed("OWN001", ["t_3"]), seed("OWN002", ["t_2"]), seed("PAIR01", ["t_1", "t_2"], "21:00", party=5),
         seed("GONE01", ["t_3"], "21:00", status="cancelled"), seed("OTH001", ["t_3"], rid="r_other")]


def url(name: str) -> str:
    value = os.environ.get(name)
    assert value, f"set {name} to the service of the same checkout"
    return value.rstrip("/")


def exported(base: str) -> dict:
    with Api(base, timeout=RESET_TIMEOUT) as control:
        return assert_status(control.get("/_test/export"), 200).json()


def revisions(base: str) -> dict:
    return {r["id"]: r["revision"] for r in exported(base)["state"]["restaurants"]}


@pytest.fixture
def world(reset, api):
    reset(fx.fixture(restaurants=RESTAURANTS, reservations=SEEDS))
    return (api().authenticate(fx.ADA["email"], fx.ADA["password"]),
            api().authenticate(fx.BOB["email"], fx.BOB["password"]))


def create(client, table="t_2", hhmm="19:00", party=2, key=None, date=None, **tables):
    date = date or weeks(1)  # a date without seeds, unless one is named
    return client.post("/reservations", idempotency_key=key or new_key(), json={
        "restaurant_id": "r_anker", **(tables or {"table_id": table}), "starts_at_local": fx.local(date, hhmm),
        "party_size": party})


def move(client, *items, key=None):
    return client.post("/reservation-moves", idempotency_key=key or new_key(), json={"moves": list(items)})


def publish(client, key=None, **overrides):
    return client.post("/restaurants/r_anker/policies", idempotency_key=key or new_key(),
                       json=fx.policy(weeks(2), **overrides))


def adopt(client, reference="OWN001", count=4, key=None):
    return client.post("/series", idempotency_key=key or new_key(), json={
        "anchor_reference": reference, "count": count, "interval_weeks": 1})


# ---- 0 after reset (R422, Q5) ------------------------------------------------------------------------

def test_a_reset_starts_every_restaurant_at_0_and_the_export_is_schema_4(world, base_url):
    """R422/Q5/Q24: after a reset with seeded bookings (confirmed, cancelled, a pair), every
    restaurant's revision is 0 in the schema-4 export."""
    body = exported(base_url)
    assert body["state"]["schema"] == 4
    assert revisions(base_url) == {"r_anker": 0, "r_other": 0}


# ---- +1 once per successful operation (R422, R359, R368) ---------------------------------------------

WRITES = {
    "create_single": lambda ada, bob: assert_status(create(bob), 201),
    "create_pair": lambda ada, bob: assert_status(create(bob, hhmm="21:00", party=5, table_ids=["t_2", "t_1"]), 201),
    "adoption_of_four": lambda ada, bob: assert_status(adopt(ada, count=4), 201),
    "real_patch": lambda ada, bob: assert_status(ada.patch("/reservations/OWN001", json={"party_size": 3}), 200),
    "move_batch_two_real_changes": lambda ada, bob: assert_status(move(
        ada, {"reference": "OWN001", "party_size": 3},
        {"reference": "OWN002", "table_id": "t_1"}), 201),
    "cancel": lambda ada, bob: assert_status(ada.post("/reservations/OWN001/cancel"), 200),
    "policy_publication": lambda ada, bob: assert_status(publish(ada), 201),
}


@pytest.mark.parametrize("write", list(WRITES))
def test_each_successful_write_raises_its_restaurant_once(world, base_url, write):
    """R422/R359/R368/Q5: a create (single or pair), an adoption of four (once for the whole
    operation), a real PATCH, a move batch with two real changes (once for the batch), a
    cancel and a policy publication each raise their restaurant's revision by exactly 1; the
    other restaurant keeps its own."""
    WRITES[write](*world)
    assert revisions(base_url) == {"r_anker": 1, "r_other": 0}


# ---- +0 for no-ops, failures and replays (R423) -------------------------------------------------------

def replay(prepare):
    """A write made once (it raises the revision), then measured when replayed."""
    def case(ada, bob):
        path, body, client = prepare(ada, bob)
        key = new_key()
        assert assert_status(client.post(path, json=body, idempotency_key=key), 201)
        return lambda: assert_status(client.post(path, json=body, idempotency_key=key), 200)
    return case


def after_prep(prep, measured):
    def case(ada, bob):
        prep(ada, bob)
        return lambda: measured(ada, bob)
    return case


QUIET = {
    "patch_same_values": lambda ada, bob: lambda: assert_status(
        ada.patch("/reservations/OWN001", json={"table_id": "t_3", "party_size": 2}), 200),
    "patch_only_expected_revision": lambda ada, bob: lambda: assert_status(
        ada.patch("/reservations/OWN001", json={"expected_revision": 1}), 200),
    "patch_reversed_pair": lambda ada, bob: lambda: assert_status(
        ada.patch("/reservations/PAIR01", json={"table_ids": ["t_2", "t_1"]}), 200),
    "move_batch_of_no_ops": lambda ada, bob: lambda: assert_status(move(
        ada, {"reference": "OWN001", "party_size": 2}, {"reference": "OWN002", "table_id": "t_2"}), 201),
    "repeated_cancel": after_prep(lambda ada, bob: assert_status(ada.post("/reservations/OWN002/cancel"), 200),
                                  lambda ada, bob: assert_status(ada.post("/reservations/OWN002/cancel"), 200)),
    "create_conflict": lambda ada, bob: lambda: assert_error(create(bob, "t_3", "19:00", date=DATE), 409, "table_unavailable"),
    "create_invalid": lambda ada, bob: lambda: assert_error(create(bob, party=0), 422, "validation_failed"),
    "create_no_token": lambda ada, bob: lambda: assert_error(
        Api(bob.base_url).post("/reservations", idempotency_key=new_key(), json={}), 401, "unauthenticated"),
    "publication_forbidden": lambda ada, bob: lambda: assert_error(publish(bob), 403, "forbidden"),
    "publication_invalid": lambda ada, bob: lambda: assert_error(publish(ada, slot_minutes=0), 422, "validation_failed"),
    "patch_stale": lambda ada, bob: lambda: assert_error(
        ada.patch("/reservations/OWN001", json={"party_size": 3, "expected_revision": 5}), 409, "stale_revision"),
    "patch_conflict": lambda ada, bob: lambda: assert_error(
        ada.patch("/reservations/OWN002", json={"table_id": "t_3"}), 409, "table_unavailable"),
    "patch_other_owner": lambda ada, bob: lambda: assert_error(
        bob.patch("/reservations/OWN001", json={"party_size": 3}), 404, "not_found"),
    "failed_move_batch": lambda ada, bob: lambda: assert_error(move(
        ada, {"reference": "OWN001", "party_size": 3}, {"reference": "OWN002", "table_id": "t_3"}),
        409, "table_unavailable"),
    "failed_adoption": after_prep(lambda ada, bob: assert_status(create(bob, "t_3", "19:00", date=weeks(2)), 201),
                                  lambda ada, bob: assert_error(adopt(ada), 409, "table_unavailable")),
    "second_adoption": after_prep(lambda ada, bob: assert_status(adopt(ada, count=2), 201),
                                  lambda ada, bob: assert_error(adopt(ada, count=2), 409, "already_in_series")),
    "replayed_create": replay(lambda ada, bob: ("/reservations", {
        "restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": fx.local(weeks(1)), "party_size": 2}, bob)),
    "replayed_publication": replay(lambda ada, bob: ("/restaurants/r_anker/policies", fx.policy(weeks(2)), ada)),
    "replayed_move": replay(lambda ada, bob: ("/reservation-moves", {"moves": [
        {"reference": "OWN001", "party_size": 3}]}, ada)),
    "replayed_adoption": replay(lambda ada, bob: ("/series", {
        "anchor_reference": "OWN001", "count": 2, "interval_weeks": 1}, ada)),
}


@pytest.mark.parametrize("case", list(QUIET))
def test_no_ops_failures_and_replays_leave_it(world, base_url, case):
    """R423/Q5: a PATCH with the same values, only `expected_revision` or a reversed pair, a
    move batch of no-op items and a repeated cancel (no-ops); a refused create (409, 422,
    401), publication (403, 422), PATCH (stale, conflict, another owner's), move batch and
    adoption, and a second adoption (failures); replays of a create, a publication, a move and
    an adoption: none changes either restaurant's revision."""
    measured = QUIET[case](*world)
    before = revisions(base_url)
    measured()
    assert revisions(base_url) == before, case


# ---- export and import (Q24, J6) ------------------------------------------------------------------------

def test_a_stage_4_import_keeps_the_revisions_and_counting_goes_on(world, base_url):
    """Q24/J6: the schema-4 export carries each restaurant's revision; imported into another
    stage-4 service it re-exports equal, and the next create there raises it by one."""
    ada, bob = world
    for write in ("create_single", "policy_publication", "real_patch"):
        WRITES[write](ada, bob)
    body = exported(base_url)
    assert revisions(base_url) == {"r_anker": 3, "r_other": 0}
    second = url("TABLEKEEPER_SECOND_URL")
    with Api(second, timeout=RESET_TIMEOUT) as control:
        assert_status(control.post("/_test/import", json=body), 204)
    assert exported(second) == body
    with Api(second, token=bob.token) as bob2:
        assert_status(create(bob2, "t_1", "18:00"), 201)
    assert revisions(second) == {"r_anker": 4, "r_other": 0}


@pytest.mark.parametrize("source", ["TABLEKEEPER_STAGE3_URL", "TABLEKEEPER_STAGE2_URL", "TABLEKEEPER_STAGE1_URL"])
def test_an_earlier_stage_export_imports_at_revision_0(base_url, source):
    """Q5/Q24/J6: an export from the running stage-3, stage-2 or stage-1 service, after writes
    there, imports into stage 4 with every restaurant at revision 0."""
    with Api(url(source), timeout=RESET_TIMEOUT) as previous:
        assert_status(previous.post("/_test/reset", json=fx.fixture()), 204)
        token = previous.authenticate(fx.BOB["email"], fx.BOB["password"]).token
    with Api(url(source), token=token) as bob:
        assert_status(bob.post("/reservations", idempotency_key=new_key(), json={
            "restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": fx.local(DATE), "party_size": 2}), 201)
    body = exported(url(source))
    with Api(base_url, timeout=RESET_TIMEOUT) as control:
        assert_status(control.post("/_test/import", json=body), 204)
    assert revisions(base_url) == {"r_anker": 0}


@pytest.mark.parametrize("value", [-1, 1.5, "3", True, None, "missing"],
                         ids=["negative", "fraction", "string", "true", "null", "missing"])
def test_an_invalid_exported_revision_is_refused(world, base_url, value):
    """J6/D20: a restaurant revision that is not an integer of at least 0 (or is missing) makes
    the import 422 validation_failed, the destination unchanged; 0 is accepted."""
    body = exported(base_url)
    bad = copy.deepcopy(body)
    if value == "missing":
        del bad["state"]["restaurants"][0]["revision"]
    else:
        bad["state"]["restaurants"][0]["revision"] = value
    with Api(base_url, timeout=RESET_TIMEOUT) as control:
        assert_error(control.post("/_test/import", json=bad), 422, "validation_failed")
    assert exported(base_url) == body
    with Api(base_url, timeout=RESET_TIMEOUT) as control:
        assert_status(control.post("/_test/import", json=body), 204)


# ---- stage-4 replacements of the stage-3 checks superseded by Q24 --------------------------------------

_spec = importlib.util.spec_from_file_location(
    "stage3_import", pathlib.Path(__file__).resolve().parents[1] / "stage-3" / "test_s3_i5_import.py")
stage3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stage3)


def test_a_stage_4_export_restores_unchanged_in_another_stage_4(reset, api, base_url):
    """Q24 (replaces acceptance/stage-3 test_s3_i5_import.py::
    test_a_stage_3_export_restores_unchanged_in_another_stage_3): a stage-4 export, schema 4,
    imported into a fresh stage-4 re-exports equal; every list, reservation, history,
    decision, series, policy list and availability reads the same; every receipt replays
    200 with its original body there and changes nothing."""
    world = stage3.stage3_world(reset, api)
    second = url("TABLEKEEPER_SECOND_URL")
    body = exported(base_url)
    assert body["state"]["schema"] == 4
    with Api(second, timeout=RESET_TIMEOUT) as control:
        assert_status(control.post("/_test/import", json=body), 204)
    assert exported(second) == body

    def on(base):
        return lambda token: Api(base, token=token)

    assert stage3.views(on(second), world) == stage3.views(on(base_url), world)
    for name, sent in world.sent.items():
        with Api(second, token=sent.token) as client:
            assert assert_status(client.post(sent.path, json=sent.body, idempotency_key=sent.key), 200).json() \
                == sent.response, name
    assert exported(second) == body


@pytest.mark.parametrize("schema", [5, 0])
def test_an_export_of_an_unknown_schema_is_refused(world, base_url, schema):
    """Q24/D20 (replaces acceptance/stage-3 test_s3_i5_import.py::
    test_an_invalid_stage_3_export_is_refused_and_changes_nothing[schema_4]): with schema 4
    current, schema 5 (and 0) is unknown: 422 validation_failed, the destination unchanged."""
    body = exported(base_url)
    bad = copy.deepcopy(body)
    bad["state"]["schema"] = schema
    with Api(base_url, timeout=RESET_TIMEOUT) as control:
        assert_error(control.post("/_test/import", json=bad), 422, "validation_failed")
    assert exported(base_url) == body
