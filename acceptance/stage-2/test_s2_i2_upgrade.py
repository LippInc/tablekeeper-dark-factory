"""S2-I2 acceptance checks (verifier seat): the upgrade from stage 1, from the stage-2
specification ("Existing clients after an upgrade") with §7 and §10 of stage 1.

Needs the stage-1 service of the same checkout as `--previous-base-url` (recipe S2-2) and,
for the stage-2 round trip, a second stage-2 container in TABLEKEEPER_SECOND_URL. Each check
builds a world on the stage-1 service through its API -- seeded and signed-up accounts,
sessions, bookings created, PATCHed, moved and cancelled, a key whose request failed, and a
booking whose response its client never read -- exports it there and imports it into the
stage-2 service. R.., E.., D.. and G.. name the room plan's requirement lines and decisions.
"""
from __future__ import annotations

import copy
import json
import os
import socket
import time
import urllib.parse
from types import SimpleNamespace

import pytest

import fixtures as fx
from harness.http import RESET_TIMEOUT, Api, assert_error, assert_status, new_key

pytestmark = pytest.mark.stage(2)

DATE = fx.booking_date()
CY = {"email": "cy@example.com", "password": "cy's own secret", "display_name": "Cy"}
CAPACITY = {"t_1": 2, "t_2": 4, "t_3": 6}
DURATION = 90


def at(hhmm: str) -> str:
    return fx.local(DATE, hhmm)


def minutes(local: str) -> int:
    hour, minute = local[-5:].split(":")
    return int(hour) * 60 + int(minute)


def body(table_id: str, hhmm: str, party_size: int = 2) -> dict:
    return {"restaurant_id": "r_anker", "table_id": table_id, "starts_at_local": at(hhmm),
            "party_size": party_size}


def pair(table_ids: list[str], hhmm: str, party_size: int) -> dict:
    return {"restaurant_id": "r_anker", "table_ids": table_ids, "starts_at_local": at(hhmm),
            "party_size": party_size}


def with_table_ids(booking: dict) -> dict:
    """A stage-1 booking as the stage-2 service renders it (R260): `table_ids` added."""
    return {**booking, "table_ids": [booking["table_id"]]}


def mentions_table_ids(value) -> bool:
    if isinstance(value, dict):
        return "table_ids" in value or any(mentions_table_ids(v) for v in value.values())
    return isinstance(value, list) and any(mentions_table_ids(v) for v in value)


def lost_create(base_url: str, token: str, key: str, payload: dict) -> None:
    """Send a create and close the connection without reading the answer (R248): the
    service commits the booking, but its client never sees the response."""
    url = urllib.parse.urlsplit(base_url)
    raw = json.dumps(payload).encode()
    head = (f"POST /reservations HTTP/1.1\r\nHost: {url.hostname}\r\n"
            f"Authorization: Bearer {token}\r\nIdempotency-Key: {key}\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(raw)}\r\n"
            "Connection: close\r\n\r\n").encode()
    with socket.create_connection((url.hostname, url.port or 80), timeout=5) as sock:
        sock.sendall(head + raw)
        time.sleep(0.5)


def stage1_world(previous_api: Api) -> SimpleNamespace:
    """The stage-1 world, its reads and its export (taken after every write)."""
    url = previous_api.base_url
    clients: list[Api] = []

    def client(token: str | None = None) -> Api:
        clients.append(Api(url, token=token))
        return clients[-1]

    assert_status(previous_api.post("/_test/reset", json=fx.fixture(
        restaurants=[fx.restaurant(opening_hours=fx.all_week("12:00", "23:00"))],
        reservations=[
            {"id": "res_seed_a", "reference": "SEEDA1", "user_id": "u_ada", "restaurant_id": "r_anker",
             "table_id": "t_3", "starts_at_local": at("12:00"), "party_size": 2},
            {"id": "res_seed_b", "reference": "SEEDB1", "user_id": "u_bob", "restaurant_id": "r_anker",
             "table_id": "t_1", "starts_at_local": at("12:00"), "party_size": 2}])), 204)
    ada = client().authenticate(fx.ADA["email"], fx.ADA["password"])
    bob = client().authenticate(fx.BOB["email"], fx.BOB["password"])
    cy = client(assert_status(client().signup(CY["email"], CY["password"], CY["display_name"]),
                              201).json()["token"])
    sent: dict[str, SimpleNamespace] = {}

    def keyed(name: str, who: Api, path: str, payload: dict, status: int) -> dict:
        key = new_key()
        resp = assert_status(who.post(path, json=payload, idempotency_key=key), status)
        sent[name] = SimpleNamespace(token=who.token, path=path, body=payload, key=key,
                                     content=resp.content, response=resp.json())
        return resp.json()

    first = keyed("ada_create", ada, "/reservations", body("t_2", "19:00", 4), 201)
    assert "table_ids" not in first, "the previous service must be a stage-1 service"
    keyed("failed", ada, "/reservations", body("t_2", "19:30"), 409)
    later = keyed("ada_cancelled", ada, "/reservations", body("t_1", "20:00"), 201)
    keyed("bob_create", bob, "/reservations", body("t_3", "19:00", 5), 201)
    patched = keyed("cy_patched", cy, "/reservations", body("t_1", "17:00"), 201)
    assert_status(cy.patch(f"/reservations/{patched['reference']}", json={
        "table_id": "t_2", "starts_at_local": at("15:00")}), 200)
    keyed("ada_moves", ada, "/reservation-moves", {"moves": [
        {"reference": first["reference"], "starts_at_local": at("18:00")},
        {"reference": later["reference"], "starts_at_local": at("20:30")}]}, 201)
    assert_status(ada.post(f"/reservations/{later['reference']}/cancel"), 200)
    lost = SimpleNamespace(token=cy.token, key=new_key(), body=body("t_3", "21:00"))
    lost_create(url, lost.token, lost.key, lost.body)

    tokens = {"ada": ada.token, "bob": bob.token, "cy": cy.token}
    lists = {name: assert_status(client(token).get("/reservations"), 200).json()["reservations"]
             for name, token in tokens.items()}
    found = [b for b in lists["cy"] if b["starts_at_local"] == at("21:00")]
    assert len(found) == 1, "precondition: the create whose response was lost committed on stage 1"
    availability = {party: assert_status(client().get("/availability", params={
        "restaurant_id": "r_anker", "date": DATE, "party_size": party}), 200).json()["slots"]
        for party in (1, 3, 5)}
    exported = assert_status(previous_api.get("/_test/export"), 200).json()
    for made in clients:
        made.close()
    return SimpleNamespace(tokens=tokens, sent=sent, lists=lists, lost=lost, lost_booking=found[0],
                           owners={b["reference"]: name for name, bs in lists.items() for b in bs},
                           bookings={b["reference"]: b for bs in lists.values() for b in bs},
                           availability=availability, exported=exported)


@pytest.fixture
def upgraded(previous_api, base_url) -> SimpleNamespace:
    """The stage-1 world, imported into the stage-2 service (R245)."""
    world = stage1_world(previous_api)
    with Api(base_url, timeout=RESET_TIMEOUT) as control:
        assert_status(control.post("/_test/import", json=world.exported), 204)
    return world


def test_sessions_from_stage_1_stay_signed_in(upgraded, api):
    """R246/R138/D18: every stage-1 token -- a seeded user's login and a signed-up user's --
    still authenticates, and lists the same bookings, now with `table_ids`."""
    for name, token in upgraded.tokens.items():
        listed = assert_status(api(token).get("/reservations"), 200).json()["reservations"]
        assert listed == [with_table_ids(b) for b in upgraded.lists[name]], name


def test_stage_1_passwords_log_in_after_the_upgrade(upgraded, api):
    """R138: seeded and signed-up accounts log in with their stage-1 passwords; a wrong
    password is still refused."""
    for name, account in (("ada", fx.ADA), ("bob", fx.BOB), ("cy", CY)):
        token = assert_status(api().login(account["email"], account["password"]), 200).json()["token"]
        listed = assert_status(api(token).get("/reservations"), 200).json()["reservations"]
        assert listed == [with_table_ids(b) for b in upgraded.lists[name]], name
    assert api().login(fx.ADA["email"], "not the password").status_code == 401


def test_stage_1_references_read_the_same_with_table_ids(upgraded, api):
    """R247/R139/R260: each retained reference reads, for its owner, exactly as on stage 1
    (identity, status, times, created_at) plus `table_ids`; to anyone else it is 404."""
    assert len(upgraded.bookings) == 7
    for reference, booking in upgraded.bookings.items():
        owner = upgraded.owners[reference]
        read = assert_status(api(upgraded.tokens[owner]).get(f"/reservations/{reference}"), 200).json()
        assert read == with_table_ids(booking), reference
        stranger = next(name for name in upgraded.tokens if name != owner)
        assert_error(api(upgraded.tokens[stranger]).get(f"/reservations/{reference}"), 404, "not_found")


def test_every_stage_1_receipt_replays_its_original_body(upgraded, api):
    """R248/R273/R82/E8/D18/§7: every stage-1 receipt of /reservations and
    /reservation-moves replays 200 with its original stage-1 body (no `table_ids`), also
    with the body's keys in another order; the key with another body is 409
    idempotency_key_reuse; the replays change nothing."""
    replayed = [name for name in upgraded.sent if name != "failed"]
    bytes_equal = 0
    for name in replayed:
        sent = upgraded.sent[name]
        client = api(sent.token)
        resp = assert_status(client.post(sent.path, json=sent.body, idempotency_key=sent.key), 200)
        assert resp.json() == sent.response, name
        assert not mentions_table_ids(resp.json()), name
        bytes_equal += resp.content == sent.content
        reordered = json.dumps(dict(reversed(list(sent.body.items()))), indent=1).encode()
        again = assert_status(client.post(sent.path, content=reordered, idempotency_key=sent.key), 200)
        assert again.json() == sent.response, name
        other = {"restaurant_id": "r_anker"} if sent.path == "/reservations" else {"moves": []}
        assert_error(client.post(sent.path, json=other, idempotency_key=sent.key), 409,
                     "idempotency_key_reuse")
    print(f"stage-1 receipts replayed={len(replayed)} bytes_equal={bytes_equal}")
    for name, token in upgraded.tokens.items():
        listed = assert_status(api(token).get("/reservations"), 200).json()["reservations"]
        assert listed == [with_table_ids(b) for b in upgraded.lists[name]], name


def test_a_booking_whose_response_was_lost_is_recovered_after_the_upgrade(upgraded, api):
    """R248/R82: the create whose response its client never saw, retried after the import
    with the same key and body, answers 200 with the original stage-1 response -- the
    booking made on stage 1 -- and books nothing more."""
    lost = upgraded.lost
    client = api(lost.token)
    first = assert_status(client.post("/reservations", json=lost.body, idempotency_key=lost.key), 200)
    assert first.json() == upgraded.lost_booking
    receipt = [r for r in upgraded.exported["state"]["receipts"] if r.get("key") == lost.key]
    assert [r["response"] for r in receipt] == [first.json()]
    second = assert_status(client.post("/reservations", json=lost.body, idempotency_key=lost.key), 200)
    assert second.json() == first.json()
    listed = assert_status(client.get("/reservations"), 200).json()["reservations"]
    assert [b["reference"] for b in listed if b["starts_at_local"] == at("21:00")] == \
        [upgraded.lost_booking["reference"]]


def test_a_failed_key_is_reusable_after_the_upgrade(upgraded, api):
    """R139/§7: a key whose stage-1 request failed (409) is unused after the import: the
    same request is a first use (201), and then replays (200)."""
    sent = upgraded.sent["failed"]
    client = api(sent.token)
    created = assert_status(client.post(sent.path, json=sent.body, idempotency_key=sent.key), 201).json()
    assert created["table_ids"] == ["t_2"] and created["starts_at_local"] == at("19:30")
    assert assert_status(client.post(sent.path, json=sent.body, idempotency_key=sent.key), 200).json() == created


def test_new_references_do_not_collide_with_imported_ones(upgraded, api):
    """R138/R139: bookings made after the import get new references; every imported
    reference still reads its own booking."""
    bob = api(upgraded.tokens["bob"])
    made = [assert_status(bob.post("/reservations", json=body(table, hhmm), idempotency_key=new_key()),
                          201).json()["reference"]
            for table, hhmm in (("t_1", "14:00"), ("t_1", "16:00"), ("t_1", "18:00"), ("t_1", "21:30"),
                                ("t_2", "12:00"), ("t_2", "21:00"), ("t_3", "14:00"), ("t_3", "16:00"))]
    assert len(set(made)) == len(made)
    assert not set(made) & set(upgraded.bookings)
    for reference, booking in upgraded.bookings.items():
        owner = upgraded.tokens[upgraded.owners[reference]]
        assert assert_status(api(owner).get(f"/reservations/{reference}"), 200).json() == \
            with_table_ids(booking)


def test_imported_bookings_hold_their_tables(upgraded, api, anon):
    """R245/R7/R138/R90/R257: after the import, availability equals the reference built
    from the stage-1 bookings and stage 1's own answer, with the singles as the options;
    a create on each confirmed imported booking's table at an overlapping time is 409, and
    on the cancelled one's slot 201."""
    confirmed = [b for b in upgraded.bookings.values() if b["status"] == "confirmed"]
    cancelled = [b for b in upgraded.bookings.values() if b["status"] == "cancelled"]
    assert len(confirmed) == 6 and len(cancelled) == 1
    for party, before in upgraded.availability.items():
        slots = assert_status(anon.get("/availability", params={
            "restaurant_id": "r_anker", "date": DATE, "party_size": party}), 200).json()["slots"]
        assert [s["available_table_ids"] for s in slots] == [s["available_table_ids"] for s in before]
        for slot in slots:
            start = minutes(slot["starts_at_local"])
            free = [t for t, cap in CAPACITY.items() if cap >= party and all(
                abs(start - minutes(b["starts_at_local"])) >= DURATION
                for b in confirmed if b["table_id"] == t)]
            assert slot["available_table_ids"] == free, (party, slot["starts_at_local"])
            assert slot["available_options"] == [{"table_ids": [t], "capacity": CAPACITY[t]} for t in free]
    other = api().authenticate(fx.BOB["email"], fx.BOB["password"])
    for booking in confirmed:
        later = booking["starts_at_local"][:-5] + "{:02d}:{:02d}".format(*divmod(
            minutes(booking["starts_at_local"]) + 30, 60))
        resp = other.post("/reservations", idempotency_key=new_key(), json={
            **body(booking["table_id"], "12:00"), "starts_at_local": later})
        assert_error(resp, 409, "table_unavailable")
    for booking in cancelled:
        assert_status(other.post("/reservations", idempotency_key=new_key(), json={
            **body(booking["table_id"], "12:00"), "starts_at_local": booking["starts_at_local"]}), 201)


# ---- a stage-2 export into another stage-2 container ---------------------------------------------

@pytest.fixture
def second_url() -> str:
    url = os.environ.get("TABLEKEEPER_SECOND_URL")
    assert url, "set TABLEKEEPER_SECOND_URL to a second container of the stage-2 image"
    return url.rstrip("/")


def test_a_stage_2_export_with_pairs_restores_unchanged_in_another_container(reset, api, base_url,
                                                                           second_url):
    """R133/R138/R139/G5: a stage-2 export holding pairs (seeded reversed, created, moved,
    cancelled) and their receipts, imported into a second stage-2 container that holds data
    of its own, reads, replays and occupies the same there, and exports unchanged."""
    reset(fx.fixture(restaurants=[{**fx.restaurant(opening_hours=fx.all_week("12:00", "23:00")),
                                   "combinable": [["t_1", "t_2"], ["t_3", "t_2"]]}], reservations=[
        {"id": "res_p", "reference": "SEEDP1", "user_id": "u_ada", "restaurant_id": "r_anker",
         "table_ids": ["t_2", "t_1"], "starts_at_local": at("12:00"), "party_size": 5},
        {"id": "res_c", "reference": "SEEDC1", "user_id": "u_bob", "restaurant_id": "r_anker",
         "table_ids": ["t_3", "t_2"], "starts_at_local": at("12:30"), "party_size": 8, "status": "cancelled"}]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    receipts = []

    def keyed(path: str, payload: dict) -> dict:
        key = new_key()
        response = assert_status(ada.post(path, json=payload, idempotency_key=key), 201).json()
        receipts.append((path, payload, key, response))
        return response

    moved = keyed("/reservations", pair(["t_2", "t_1"], "16:00", 5))
    gone = keyed("/reservations", pair(["t_2", "t_3"], "20:30", 8))
    keyed("/reservation-moves", {"moves": [{"reference": moved["reference"], "starts_at_local": at("15:00")}]})
    assert_status(ada.post(f"/reservations/{gone['reference']}/cancel"), 200)
    listed = assert_status(ada.get("/reservations"), 200).json()
    with Api(base_url, timeout=RESET_TIMEOUT) as source, Api(second_url, timeout=RESET_TIMEOUT) as target:
        exported = assert_status(source.get("/_test/export"), 200).json()
        assert_status(target.post("/_test/reset", json=fx.fixture()), 204)
        assert_status(target.post("/_test/import", json=exported), 204)
        assert assert_status(target.get("/_test/export"), 200).json() == exported
    there = Api(second_url, token=ada.token)
    assert assert_status(there.get("/reservations"), 200).json() == listed
    assert {b["reference"]: b["table_ids"] for b in listed["reservations"]} == {
        "SEEDP1": ["t_1", "t_2"], moved["reference"]: ["t_1", "t_2"], gone["reference"]: ["t_3", "t_2"]}
    for path, payload, key, response in receipts:
        assert assert_status(there.post(path, json=payload, idempotency_key=key), 200).json() == response
    for party in (1, 5):
        params = {"restaurant_id": "r_anker", "date": DATE, "party_size": party}
        assert there.get("/availability", params=params).json() == ada.get("/availability", params=params).json()
    for table, hhmm in (("t_1", "12:30"), ("t_2", "15:30"), ("t_1", "14:00")):
        assert_error(there.post("/reservations", idempotency_key=new_key(), json=body(table, hhmm)),
                     409, "table_unavailable")
    assert_status(there.post("/reservations", idempotency_key=new_key(), json=body("t_3", "20:30")), 201)
    there.close()


# ---- invalid imports ---------------------------------------------------------------------------------

def _set(path: tuple, value):
    def edit(export: dict) -> None:
        target = export
        for step in path[:-1]:
            target = target[step]
        if value is _DELETE:
            del target[path[-1]]
        else:
            target[path[-1]] = value
    return edit


_DELETE = object()
RESERVATION = ("state", "reservations", 0)
INVALID = {
    "schema_0": _set(("state", "schema"), 0),
    "schema_3": _set(("state", "schema"), 3),
    "schema_string": _set(("state", "schema"), "1"),
    "schema_true": _set(("state", "schema"), True),
    "schema_missing": _set(("state", "schema"), _DELETE),
    "reservation_without_table_id": _set(RESERVATION + ("table_id",), _DELETE),
    "table_id_wrong_type": _set(RESERVATION + ("table_id",), 5),
    "table_id_unknown": _set(RESERVATION + ("table_id",), "t_9"),
    "reservations_not_a_list": _set(("state", "reservations"), "none"),
    "reservation_not_an_object": _set(RESERVATION, "SEEDA1"),
    "restaurant_not_an_object": _set(("state", "restaurants", 0), "r_anker"),
    "wrong_track": _set(("track",), "pocketful"),
    "format_version_2": _set(("format_version",), 2),
    "format_version_string": _set(("format_version",), "1"),
}


@pytest.mark.parametrize("name", list(INVALID))
def test_an_invalid_stage_1_export_is_refused_and_changes_nothing(upgraded, api, base_url, name):
    """R135/D20: an invalid stage-1 export -- an unknown or mistyped schema, a reservation
    without a table, a wrong-typed or unknown table, a malformed list or record, a wrong
    track or version -- is 422 validation_failed and the destination is unchanged."""
    broken = copy.deepcopy(upgraded.exported)
    INVALID[name](broken)
    with Api(base_url, timeout=RESET_TIMEOUT) as control:
        before = assert_status(control.get("/_test/export"), 200).json()
        assert_error(control.post("/_test/import", json=broken), 422, "validation_failed")
        assert assert_status(control.get("/_test/export"), 200).json() == before
    assert_status(api(upgraded.tokens["ada"]).get("/reservations"), 200)


def test_a_stage_1_reservation_without_table_id_is_invalid_whatever_else_it_carries(upgraded, base_url):
    """R135/E10: in schema 1 `table_ids` is an unknown field, so a reservation that carries
    it instead of `table_id` has no table: 422 validation_failed, destination unchanged."""
    broken = copy.deepcopy(upgraded.exported)
    record = broken["state"]["reservations"][0]
    record["table_ids"] = [record.pop("table_id")]
    with Api(base_url, timeout=RESET_TIMEOUT) as control:
        before = assert_status(control.get("/_test/export"), 200).json()
        assert_error(control.post("/_test/import", json=broken), 422, "validation_failed")
        assert assert_status(control.get("/_test/export"), 200).json() == before


def test_an_unparseable_import_is_400_and_changes_nothing(upgraded, base_url):
    """R135/D20: only a body that is not JSON is 400; a JSON array is 422."""
    with Api(base_url, timeout=RESET_TIMEOUT) as control:
        before = assert_status(control.get("/_test/export"), 200).json()
        assert_error(control.post("/_test/import", content=b'{"track": "tablekeeper",'), 400,
                     "malformed_request")
        assert_error(control.post("/_test/import", json=[upgraded.exported]), 422, "validation_failed")
        assert assert_status(control.get("/_test/export"), 200).json() == before


def test_a_stray_table_ids_field_in_a_stage_1_reservation_is_ignored(upgraded, api, base_url):
    """E10: a schema-1 reservation carrying an extra `table_ids` field is valid; the field
    is ignored and the booking holds its `table_id`."""
    edited = copy.deepcopy(upgraded.exported)
    record = next(r for r in edited["state"]["reservations"] if r["reference"] == "SEEDA1")
    record["table_ids"] = ["t_1", "t_2"]
    with Api(base_url, timeout=RESET_TIMEOUT) as control:
        assert_status(control.post("/_test/import", json=edited), 204)
    read = assert_status(api(upgraded.tokens["ada"]).get("/reservations/SEEDA1"), 200).json()
    assert read == with_table_ids(upgraded.bookings["SEEDA1"])
    assert read["table_ids"] == ["t_3"]
