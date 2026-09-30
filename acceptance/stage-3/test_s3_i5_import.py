"""S3-I5 acceptance checks (verifier seat): export and import across stages 1-3, from the
stage-3 specification (R361: "A stage-3 service must accept exports produced by the same
team's stage-1 or stage-2 service. Adoption must work on reservations imported this way.
Existing confirmation links, sessions and original booking retries remain valid.") with
stage-1 §10 and the plans' H6, P4, D18, D20, E8, E10 and the critic's B2.

Uses the stage-1 service (TABLEKEEPER_STAGE1_URL), the stage-2 service
(TABLEKEEPER_STAGE2_URL) and a second stage-3 service (TABLEKEEPER_SECOND_URL) of the same
checkout, and resets each: run it alone against other files that reset them.
"""
from __future__ import annotations

import copy
import datetime as dt
import importlib.util
import json
import os
import pathlib
import time
from types import SimpleNamespace

import pytest

import fixtures as fx
from harness.http import RESET_TIMEOUT, Api, assert_error, assert_status, new_key

pytestmark = pytest.mark.stage(3)

_spec = importlib.util.spec_from_file_location(
    "stage2_upgrade", pathlib.Path(__file__).resolve().parents[1] / "stage-2" / "test_s2_i2_upgrade.py")
stage2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stage2)

DATE = fx.booking_date()
NOON_POLICY_0 = {"policy_version": 0, "slot_minutes": 30, "reservation_duration_minutes": 90,
                 "cancellation_cutoff_minutes": 120, "opening_hours": fx.all_week("12:00", "23:00"),
                 "capacities": {"t_1": 2, "t_2": 4, "t_3": 6}}


def url(name: str) -> str:
    value = os.environ.get(name)
    assert value, f"set {name} to the service of the same checkout"
    return value.rstrip("/")


def weeks(n: int) -> str:
    return (dt.date.fromisoformat(DATE) + dt.timedelta(weeks=n)).isoformat()


def export(base: str) -> dict:
    with Api(base, timeout=RESET_TIMEOUT) as control:
        return assert_status(control.get("/_test/export"), 200).json()


def import_into(base: str, body) -> None:
    with Api(base, timeout=RESET_TIMEOUT) as control:
        assert_status(control.post("/_test/import", json=body), 204)


def instant(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


def stage3_shape(booking: dict, terms: dict) -> dict:
    return {**stage2.with_table_ids(booking), "revision": 1, "accepted_terms": terms}


def created_entry_matches(entry: dict, booking: dict, terms: dict) -> bool:
    """One `created` entry at the booking's creation, holding its current fields (H6, P4)."""
    tables = booking.get("table_ids") or [booking["table_id"]]
    first = ({"field": "table_id", "from": None, "to": tables[0]} if len(tables) == 1
             else {"field": "table_ids", "from": None, "to": tables})
    return (entry["seq"], entry["event"], entry["revision"], entry["accepted_terms"]) == (1, "created", 1, terms) \
        and instant(entry["at"]) == instant(booking["created_at"]) \
        and entry["changes"] == [first, {"field": "starts_at_local", "from": None, "to": booking["starts_at_local"]},
                                 {"field": "party_size", "from": None, "to": booking["party_size"]}]


def slots_without_explain(client, date, party) -> list:
    return assert_status(client.get("/availability", params={"restaurant_id": "r_anker", "date": date,
                                                             "party_size": party}), 200).json()["slots"]


def explained_ids(client, date, party) -> list:
    slots = assert_status(client.get("/availability", params={"restaurant_id": "r_anker", "date": date,
                                                              "party_size": party, "explain": "true"}), 200).json()["slots"]
    assert all([e["table_id"] for e in s["explain"] if e["available"]] == s["available_table_ids"] for s in slots)
    return [(s["starts_at_local"], s["available_table_ids"]) for s in slots]


# ---- the stage-2 world ----------------------------------------------------------------------------

def stage2_world(base: str) -> SimpleNamespace:
    """A running stage-2 service's world: three accounts (one signed up), single and pair
    bookings, a changed one, a cancelled one, keyed creates and a move, a create whose answer
    was lost, and its export taken after every write."""
    clients = []

    def client(token=None):
        clients.append(Api(base, token=token))
        return clients[-1]

    restaurant = {**fx.restaurant(opening_hours=fx.all_week("12:00", "23:00")), "combinable": [["t_1", "t_2"]]}
    with Api(base, timeout=RESET_TIMEOUT) as control:
        assert_status(control.post("/_test/reset", json=fx.fixture(restaurants=[restaurant], reservations=[
            {"id": "res_seed21", "reference": "SEED21", "user_id": "u_ada", "restaurant_id": "r_anker",
             "table_id": "t_3", "starts_at_local": stage2.at("12:00"), "party_size": 2}])), 204)
    ada = client().authenticate(fx.ADA["email"], fx.ADA["password"])
    bob = client().authenticate(fx.BOB["email"], fx.BOB["password"])
    cy = client(assert_status(client().signup(stage2.CY["email"], stage2.CY["password"], stage2.CY["display_name"]),
                              201).json()["token"])
    sent = {}

    def keyed(name, who, path, payload, status):
        key = new_key()
        resp = assert_status(who.post(path, json=payload, idempotency_key=key), status)
        sent[name] = SimpleNamespace(token=who.token, path=path, body=payload, key=key, response=resp.json())
        return resp.json()

    single = keyed("ada_single", ada, "/reservations", stage2.body("t_2", "19:00", 4), 201)
    assert "table_ids" in single and "revision" not in single, "the stage-2 service must be a stage-2 service"
    keyed("ada_pair", ada, "/reservations", stage2.pair(["t_2", "t_1"], "21:00", 5), 201)
    keyed("failed", ada, "/reservations", stage2.body("t_2", "19:30"), 409)
    later = keyed("ada_cancelled", ada, "/reservations", stage2.body("t_3", "19:00"), 201)
    assert_status(ada.post(f"/reservations/{later['reference']}/cancel"), 200)
    keyed("bob_create", bob, "/reservations", stage2.body("t_3", "17:00", 5), 201)
    patched = keyed("cy_patched", cy, "/reservations", stage2.body("t_1", "15:00"), 201)
    assert_status(cy.patch(f"/reservations/{patched['reference']}", json={
        "table_id": "t_3", "starts_at_local": stage2.at("13:30")}), 200)
    keyed("ada_moves", ada, "/reservation-moves", {"moves": [
        {"reference": single["reference"], "starts_at_local": stage2.at("18:00")}]}, 201)
    lost = SimpleNamespace(token=cy.token, key=new_key(), body=stage2.body("t_1", "17:00"))
    stage2.lost_create(base, lost.token, lost.key, lost.body)
    tokens = {"ada": ada.token, "bob": bob.token, "cy": cy.token}
    lists = {name: assert_status(client(token).get("/reservations"), 200).json()["reservations"]
             for name, token in tokens.items()}
    [lost_booking] = [b for b in lists["cy"] if b["starts_at_local"] == stage2.at("17:00")]
    availability = {party: slots_without_explain(client(), DATE, party) for party in (1, 3, 5)}
    exported = export(base)
    for made in clients:
        made.close()
    return SimpleNamespace(tokens=tokens, sent=sent, lists=lists, lost=lost, lost_booking=lost_booking,
                           availability=availability, exported=exported,
                           bookings={b["reference"]: (name, b) for name, bs in lists.items() for b in bs})


@pytest.fixture
def from_stage_2(base_url):
    world = stage2_world(url("TABLEKEEPER_STAGE2_URL"))
    time.sleep(1.1)  # an import-time stamp must differ from every created_at, shown to the second
    import_into(base_url, world.exported)
    return world


def test_a_stage_2_export_keeps_sessions_logins_and_references(from_stage_2, api):
    """R361/R246/H6: every stage-2 token lists the same bookings, now at revision 1 under
    policy 0; stage-2 passwords log in; each reference reads the same for its owner."""
    world = from_stage_2
    for name, token in world.tokens.items():
        assert assert_status(api(token).get("/reservations"), 200).json()["reservations"] == \
            [{**b, "revision": 1, "accepted_terms": NOON_POLICY_0} for b in world.lists[name]], name
    for name, account in (("ada", fx.ADA), ("bob", fx.BOB), ("cy", stage2.CY)):
        token = assert_status(api().login(account["email"], account["password"]), 200).json()["token"]
        assert len(assert_status(api(token).get("/reservations"), 200).json()["reservations"]) == len(world.lists[name])
    for reference, (name, booking) in world.bookings.items():
        read = assert_status(api(world.tokens[name]).get(f"/reservations/{reference}"), 200).json()
        assert read == {**booking, "revision": 1, "accepted_terms": NOON_POLICY_0}, reference


def test_stage_2_bookings_have_one_created_entry_at_their_creation(from_stage_2, api):
    """H6/P4: every imported booking, confirmed or cancelled, single or pair, changed or not,
    has one `created` entry at its `created_at` holding its current fields, revision 1, policy
    0; its decision agrees."""
    world = from_stage_2
    for reference, (name, booking) in world.bookings.items():
        owner = api(world.tokens[name])
        [entry] = assert_status(owner.get(f"/reservations/{reference}/history"), 200).json()["entries"]
        assert created_entry_matches(entry, booking, NOON_POLICY_0), (reference, entry)
        assert assert_status(owner.get(f"/reservations/{reference}/decision"), 200).json() == \
            {"reference": reference, "revision": 1, "accepted_terms": NOON_POLICY_0}


def test_stage_2_receipts_replay_verbatim(from_stage_2, api, base_url):
    """R361/§7/E8: every stage-2 receipt, the lost create's included, replays 200 with its
    stage-2 body (no revision or accepted_terms); nothing changes."""
    world = from_stage_2
    before = export(base_url)
    for name, sent in world.sent.items():
        if name == "failed":
            continue
        replay = assert_status(api(sent.token).post(sent.path, json=sent.body, idempotency_key=sent.key), 200).json()
        assert replay == sent.response, name
        assert not {"revision", "accepted_terms"} & set(json.dumps(replay).split('"')), name
    lost = assert_status(api(world.lost.token).post("/reservations", json=world.lost.body,
                                                    idempotency_key=world.lost.key), 200).json()
    assert lost == world.lost_booking
    assert export(base_url) == before


def test_stage_2_occupancy_and_adoption(from_stage_2, api, anon):
    """R361/R354: imported bookings hold their tables exactly as on stage 2 (availability with
    and without explain equals the stage-2 answer), and an imported booking can be adopted as a
    series anchor; occurrence 0 is its read."""
    world = from_stage_2
    for party, before in world.availability.items():
        assert slots_without_explain(anon, DATE, party) == before, party
        assert explained_ids(anon, DATE, party) == [(s["starts_at_local"], s["available_table_ids"]) for s in before]
    ada = api(world.tokens["ada"])
    anchor = world.sent["ada_single"].response["reference"]
    answer = assert_status(ada.post("/series", idempotency_key=new_key(), json={
        "anchor_reference": anchor, "count": 2, "interval_weeks": 1}), 201).json()
    assert answer["occurrences"][0]["reservation"] == assert_status(ada.get(f"/reservations/{anchor}"), 200).json()


# ---- the stage-1 world ------------------------------------------------------------------------------

@pytest.fixture
def from_stage_1(base_url):
    with Api(url("TABLEKEEPER_STAGE1_URL"), timeout=RESET_TIMEOUT) as stage1:
        world = stage2.stage1_world(stage1)
    time.sleep(1.1)  # as above
    import_into(base_url, world.exported)
    return world


def test_stage_1_bookings_have_history_occupancy_and_can_be_adopted(from_stage_1, api, anon):
    """R361/H6/P4: every imported stage-1 booking has one `created` entry at its `created_at`;
    occupancy equals the stage-1 answer; the lost create's key replays its booking; an imported
    booking is adopted as a series anchor."""
    world = from_stage_1
    for reference, booking in world.bookings.items():
        owner = api(world.tokens[world.owners[reference]])
        [entry] = assert_status(owner.get(f"/reservations/{reference}/history"), 200).json()["entries"]
        assert created_entry_matches(entry, booking, NOON_POLICY_0), (reference, entry)
    for party, before in world.availability.items():
        assert [(s["starts_at_local"], s["available_table_ids"]) for s in slots_without_explain(anon, DATE, party)] == \
            [(s["starts_at_local"], s["available_table_ids"]) for s in before], party
        assert explained_ids(anon, DATE, party) == [(s["starts_at_local"], s["available_table_ids"]) for s in before]
    lost = assert_status(api(world.lost.token).post("/reservations", json=world.lost.body,
                                                    idempotency_key=world.lost.key), 200).json()
    assert lost == world.lost_booking
    ada = api(world.tokens["ada"])
    anchor = world.sent["ada_create"].response["reference"]
    answer = assert_status(ada.post("/series", idempotency_key=new_key(), json={
        "anchor_reference": anchor, "count": 2, "interval_weeks": 1}), 201).json()
    assert answer["occurrences"][0]["reservation"] == stage3_shape(world.bookings[anchor], NOON_POLICY_0)


# ---- stage 3 to stage 3 ----------------------------------------------------------------------------

def stage3_world(reset, api) -> SimpleNamespace:
    """A stage-3 world with everything stage 3 adds: managers, a published policy, revisions,
    terms, histories, a series with an exception, a pair, a cancelled booking, and receipts of a
    create, a pair create, a policy, an adoption and a move."""
    reset(fx.fixture(restaurants=[{**fx.managed_restaurant(), "combinable": [["t_1", "t_2"]]}], reservations=[
        {"id": "res_seed31", "reference": "SEED31", "user_id": "u_bob", "restaurant_id": "r_anker",
         "table_id": "t_3", "starts_at_local": fx.local(DATE, "18:00"), "party_size": 2}]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    bob = api().authenticate(fx.BOB["email"], fx.BOB["password"])
    sent = {}

    def keyed(name, who, path, payload):
        key = new_key()
        response = assert_status(who.post(path, json=payload, idempotency_key=key), 201).json()
        sent[name] = SimpleNamespace(token=who.token, path=path, body=payload, key=key, response=response)
        return response

    single = keyed("create", ada, "/reservations", {"restaurant_id": "r_anker", "table_id": "t_2",
                                                     "starts_at_local": fx.local(DATE), "party_size": 4})
    pair = keyed("pair", ada, "/reservations", {"restaurant_id": "r_anker", "table_ids": ["t_2", "t_1"],
                                                 "starts_at_local": fx.local(DATE, "21:00"), "party_size": 5})
    keyed("policy", ada, "/restaurants/r_anker/policies", fx.policy(weeks(1), reservation_duration_minutes=45))
    assert_status(ada.patch(f"/reservations/{single['reference']}", json={"party_size": 3}), 200)
    series = keyed("adoption", ada, "/series", {"anchor_reference": single["reference"], "count": 3,
                                                "interval_weeks": 1})
    keyed("move", ada, "/reservation-moves", {"moves": [
        {"reference": series["occurrences"][1]["reference"], "starts_at_local": fx.local(weeks(1), "20:00")}]})
    assert_status(ada.post(f"/reservations/{pair['reference']}/cancel"), 200)
    keyed("bob_create", bob, "/reservations", {"restaurant_id": "r_anker", "table_id": "t_3",
                                                "starts_at_local": fx.local(DATE, "20:30"), "party_size": 2})
    return SimpleNamespace(ada=ada, bob=bob, sent=sent, series_id=series["series_id"])


def views(client_for, world) -> dict:
    """Everything a diner or anyone can read of the world."""
    found = {"policies": assert_status(client_for(None).get("/restaurants/r_anker/policies"), 200).json(),
             "series": assert_status(client_for(world.ada.token).get(f"/series/{world.series_id}"), 200).json()}
    for who in (world.ada, world.bob):
        client = client_for(who.token)
        listed = assert_status(client.get("/reservations"), 200).json()["reservations"]
        found[who.token] = listed
        for booking in listed:
            ref = booking["reference"]
            found[ref] = [assert_status(client.get(f"/reservations/{ref}{part}"), 200).json()
                          for part in ("", "/history", "/decision")]
    for date in (DATE, weeks(1)):
        found[date] = explained_ids(client_for(None), date, 2)
    return found


def test_a_stage_3_export_restores_unchanged_in_another_stage_3(reset, api, base_url):
    """§10/H6/D18: a stage-3 export imported into a fresh stage-3 service re-exports equal;
    every list, reservation, history, decision, series, policy list and availability reads the
    same; every receipt (create, pair, policy, adoption, move) replays 200 with its original
    body there and changes nothing."""
    world = stage3_world(reset, api)
    second = url("TABLEKEEPER_SECOND_URL")
    exported = export(base_url)
    assert exported["state"]["schema"] == 3
    import_into(second, exported)
    assert export(second) == exported

    def on(base):
        return lambda token: Api(base, token=token)

    assert views(on(second), world) == views(on(base_url), world)
    for name, sent in world.sent.items():
        with Api(second, token=sent.token) as client:
            assert assert_status(client.post(sent.path, json=sent.body, idempotency_key=sent.key), 200).json() \
                == sent.response, name
    assert export(second) == exported


# ---- invalid imports (D20) -------------------------------------------------------------------------------

def edit(path, value):
    def apply(body):
        target = body
        for step in path[:-1]:
            target = target[step]
        if value is _DELETE:
            del target[path[-1]]
        else:
            target[path[-1]] = value
    return apply


_DELETE = object()
FIRST = ("state", "reservations", 0)
INVALID = {
    "not_an_object": lambda body: None,
    "wrong_track": edit(("track",), "other"),
    "schema_4": edit(("state", "schema"), 4),
    "schema_0": edit(("state", "schema"), 0),
    "history_seq_gap": edit((*FIRST, "history", 0, "seq"), 2),
    "history_bad_event": edit((*FIRST, "history", 0, "event"), "moved"),
    "history_missing": edit((*FIRST, "history"), _DELETE),
    "history_empty": edit((*FIRST, "history"), []),
    "policy_version_unknown": edit((*FIRST, "policy_version"), 9),
    "series_unknown_reference": edit(("state", "series", 0, "occurrences", 1, "reference"), "NOPE0000"),
    "series_one_occurrence": lambda body: body["state"]["series"][0].__setitem__(
        "occurrences", body["state"]["series"][0]["occurrences"][:1]),
    "policy_incomplete": edit(("state", "restaurants", 0, "policies", 0, "capacities"), _DELETE),
    "revision_zero": edit((*FIRST, "revision"), 0),
}


@pytest.mark.parametrize("case", list(INVALID))
def test_an_invalid_stage_3_export_is_refused_and_changes_nothing(reset, api, base_url, case):
    """D20/§10: a non-object body, a wrong track or schema, a broken history (a seq gap, an
    unknown event, none at all), an unknown policy version, a broken series, an incomplete
    published policy or revision 0 is 422 validation_failed and leaves the destination as it
    was."""
    world = stage3_world(reset, api)
    exported = export(base_url)
    second = url("TABLEKEEPER_SECOND_URL")
    import_into(second, exported)
    body = copy.deepcopy(exported)
    body = [] if case == "not_an_object" else body
    if case != "not_an_object":
        INVALID[case](body)
    with Api(second, timeout=RESET_TIMEOUT) as control:
        assert_error(control.post("/_test/import", json=body), 422, "validation_failed")
    assert export(second) == exported
    assert world.series_id


def test_a_stage_1_reservation_with_table_ids_but_no_table_id_is_refused(base_url):
    """E10/D20: a schema-1 reservation carrying `table_ids` but no `table_id` is 422 and the
    destination keeps its state; an unparseable body is 400 and changes nothing."""
    with Api(url("TABLEKEEPER_STAGE1_URL"), timeout=RESET_TIMEOUT) as stage1:
        assert_status(stage1.post("/_test/reset", json=fx.fixture(reservations=[
            {"id": "res_one", "reference": "ONE001", "user_id": "u_ada", "restaurant_id": "r_anker",
             "table_id": "t_2", "starts_at_local": fx.local(DATE), "party_size": 2}])), 204)
        exported = assert_status(stage1.get("/_test/export"), 200).json()
    import_into(base_url, exported)
    before = export(base_url)
    body = copy.deepcopy(exported)
    record = body["state"]["reservations"][0]
    record["table_ids"] = [record.pop("table_id")]
    with Api(base_url, timeout=RESET_TIMEOUT) as control:
        assert_error(control.post("/_test/import", json=body), 422, "validation_failed")
        assert_error(control.post("/_test/import", content=b'{"track": "tablekeeper", '), 400, "malformed_request")
    assert export(base_url) == before


# ---- mixed durations (B2) ----------------------------------------------------------------------------

def test_a_restore_keeps_each_bookings_own_duration(reset, api, base_url):
    """B2/H1/H6: a schema-3 export holding a 90-minute booking (policy 0) and 30-minute ones (a
    later policy) restores into another stage-3 service with each booking's own duration:
    availability with and without explain equals the reference; a create just inside each
    booking's end is 409 and just after it 201."""
    reset(fx.fixture(restaurants=[fx.managed_restaurant()]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    assert_status(ada.post("/restaurants/r_anker/policies", idempotency_key=new_key(),
                           json=fx.policy(weeks(1), reservation_duration_minutes=30)), 201)
    booked = {DATE: ("t_2", 19 * 60, 90), weeks(1): ("t_2", 19 * 60, 30)}
    for date in booked:
        assert_status(ada.post("/reservations", idempotency_key=new_key(), json={
            "restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": fx.local(date), "party_size": 2}), 201)
    second = url("TABLEKEEPER_SECOND_URL")
    import_into(second, export(base_url))
    with Api(second) as anon, Api(second).authenticate(fx.BOB["email"], fx.BOB["password"]) as bob:
        for date, (table, start, length) in booked.items():
            duration = 90 if date == DATE else 30
            plain = slots_without_explain(anon, date, 1)
            expected = [(s["starts_at_local"], [t for t in ("t_1", "t_2", "t_3") if t != table or
                                                (int(s["starts_at_local"][11:13]) * 60 + int(s["starts_at_local"][14:16])
                                                 + duration <= start) or
                                                int(s["starts_at_local"][11:13]) * 60 + int(s["starts_at_local"][14:16])
                                                >= start + length]) for s in plain]
            assert [(s["starts_at_local"], s["available_table_ids"]) for s in plain] == expected, date
            assert explained_ids(anon, date, 1) == expected, date
            end = start + length
            inside, after = f"{(end - 30) // 60:02d}:{(end - 30) % 60:02d}", f"{end // 60:02d}:{end % 60:02d}"
            assert_error(bob.post("/reservations", idempotency_key=new_key(), json={
                "restaurant_id": "r_anker", "table_id": table, "starts_at_local": fx.local(date, inside),
                "party_size": 1}), 409, "table_unavailable")
            assert_status(bob.post("/reservations", idempotency_key=new_key(), json={
                "restaurant_id": "r_anker", "table_id": table, "starts_at_local": fx.local(date, after),
                "party_size": 1}), 201)
