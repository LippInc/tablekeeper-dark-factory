"""S1-I5 acceptance check across two service containers (verifier seat), from §10.

Needs a second, separately started container of the same image: pass its base URL in
the environment variable TABLEKEEPER_SECOND_URL (e.g. -e TABLEKEEPER_SECOND_URL=
http://<second-container>:8080 in recipe step 3b). Without it the check fails: an import
into the source's own process cannot show that nothing depends on that process.
"""
from __future__ import annotations

import os

import pytest

import fixtures as fx
from harness.http import RESET_TIMEOUT, Api, assert_error, assert_status, new_key

pytestmark = pytest.mark.stage(1)

DATE = fx.booking_date()
DAN = {"id": "u_dan", "email": "dan@example.com", "password": "dan's secret", "display_name": "Dan"}


def create_body(table_id: str, at: str) -> dict:
    return {"restaurant_id": "r_anker", "table_id": table_id,
            "starts_at_local": fx.local(DATE, at), "party_size": 2}


@pytest.fixture
def second_url() -> str:
    url = os.environ.get("TABLEKEEPER_SECOND_URL")
    assert url, "set TABLEKEEPER_SECOND_URL to a second container of the same image"
    return url.rstrip("/")


def test_an_export_restores_in_another_container(reset, api, base_url, second_url):
    """R133/R138/R139/R140/R141/R154: an export from container A, imported into a
    container B that holds data of its own, restores A's accounts, sessions, bookings
    and receipts in B, replaces B's own data, and B's export equals A's."""
    reset(fx.fixture())
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    signup = assert_status(api().signup("zoe@example.com", "zoe's secret", "Zoe"), 201).json()
    zoe = api(signup["token"])
    keyed = []
    for client, path, body in (
            (ada, "/reservations", create_body("t_2", "19:00")),
            (zoe, "/reservations", create_body("t_3", "19:00")),
            (ada, "/reservations", create_body("t_1", "21:00"))):
        key = new_key()
        keyed.append((client, path, body, key,
                      assert_status(client.post(path, json=body, idempotency_key=key), 201).json()))
    moved_ref = keyed[2][4]["reference"]
    move = {"moves": [{"reference": moved_ref, "starts_at_local": fx.local(DATE, "20:30")}]}
    key = new_key()
    keyed.append((ada, "/reservation-moves", move, key, assert_status(
        ada.post("/reservation-moves", json=move, idempotency_key=key), 201).json()))
    assert_status(ada.post(f"/reservations/{keyed[0][4]['reference']}/cancel"), 200)
    failed_key = new_key()
    assert_error(zoe.post("/reservations", json=create_body("t_3", "19:30"),
                          idempotency_key=failed_key), 409, "table_unavailable")
    lists = {"ada": ada.get("/reservations").json(), "zoe": zoe.get("/reservations").json()}
    refs = {r["reference"] for listed in lists.values() for r in listed["reservations"]}
    exported = assert_status(api().get("/_test/export", token=None, timeout=RESET_TIMEOUT), 200).json()

    with Api(second_url, timeout=RESET_TIMEOUT) as b:
        assert_status(b.post("/_test/reset", json=fx.fixture(users=[DAN]), token=None), 204)
        dan_token = assert_status(b.login(DAN["email"], DAN["password"]), 200).json()["token"]
        assert_status(b.post("/_test/import", json=exported, token=None), 204)
        assert assert_status(b.get("/_test/export", token=None), 200).json() == exported
        assert_error(b.get("/reservations", token=dan_token), 401, "unauthenticated")
        assert_error(b.login(DAN["email"], DAN["password"]), 401, "unauthenticated")
        assert b.login(fx.ADA["email"], fx.ADA["password"]).json()["user_id"] == fx.ADA["id"]
        assert b.login("zoe@example.com", "zoe's secret").json()["user_id"] == signup["user_id"]
        for name, client in (("ada", ada), ("zoe", zoe)):
            assert b.get("/reservations", token=client.token).json() == lists[name], name
        for client, path, body, key, original in keyed:
            replay = b.post(path, json=body, idempotency_key=key, token=client.token)
            assert assert_status(replay, 200).json() == original, path
        assert_status(b.post("/reservations", json=create_body("t_3", "21:00"),
                             idempotency_key=failed_key, token=zoe.token), 201)
        made = {assert_status(b.post("/reservations", json=create_body(table, "18:00"),
                                     idempotency_key=new_key(), token=ada.token), 201).json()["reference"]
                for table in ("t_1", "t_2")}
        assert not made & refs
