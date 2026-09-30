"""S3-I1 stage-3 replacements (verifier seat) for six stage-2 upgrade checks superseded by
R330 (every reservation response gains `revision` and `accepted_terms`): a stage-1 export,
imported into the stage-3 service, keeps sessions, passwords, references, receipts and fresh
references, now read with `table_ids`, revision 1 and policy 0 (H6: imported bookings start
at revision 1 under policy 0, the exported fixture's own rules).

The stage-1 world is built by the stage-2 file's own helpers on the stage-1 service named by
TABLEKEEPER_STAGE1_URL (recipe S3-2); without it these checks fail.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib

import pytest

import fixtures as fx
from harness.http import RESET_TIMEOUT, Api, assert_error, assert_status, new_key

pytestmark = pytest.mark.stage(3)

_spec = importlib.util.spec_from_file_location(
    "stage2_upgrade", pathlib.Path(__file__).resolve().parents[1] / "stage-2" / "test_s2_i2_upgrade.py")
stage2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stage2)

POLICY_0 = {"policy_version": 0, "slot_minutes": 30, "reservation_duration_minutes": 90,
            "cancellation_cutoff_minutes": 120, "opening_hours": fx.all_week("12:00", "23:00"),
            "capacities": {"t_1": 2, "t_2": 4, "t_3": 6}}


def stage3(booking: dict) -> dict:
    """A stage-1 booking as the stage-3 service renders it: `table_ids`, revision 1, policy 0."""
    return {**stage2.with_table_ids(booking), "revision": 1, "accepted_terms": POLICY_0}


@pytest.fixture
def upgraded(base_url):
    url = os.environ.get("TABLEKEEPER_STAGE1_URL")
    assert url, "set TABLEKEEPER_STAGE1_URL to the stage-1 service of the same checkout"
    with Api(url.rstrip("/"), timeout=RESET_TIMEOUT) as stage1:
        world = stage2.stage1_world(stage1)
    with Api(base_url, timeout=RESET_TIMEOUT) as control:
        assert_status(control.post("/_test/import", json=world.exported), 204)
    return world


def test_sessions_from_stage_1_stay_signed_in(upgraded, api):
    """R246/R138/R330 (replaces the stage-2 check of the same name): every stage-1 token lists
    the same bookings in stage-3 shape."""
    for name, token in upgraded.tokens.items():
        listed = assert_status(api(token).get("/reservations"), 200).json()["reservations"]
        assert listed == [stage3(b) for b in upgraded.lists[name]], name


def test_stage_1_passwords_log_in_after_the_upgrade(upgraded, api):
    """R138/R330: stage-1 passwords log in and list the same bookings in stage-3 shape."""
    for name, account in (("ada", fx.ADA), ("bob", fx.BOB), ("cy", stage2.CY)):
        token = assert_status(api().login(account["email"], account["password"]), 200).json()["token"]
        assert assert_status(api(token).get("/reservations"), 200).json()["reservations"] == \
            [stage3(b) for b in upgraded.lists[name]], name
    assert api().login(fx.ADA["email"], "not the password").status_code == 401


def test_stage_1_references_read_in_stage_3_shape(upgraded, api):
    """R247/R139/R330/R331: each retained reference reads for its owner as on stage 1 plus
    `table_ids`, revision 1 and policy 0; to anyone else 404; its decision agrees."""
    for reference, booking in upgraded.bookings.items():
        owner = api(upgraded.tokens[upgraded.owners[reference]])
        assert assert_status(owner.get(f"/reservations/{reference}"), 200).json() == stage3(booking), reference
        assert assert_status(owner.get(f"/reservations/{reference}/decision"), 200).json() == \
            {"reference": reference, "revision": 1, "accepted_terms": POLICY_0}
        stranger = next(name for name in upgraded.tokens if name != upgraded.owners[reference])
        assert_error(api(upgraded.tokens[stranger]).get(f"/reservations/{reference}"), 404, "not_found")


def test_every_stage_1_receipt_replays_its_original_body(upgraded, api):
    """R248/R332/E8: every stage-1 receipt replays 200 with its original stage-1 body (no
    `table_ids`, `revision` or `accepted_terms`), with keys reordered too; another body is
    409; nothing changes."""
    for name, sent in upgraded.sent.items():
        if name == "failed":
            continue
        client = api(sent.token)
        resp = assert_status(client.post(sent.path, json=sent.body, idempotency_key=sent.key), 200)
        assert resp.json() == sent.response, name
        assert not {"table_ids", "revision", "accepted_terms"} & set(json.dumps(resp.json()).split('"')), name
        reordered = json.dumps(dict(reversed(list(sent.body.items())))).encode()
        assert assert_status(client.post(sent.path, content=reordered, idempotency_key=sent.key), 200).json() == sent.response
        other = {"restaurant_id": "r_anker"} if sent.path == "/reservations" else {"moves": []}
        assert_error(client.post(sent.path, json=other, idempotency_key=sent.key), 409, "idempotency_key_reuse")
    for name, token in upgraded.tokens.items():
        assert assert_status(api(token).get("/reservations"), 200).json()["reservations"] == \
            [stage3(b) for b in upgraded.lists[name]], name


def test_new_references_do_not_collide_with_imported_ones(upgraded, api):
    """R138/R139: bookings made after the import get new references; imported ones still read
    their own booking."""
    bob = api(upgraded.tokens["bob"])
    made = [assert_status(bob.post("/reservations", json=stage2.body(table, hhmm), idempotency_key=new_key()),
                          201).json()["reference"]
            for table, hhmm in (("t_1", "14:00"), ("t_1", "16:00"), ("t_2", "12:00"), ("t_3", "14:00"))]
    assert len(set(made)) == len(made) and not set(made) & set(upgraded.bookings)
    for reference, booking in upgraded.bookings.items():
        owner = api(upgraded.tokens[upgraded.owners[reference]])
        assert assert_status(owner.get(f"/reservations/{reference}"), 200).json() == stage3(booking)


def test_a_stray_table_ids_field_in_a_stage_1_reservation_is_ignored(upgraded, api, base_url):
    """E10/R330: a schema-1 reservation carrying an extra `table_ids` imports, holding its
    `table_id`, at revision 1 under policy 0."""
    import copy
    edited = copy.deepcopy(upgraded.exported)
    record = next(r for r in edited["state"]["reservations"] if r["reference"] == "SEEDA1")
    record["table_ids"] = ["t_1", "t_2"]
    with Api(base_url, timeout=RESET_TIMEOUT) as control:
        assert_status(control.post("/_test/import", json=edited), 204)
    read = assert_status(api(upgraded.tokens["ada"]).get("/reservations/SEEDA1"), 200).json()
    assert read == stage3(upgraded.bookings["SEEDA1"])
