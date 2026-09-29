"""S1-I5 acceptance checks (verifier seat), written from the stage-1 specification.

GET /_test/export and POST /_test/import (§10) on one service: export → reset to other
data → import. The state format is opaque, so every check observes the service through
its API. R.. and D.. name the room plan's requirement lines and decisions. Importing into
a second container is test_s1_i5_two_containers.py; the snapshot under concurrent writes
and the time limits are test_s1_i5_snapshot.py (run alone).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import fixtures as fx
from harness.http import RESET_TIMEOUT, assert_error, assert_status, error_code, new_key

pytestmark = pytest.mark.stage(1)

DATE = fx.booking_date()
CAROL = {"email": "carol@example.com", "password": "carol's secret", "display_name": "Carol"}
DAN = {"id": "u_dan", "email": "dan@example.com", "password": "dan's secret", "display_name": "Dan"}


def create_body(table_id: str, at: str, party_size: int = 2) -> dict:
    return {"restaurant_id": "r_anker", "table_id": table_id,
            "starts_at_local": fx.local(DATE, at), "party_size": party_size}


def export(anon) -> dict:
    resp = anon.get("/_test/export", token=None, timeout=RESET_TIMEOUT)
    return assert_status(resp, 200).json()


def import_(anon, body, **kw):
    kw.setdefault("json" if not isinstance(body, bytes) else "content", body)
    return anon.post("/_test/import", token=None, timeout=RESET_TIMEOUT, **kw)


def listing(client) -> list[dict]:
    return assert_status(client.get("/reservations"), 200).json()["reservations"]


def free_at(anon) -> dict[str, list[str]]:
    slots = assert_status(anon.get("/availability", params={
        "restaurant_id": "r_anker", "date": DATE, "party_size": 1}), 200).json()["slots"]
    return {s["starts_at_local"][-5:]: s["available_table_ids"] for s in slots}


@pytest.fixture
def source(reset, api, anon):
    """A source state with every kind of record: seeded and signed-up accounts, several
    sessions, created, amended, cancelled and moved bookings, keyed receipts of both
    paths, and a key whose request failed. Returns what the API showed before export."""
    reset(fx.fixture(reservations=[{
        "id": "res_seed", "reference": "SEED01", "user_id": "u_ada", "restaurant_id": "r_anker",
        "table_id": "t_3", "starts_at_local": fx.local(DATE, "21:00"), "party_size": 2}]))
    carol = api(assert_status(anon.signup(CAROL["email"], CAROL["password"],
                                          CAROL["display_name"]), 201).json()["token"])
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    bob = api().authenticate(fx.BOB["email"], fx.BOB["password"])
    s = SimpleNamespace(ada=ada, bob=bob, carol=carol, keys={})

    def keyed(client, name, path, body):
        key = new_key()
        resp = client.post(path, json=body, idempotency_key=key)
        s.keys[name] = (client, path, body, key, resp)
        return resp

    r1 = assert_status(keyed(ada, "k1", "/reservations", create_body("t_2", "19:00", 4)), 201).json()
    r2 = assert_status(keyed(ada, "k2", "/reservations", create_body("t_1", "18:00")), 201).json()
    assert_status(ada.patch(f"/reservations/{r2['reference']}",
                            json={"starts_at_local": fx.local(DATE, "20:30")}), 200)
    r3 = assert_status(keyed(ada, "k3", "/reservations", create_body("t_2", "21:00")), 201).json()
    assert_status(ada.post(f"/reservations/{r3['reference']}/cancel"), 200)
    assert_status(keyed(carol, "k4", "/reservations", create_body("t_3", "18:00")), 201)
    assert_status(keyed(ada, "km", "/reservation-moves",
                        {"moves": [{"reference": "SEED01", "starts_at_local": fx.local(DATE, "21:30")}]}), 201)
    failed = keyed(ada, "kf", "/reservations", create_body("t_2", "19:30"))
    assert_error(failed, 409, "table_unavailable")
    s.r1, s.r2, s.r3 = r1, r2, r3
    s.refs = {r["reference"] for c in (ada, bob, carol) for r in listing(c)}
    s.lists = {name: listing(c) for name, c in (("ada", ada), ("bob", bob), ("carol", carol))}
    s.free = free_at(anon)
    s.detail = assert_status(anon.get("/restaurants/r_anker"), 200).json()
    s.users = {"ada": fx.ADA["id"], "bob": fx.BOB["id"],
               "carol": assert_status(anon.login(CAROL["email"], CAROL["password"]), 200).json()["user_id"]}
    s.exported = export(anon)
    return s


def elsewhere(reset, api):
    """Reset to other data and give it a session and a booking of its own."""
    reset(fx.fixture(users=[DAN]))
    dan = api().authenticate(DAN["email"], DAN["password"])
    assert_status(dan.post("/reservations", json=create_body("t_1", "19:00"),
                           idempotency_key=new_key()), 201)
    return dan


# ---- export (§10) ---------------------------------------------------------------------------

def test_the_export_is_an_object_with_track_version_and_state(world, anon):
    """R129/R130: unauthenticated GET /_test/export answers 200 with track "tablekeeper",
    format_version 1 and an object state."""
    resp = assert_status(anon.get("/_test/export", token=None), 200)
    assert resp.headers["content-type"].replace(" ", "").lower() == "application/json;charset=utf-8"
    body = resp.json()
    assert body.get("track") == "tablekeeper"
    assert type(body.get("format_version")) is int and body["format_version"] == 1
    assert isinstance(body.get("state"), dict)


def test_the_export_holds_no_plaintext_password(source, anon):
    """R69/R138: accounts travel with their hashed passwords, never the plaintext."""
    text = json.dumps(source.exported, ensure_ascii=False)
    for password in (fx.ADA["password"], fx.BOB["password"], CAROL["password"]):
        assert password not in text


def test_exporting_changes_nothing(source, anon):
    """R137: export is a read-only snapshot: exporting again gives the same state."""
    assert export(anon) == source.exported
    assert listing(source.ada) == source.lists["ada"]


# ---- import restores everything (§10) ------------------------------------------------------------

def test_an_import_restores_accounts_sessions_bookings_and_receipts(source, reset, api, anon):
    """R132/R138/R139/R140/R154: after importing an unchanged export into a service
    holding other data: the passwords log in as the same users, old tokens work, every
    list reads exactly as before (identities, statuses, timestamps), restaurants and
    occupancy are as before, and the data that was there before is gone."""
    elsewhere(reset, api)
    assert import_(anon, source.exported).status_code == 204
    for name, account in (("ada", fx.ADA), ("bob", fx.BOB), ("carol", CAROL)):
        session = assert_status(anon.login(account["email"], account["password"]), 200).json()
        assert session["user_id"] == source.users[name]
    for name in ("ada", "bob", "carol"):
        assert listing(getattr(source, name)) == source.lists[name], name
    assert assert_status(source.ada.get(f"/reservations/{source.r1['reference']}"), 200).json() == source.r1
    assert assert_status(anon.get("/restaurants/r_anker"), 200).json() == source.detail
    assert free_at(anon) == source.free
    assert_error(anon.login(DAN["email"], DAN["password"]), 401, "unauthenticated")


def test_receipts_replay_after_import_and_failed_keys_stay_unused(source, reset, api, anon):
    """R138/R139/R140/R154: every completed keyed write -- /reservations and
    /reservation-moves, later amended or cancelled -- replays 200 with its original
    body and changes nothing; a different body on a used key is still reuse; the key
    whose request failed is a first use."""
    elsewhere(reset, api)
    assert import_(anon, source.exported).status_code == 204
    for name in ("k1", "k2", "k3", "k4", "km"):
        client, path, body, key, original = source.keys[name]
        replay = client.post(path, json=body, idempotency_key=key)
        assert assert_status(replay, 200).json() == original.json(), name
    client, path, body, key, _ = source.keys["k1"]
    assert_error(client.post(path, json=create_body("t_1", "22:00"), idempotency_key=key), 409,
                 "idempotency_key_reuse")
    for name in ("ada", "bob", "carol"):
        assert listing(getattr(source, name)) == source.lists[name], name
    client, path, _, key, _ = source.keys["kf"]
    assert_status(client.post(path, json=create_body("t_1", "18:00"), idempotency_key=key), 201)


def test_new_bookings_after_import_get_new_references(source, reset, api, anon):
    """R97/R140: references are unique across all reservations, imported ones included."""
    elsewhere(reset, api)
    assert import_(anon, source.exported).status_code == 204
    made = {assert_status(source.bob.post("/reservations", json=create_body(table, at),
                                          idempotency_key=new_key()), 201).json()["reference"]
            for table, at in (("t_1", "18:00"), ("t_2", "21:30"), ("t_3", "19:30"))}
    assert len(made) == 3 and not made & source.refs


def test_importing_twice_duplicates_nothing(source, reset, api, anon):
    """R134: repeating an import restores the exported state without duplicating."""
    elsewhere(reset, api)
    assert import_(anon, source.exported).status_code == 204
    once = export(anon)
    assert import_(anon, source.exported).status_code == 204
    assert export(anon) == once
    for name in ("ada", "bob", "carol"):
        assert listing(getattr(source, name)) == source.lists[name], name


def test_an_import_replaces_a_destination_that_holds_data(source, reset, api, anon):
    """R141 (N3): the destination's own account, session and booking are gone after an
    import; the table it had booked is free, and an imported user books it."""
    dan = elsewhere(reset, api)
    assert "t_1" not in free_at(anon)["19:00"]
    assert import_(anon, source.exported).status_code == 204
    assert_error(dan.get("/reservations"), 401, "unauthenticated")
    assert_error(anon.login(DAN["email"], DAN["password"]), 401, "unauthenticated")
    assert "t_1" in free_at(anon)["19:00"]
    assert_status(source.bob.post("/reservations", json=create_body("t_1", "19:00"),
                                  idempotency_key=new_key()), 201)


def test_imported_bookings_hold_their_tables(source, reset, api, anon):
    """R7 (B3): an imported confirmed booking is absent from every overlapping slot and
    refuses an overlapping create, PATCH and move; an imported cancelled booking blocks
    nothing."""
    elsewhere(reset, api)
    assert import_(anon, source.exported).status_code == 204
    free = free_at(anon)
    assert [at for at, ids in free.items() if "t_2" not in ids] == \
        ["18:00", "18:30", "19:00", "19:30", "20:00"]
    assert "t_2" in free["20:30"]
    assert_error(source.bob.post("/reservations", json=create_body("t_2", "19:30"),
                                 idempotency_key=new_key()), 409, "table_unavailable")
    ref2 = source.r2["reference"]
    assert_error(source.ada.patch(f"/reservations/{ref2}", json={"table_id": "t_2",
                                  "starts_at_local": fx.local(DATE, "19:00")}), 409, "table_unavailable")
    assert_error(source.ada.post("/reservation-moves", idempotency_key=new_key(), json={"moves": [
        {"reference": ref2, "table_id": "t_2", "starts_at_local": fx.local(DATE, "20:00")}]}),
        409, "table_unavailable")
    assert_status(source.bob.post("/reservations", json=create_body("t_2", "21:30"),
                                  idempotency_key=new_key()), 201)


def test_a_reset_after_an_import_clears_the_imported_state(source, reset, api, anon):
    """R141: reset clears everything, imported state included: imported sessions and
    accounts are gone and a key used before is a first use again."""
    elsewhere(reset, api)
    assert import_(anon, source.exported).status_code == 204
    reset(fx.fixture(users=[fx.ADA]))
    for client in (source.ada, source.carol):
        assert_error(client.get("/reservations"), 401, "unauthenticated")
    assert_error(anon.login(CAROL["email"], CAROL["password"]), 401, "unauthenticated")
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    _, path, body, key, _ = source.keys["k1"]
    assert_status(ada.post(path, json=body, idempotency_key=key), 201)
    assert len(listing(ada)) == 1


def test_an_export_is_the_state_when_it_was_taken(source, anon):
    """R137: writes after an export do not change it: importing it undoes them."""
    assert_status(source.bob.post("/reservations", json=create_body("t_1", "18:00"),
                                  idempotency_key=new_key()), 201)
    assert_status(source.ada.post(f"/reservations/{source.r1['reference']}/cancel"), 200)
    assert import_(anon, source.exported).status_code == 204
    assert listing(source.bob) == source.lists["bob"]
    assert listing(source.ada) == source.lists["ada"]


def test_unknown_top_level_fields_are_ignored(source, anon):
    """R29: unknown fields in the import body are ignored."""
    assert import_(anon, {**source.exported, "exported_by": "verifier"}).status_code == 204
    assert listing(source.ada) == source.lists["ada"]


# ---- rejected imports (§10, D20) --------------------------------------------------------------------

def _without(body: dict, name: str) -> dict:
    return {k: v for k, v in body.items() if k != name}


def _deep(value, leaf):
    """`value` with every string leaf replaced by `leaf(string)`."""
    if isinstance(value, dict):
        return {k: _deep(v, leaf) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep(v, leaf) for v in value]
    return leaf(value) if isinstance(value, str) else value


BAD_IMPORTS = {
    "non_object_array": lambda e: b"[]",
    "non_object_string": lambda e: b'"tablekeeper"',
    "non_object_number": lambda e: b"42",
    "non_object_null": lambda e: b"null",
    "missing_track": lambda e: _without(e, "track"),
    "missing_format_version": lambda e: _without(e, "format_version"),
    "missing_state": lambda e: _without(e, "state"),
    "wrong_track": lambda e: {**e, "track": "tablekeepers"},
    "track_wrong_type": lambda e: {**e, "track": 5},
    "version_2": lambda e: {**e, "format_version": 2},
    "version_string": lambda e: {**e, "format_version": "1"},
    "version_true": lambda e: {**e, "format_version": True},
    "version_float": lambda e: {**e, "format_version": 1.5},
    "state_array": lambda e: {**e, "state": []},
    "state_null": lambda e: {**e, "state": None},
    "state_empty": lambda e: {**e, "state": {}},
    "state_foreign": lambda e: {**e, "state": {"users": "nobody", "tables": 3}},
    "state_strings_to_numbers": lambda e: {**e, "state": _deep(e["state"], lambda s: 7)},
    "state_strings_emptied": lambda e: {**e, "state": _deep(e["state"], lambda s: "")},
}


@pytest.mark.parametrize("case", list(BAD_IMPORTS))
def test_a_rejected_import_is_422_and_changes_nothing(source, anon, case):
    """R135/D20: missing fields, a wrong track or version, a non-object body or an invalid
    state give 422 validation_failed, and the destination is exactly as before."""
    before = export(anon)
    payload = BAD_IMPORTS[case](source.exported)
    assert_error(import_(anon, payload), 422, "validation_failed")
    assert export(anon) == before
    assert listing(source.ada) == source.lists["ada"]


def test_an_unparseable_import_is_400_and_changes_nothing(source, anon):
    """R135/R47: invalid JSON follows §5: 400 malformed_request, destination unchanged."""
    before = export(anon)
    for raw in (b"{not json", b"", b'{"track": "tablekeeper",'):
        assert_error(import_(anon, raw), 400, "malformed_request")
    assert export(anon) == before


ODD_IMPORTS = [
    b"[" * 100_000 + b"]" * 100_000,
    b'{"track": "tablekeeper", "format_version": 1e400, "state": {}}',
    b'{"track": "\\ud800", "format_version": 1, "state": {"\\u0000": [[[[]]]]}}',
    b'{"track": "tablekeeper", "format_version": 99999999999999999999999, "state": {"users": [{}]}}',
]


@pytest.mark.parametrize("raw", ODD_IMPORTS, ids=[f"i{i}" for i in range(len(ODD_IMPORTS))])
def test_odd_imports_never_answer_5xx(world, anon, raw):
    """R60: requests must not produce 5xx; a refusal carries the error envelope."""
    resp = import_(anon, raw)
    assert resp.status_code < 500, f"-> {resp.status_code} {resp.text[:200]}"
    if resp.status_code >= 400:
        error_code(resp)
