"""S1-I1 acceptance checks (verifier seat), written from the stage-1 specification.

Service foundation: runtime contract (§3), conventions and errors (§3.4, §5), reset
fixtures (§4), authentication (§6), restaurant reads and reservation reads (§8) and
offsets under IANA rules (§9). R.. and D.. name the room plan's requirement lines and
decisions. Timing and concurrency checks are in test_s1_i1_load.py and run alone.
"""
from __future__ import annotations

import datetime as dt
import re

import pytest

import fixtures as fx
from harness.http import assert_error, assert_status, error_code

pytestmark = pytest.mark.stage(1)

JSON_UTF8 = "application/json;charset=utf-8"
RFC3339 = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:\d{2}|Z)")
TOO_LONG_ID = "x" * 65
CAROL = {"email": "carol@example.com", "password": "correct horse", "display_name": "Carol"}


def media_type(resp) -> str:
    return resp.headers.get("content-type", "").replace(" ", "").lower()


def restaurant_ids(client) -> list[str]:
    return [r["id"] for r in assert_status(client.get("/restaurants"), 200).json()["restaurants"]]


def references(client) -> list[str]:
    body = assert_status(client.get("/reservations"), 200).json()
    return [r["reference"] for r in body["reservations"]]


def seeded(reference: str = "SEED01", *, starts_at_local: str, reservation_id: str = "res_seed",
           user_id: str = "u_ada", restaurant_id: str = "r_anker", table_id: str = "t_2",
           party_size: int = 2) -> dict:
    """A seeded booking: a create body plus `id`, `reference` and `user_id` (§4)."""
    return {"id": reservation_id, "reference": reference, "user_id": user_id,
            "restaurant_id": restaurant_id, "table_id": table_id,
            "starts_at_local": starts_at_local, "party_size": party_size}


def signup(client, account: dict):
    return client.signup(account["email"], account["password"], account["display_name"])


def login(client, account: dict):
    return client.login(account["email"], account["password"])


def assert_instant(value: str, local: str, offset: str) -> None:
    """`value` is RFC 3339 and names the local wall time `local` at UTC offset `offset`."""
    assert isinstance(value, str) and RFC3339.fullmatch(value), f"not RFC 3339: {value!r}"
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    shown = (parsed.replace(tzinfo=None).isoformat(timespec="minutes"),
             parsed.isoformat()[-6:])
    assert shown == (local, offset), f"{value!r} is {shown}, expected {(local, offset)}"


# ---- runtime contract and conventions (§3, §5) ----------------------------------

def test_every_json_response_is_declared_utf8(world, anon):
    """R27: responses are `application/json; charset=utf-8`, error responses included."""
    responses = [
        anon.get("/health"),
        anon.get("/restaurants"),
        anon.get(f"/restaurants/{world.rid}"),
        anon.get("/restaurants/r_nope"),
        anon.get("/reservations"),
        world.ada.get("/reservations"),
        world.ada.get("/reservations/NOPE99"),
        login(anon, fx.ADA),
        anon.login(fx.ADA["email"], "wrong password"),
        signup(anon, CAROL),
        signup(anon, CAROL),
        anon.signup("short@example.com", "short", "Short"),
        anon.post("/auth/login", content=b"{not json", token=None),
    ]
    wrong = [f"{r.request.method} {r.request.url.path} -> {r.status_code} "
             f"{r.headers.get('content-type')!r}" for r in responses if media_type(r) != JSON_UTF8]
    assert not wrong, "not application/json; charset=utf-8: " + "; ".join(wrong)


def test_error_responses_carry_the_error_envelope(world, anon):
    """R46: every 4xx carries {"error": {"code", "message"}} with the specified code."""
    cases = [
        (anon.post("/auth/signup", content=b"{", token=None), 400, "malformed_request"),
        (anon.get("/reservations"), 401, "unauthenticated"),
        (anon.get("/restaurants/r_nope"), 404, "not_found"),
        (anon.get("/no/such/path"), 404, "not_found"),  # D16
        (anon.signup(fx.ADA["email"], "correct horse", "Ada"), 409, "email_taken"),
        (anon.signup("new@example.com", "short", "New"), 422, "validation_failed"),
    ]
    for resp, status, code in cases:
        assert_error(resp, status, code)
        assert isinstance(resp.json()["error"].get("message"), str), \
            f"error.message must be a string: {resp.text}"


@pytest.mark.parametrize("path", ["/auth/signup", "/auth/login", "/_test/reset"])
@pytest.mark.parametrize("content", [b"{not json", b"", b'{"email": "a@example.com",'],
                         ids=["garbage", "empty", "truncated"])
def test_an_unparseable_body_is_malformed_request(world, anon, path, content):
    """R47/R58: a body that does not parse is 400 malformed_request, and a rejected
    reset leaves the running state alone."""
    assert_error(anon.post(path, content=content, token=None), 400, "malformed_request")
    assert restaurant_ids(anon) == [world.rid]


@pytest.mark.parametrize("path", ["/auth/signup", "/auth/login", "/_test/reset"])
@pytest.mark.parametrize("content", [b"[]", b'"text"', b"42", b"null"])
def test_a_body_that_is_not_an_object_is_malformed_request(world, anon, path, content):
    """D4 (§5, §7 "parsed as a JSON object"): a JSON body that is not an object is 400."""
    assert_error(anon.post(path, content=content, token=None), 400, "malformed_request")


def test_unknown_request_fields_are_ignored(reset, anon, api):
    """R29: unknown fields anywhere in a request body are ignored, never an error."""
    restaurant = {**fx.restaurant(), "michelin_stars": 3}
    restaurant["tables"] = [{**t, "window": True} for t in restaurant["tables"]]
    restaurant["opening_hours"] = [{**h, "note": "kitchen closes early"}
                                   for h in restaurant["opening_hours"]]
    booking = {**seeded(starts_at_local=fx.local(fx.booking_date(), "19:00")), "notes": "window"}
    fixture = fx.fixture(users=[{**fx.ADA, "phone": "+49 30 1234567"}, fx.BOB],
                         restaurants=[restaurant], reservations=[booking])
    reset({**fixture, "generated_by": "verifier"})
    token = assert_status(anon.post("/auth/login", token=None, json={
        "email": fx.ADA["email"], "password": fx.ADA["password"], "remember_me": True}),
        200).json()["token"]
    assert_status(anon.post("/auth/signup", token=None, json={**CAROL, "newsletter": True}), 201)
    assert references(api(token)) == ["SEED01"]


def test_unknown_query_parameters_are_ignored(world, anon):
    """R30: unknown query parameters are ignored."""
    for client, path in ((anon, "/restaurants"), (anon, f"/restaurants/{world.rid}"),
                         (world.ada, "/reservations")):
        plain = assert_status(client.get(path), 200).json()
        tagged = client.get(path, params={"utm_source": "newsletter", "lang": "de"})
        assert assert_status(tagged, 200).json() == plain, path


def test_restaurants_cannot_be_created_through_the_api(world, anon):
    """R32: restaurants come from reset only; there is no creation endpoint."""
    resp = world.ada.post("/restaurants", json=fx.restaurant("r_new", name="New"))
    assert 400 <= resp.status_code < 500, f"POST /restaurants -> {resp.status_code} {resp.text}"
    error_code(resp)
    assert restaurant_ids(anon) == [world.rid]


# ---- reset and seed (§3.3, §4) ----------------------------------------------------

def test_reset_replaces_every_kind_of_state(reset, anon, api):
    """R23/R24: after 204 only the new fixture exists -- no earlier account, session,
    restaurant or booking survives it."""
    reset(fx.fixture(reservations=[seeded(starts_at_local=fx.local(fx.booking_date(), "19:00"))]))
    carol_token = assert_status(signup(anon, CAROL), 201).json()["token"]
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    dan = {"id": "u_dan", "email": "dan@example.com", "password": "correct horse",
           "display_name": "Dan"}
    reset(fx.fixture(users=[dan], restaurants=[fx.restaurant("r_two", name="Two")]))
    assert_error(login(anon, CAROL), 401, "unauthenticated")
    assert_error(login(anon, fx.ADA), 401, "unauthenticated")
    assert_error(api(carol_token).get("/reservations"), 401, "unauthenticated")
    assert_error(ada.get("/reservations"), 401, "unauthenticated")
    assert restaurant_ids(anon) == ["r_two"]
    assert_error(anon.get("/restaurants/r_anker"), 404, "not_found")
    assert references(api().authenticate(dan["email"], dan["password"])) == []
    assert_status(signup(anon, CAROL), 201)
    reset(fx.fixture())
    assert references(api().authenticate(fx.ADA["email"], fx.ADA["password"])) == []


def test_repeating_a_reset_duplicates_nothing(reset, anon, api):
    """R25: repeated resets are supported; each leaves exactly the fixture."""
    fixture = fx.fixture(reservations=[seeded(starts_at_local=fx.local(fx.booking_date(), "19:00"))])
    for _ in range(3):
        reset(fixture)
    assert restaurant_ids(anon) == ["r_anker"]
    assert references(api().authenticate(fx.ADA["email"], fx.ADA["password"])) == ["SEED01"]


def _hours(weekday="thu", opens="18:00", closes="23:00") -> list[dict]:
    return [{"weekday": weekday, "opens": opens, "closes": closes}]


def _invalid_fixtures() -> dict[str, dict]:
    at = fx.local(fx.booking_date(), "19:00")
    later = fx.local(fx.booking_date(), "20:00")
    restaurant, fixture = fx.restaurant, fx.fixture
    return {
        "overlapping_seeds_on_one_table": fixture(reservations=[
            seeded("SEED01", starts_at_local=at),
            seeded("SEED02", reservation_id="res_2", starts_at_local=later)]),
        "restaurant_id_65_chars": fixture(restaurants=[restaurant(TOO_LONG_ID)]),
        "table_id_65_chars": fixture(restaurants=[restaurant(
            tables=[{"id": TOO_LONG_ID, "label": "1", "capacity": 2}])]),
        "reservation_id_65_chars": fixture(reservations=[
            seeded(reservation_id=TOO_LONG_ID, starts_at_local=at)]),
        "unknown_weekday": fixture(restaurants=[restaurant(opening_hours=_hours("thursday"))]),
        "opens_not_hh_mm": fixture(restaurants=[restaurant(opening_hours=_hours(opens="6pm"))]),
        "closes_not_after_opens": fixture(restaurants=[restaurant(
            opening_hours=_hours(opens="23:00", closes="18:00"))]),
        "unknown_timezone": fixture(restaurants=[restaurant(timezone="Mars/Olympus_Mons")]),
        "duplicate_reference": fixture(reservations=[
            seeded("SEED01", starts_at_local=at, table_id="t_2"),
            seeded("SEED01", reservation_id="res_2", starts_at_local=at, table_id="t_3")]),
        "seed_for_unknown_user": fixture(reservations=[
            seeded(user_id="u_nobody", starts_at_local=at)]),
        "seed_on_unknown_table": fixture(reservations=[seeded(table_id="t_9", starts_at_local=at)]),
        "seed_party_size_zero": fixture(reservations=[seeded(party_size=0, starts_at_local=at)]),
        "seed_in_skipped_hour": fixture(
            restaurants=[restaurant(opening_hours=fx.all_week("00:00", "23:30"))],
            reservations=[seeded(starts_at_local="2026-03-29T02:30")]),
    }


@pytest.mark.parametrize("defect", sorted(_invalid_fixtures()))
def test_an_invalid_fixture_is_422_and_changes_nothing(world, anon, api, reset, defect):
    """R7/R31/R40/R41/R33/D13: an invalid fixture is 422 validation_failed and the
    running state -- restaurants, accounts, sessions -- stays as it was."""
    carol_token = assert_status(signup(anon, CAROL), 201).json()["token"]
    assert_error(reset(_invalid_fixtures()[defect], raw=True), 422, "validation_failed")
    assert restaurant_ids(anon) == [world.rid]
    assert_status(api(carol_token).get("/reservations"), 200)
    assert_status(world.ada.get("/reservations"), 200)
    assert_status(login(anon, fx.ADA), 200)


@pytest.mark.parametrize("path,value", [
    ("restaurants.0.tables.0.capacity", "4"),
    ("restaurants.0.slot_minutes", "30"),
    ("restaurants.0.opening_hours", "every evening"),
    ("restaurants.0.tables.0.id", 7),
    ("users", {"u_ada": fx.ADA}),
])
def test_a_fixture_field_of_the_wrong_json_type_is_400(world, anon, reset, path, value):
    """R47 and the architect's v2.2 ruling on D4/D13: a fixture field of the wrong JSON
    type is 400 malformed_request, and the running state stays as it was."""
    fixture = fx.fixture()
    *parents, leaf = path.split(".")
    node = fixture
    for part in parents:
        node = node[int(part)] if part.isdigit() else node[part]
    node[int(leaf) if leaf.isdigit() else leaf] = value
    assert_error(reset(fixture, raw=True), 400, "malformed_request")
    assert restaurant_ids(anon) == [world.rid]


@pytest.mark.parametrize("second", [("t_2", "20:30"), ("t_3", "19:00")],
                         ids=["touching_on_one_table", "same_time_other_table"])
def test_seeded_bookings_that_do_not_overlap_are_accepted(reset, api, second):
    """R7 (§1): occupancy is half-open, so 19:00-20:30 and 20:30 do not overlap; two
    tables are independent."""
    table_id, at = second
    date = fx.booking_date()
    reset(fx.fixture(reservations=[
        seeded("SEED01", starts_at_local=fx.local(date, "19:00"), table_id="t_2"),
        seeded("SEED02", reservation_id="res_2", table_id=table_id,
               starts_at_local=fx.local(date, at))]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    assert sorted(references(ada)) == ["SEED01", "SEED02"]


def test_fixture_ids_of_64_characters_are_kept_intact(reset, anon, api):
    """R31: IDs up to 64 characters are valid, fixture IDs included."""
    uid, rid, tid, resid = "u" * 64, "r" * 64, "t" * 64, "s" * 64
    reset(fx.fixture(
        users=[{**fx.ADA, "id": uid}],
        restaurants=[fx.restaurant(rid, tables=[{"id": tid, "label": "Long", "capacity": 4}])],
        reservations=[seeded(reservation_id=resid, user_id=uid, restaurant_id=rid, table_id=tid,
                             starts_at_local=fx.local(fx.booking_date(), "19:00"))]))
    session = assert_status(login(anon, fx.ADA), 200).json()
    assert session["user_id"] == uid
    detail = assert_status(anon.get(f"/restaurants/{rid}"), 200).json()
    assert detail["id"] == rid and [t["id"] for t in detail["tables"]] == [tid]
    booking = assert_status(api(session["token"]).get("/reservations/SEED01"), 200).json()
    assert (booking["reservation_id"], booking["restaurant_id"], booking["table_id"]) == \
        (resid, rid, tid)


# ---- authentication (§6) ------------------------------------------------------------

def test_signup_and_login_describe_the_same_account(world, anon):
    """R61/R62: both answer user_id, display_name and a token for one account."""
    zoe = {"email": "zoe@example.com", "password": "correct horse", "display_name": "Zoë"}
    created = assert_status(signup(anon, zoe), 201).json()
    assert isinstance(created["user_id"], str) and 1 <= len(created["user_id"]) <= 64
    assert created["display_name"] == "Zoë"
    assert isinstance(created["token"], str) and created["token"]
    session = assert_status(login(anon, zoe), 200).json()
    assert (session["user_id"], session["display_name"]) == (created["user_id"], "Zoë")
    assert isinstance(session["token"], str) and session["token"]


def test_a_seeded_user_logs_in_as_the_seeded_account(world, anon):
    """R42/R62: login answers the fixture's user id and display name."""
    session = assert_status(login(anon, fx.ADA), 200).json()
    assert (session["user_id"], session["display_name"]) == (fx.ADA["id"], fx.ADA["display_name"])


def test_an_account_keeps_every_session_it_opens(world, anon, api):
    """R68: an account may hold several valid tokens at once."""
    tokens = [assert_status(signup(anon, CAROL), 201).json()["token"]]
    tokens += [assert_status(login(anon, CAROL), 200).json()["token"] for _ in range(3)]
    for token in tokens:
        assert_status(api(token).get("/reservations"), 200)
    assert_status(login(anon, fx.ADA), 200)
    assert_status(world.ada.get("/reservations"), 200)


def test_a_password_of_exactly_eight_characters_is_accepted(world, anon):
    """R64: only passwords shorter than 8 characters are refused."""
    eight = {"email": "eight@example.com", "password": "8 chars!", "display_name": "Eight"}
    assert_status(signup(anon, eight), 201)
    assert_status(login(anon, eight), 200)


@pytest.mark.parametrize("email", ["@example.com", "ada@", ""])
def test_signup_email_needs_a_local_part_and_a_domain(world, anon, email):
    """R65: an email not of the form local@domain is 422 validation_failed."""
    assert_error(anon.signup(email, "correct horse", "X"), 422, "validation_failed")


@pytest.mark.parametrize("drop", ["email", "password", "display_name"])
def test_signup_without_a_field_is_422(world, anon, drop):
    """R53: a missing required field is 422 validation_failed."""
    body = {key: value for key, value in CAROL.items() if key != drop}
    assert_error(anon.post("/auth/signup", json=body, token=None), 422, "validation_failed")


@pytest.mark.parametrize("drop", ["email", "password"])
def test_login_without_a_field_is_422(world, anon, drop):
    """R53: a missing required field is 422 validation_failed."""
    body = {key: value for key, value in fx.ADA.items() if key in ("email", "password")}
    del body[drop]
    assert_error(anon.post("/auth/login", json=body, token=None), 422, "validation_failed")


@pytest.mark.parametrize("field,value", [("password", 12345678), ("email", None)])
def test_login_field_of_the_wrong_json_type_is_400(world, anon, field, value):
    """R47: a field of the wrong JSON type is 400 malformed_request."""
    body = {"email": fx.ADA["email"], "password": fx.ADA["password"], field: value}
    assert_error(anon.post("/auth/login", json=body, token=None), 400, "malformed_request")


def test_a_taken_email_keeps_the_first_account(world, anon):
    """R63: a second signup for an email is 409 email_taken and changes nothing."""
    assert_status(signup(anon, CAROL), 201)
    assert_error(anon.signup(CAROL["email"], "another password", "Impostor"), 409, "email_taken")
    assert_status(login(anon, CAROL), 200)
    assert_error(anon.login(CAROL["email"], "another password"), 401, "unauthenticated")


def test_a_rejected_signup_creates_no_account(world, anon):
    """R64/§1: a rejected request leaves nothing behind -- the email stays free."""
    assert_error(anon.signup(CAROL["email"], "short", "Carol"), 422, "validation_failed")
    assert_error(anon.login(CAROL["email"], "short"), 401, "unauthenticated")
    assert_status(signup(anon, CAROL), 201)


@pytest.mark.parametrize("scheme", ["Token {}", "{}", "Basic {}"])
def test_a_token_must_be_sent_as_a_bearer_token(world, anon, scheme):
    """R49: a malformed Authorization header is 401 unauthenticated."""
    token = world.ada.token
    assert_status(anon.get("/reservations", headers={"Authorization": f"Bearer {token}"}), 200)
    resp = anon.get("/reservations", headers={"Authorization": scheme.format(token)})
    assert_error(resp, 401, "unauthenticated")


def test_email_comparison_ignores_case(world, anon):
    """D14: emails compare case-insensitively for signup uniqueness and login."""
    assert_error(anon.signup("ADA@EXAMPLE.COM", "correct horse", "Ada"), 409, "email_taken")
    assert_status(anon.login("Ada@Example.com", fx.ADA["password"]), 200)


# ---- restaurant reads (§8) ------------------------------------------------------------

def _entries(items: list[dict], keys: tuple[str, ...]) -> list[tuple]:
    return sorted(tuple(item.get(key) for key in keys) for item in items)


def test_restaurant_list_names_every_restaurant_once(reset, anon):
    """R84: the list carries id, name and timezone of every restaurant."""
    restaurants = [fx.restaurant("r_zeta", name="Zeta", timezone="America/New_York"),
                   fx.restaurant("r_alpha", name="Alpha"),
                   fx.restaurant("r_mid", name="Mid", timezone="Asia/Tokyo")]
    reset(fx.fixture(restaurants=restaurants))
    listed = assert_status(anon.get("/restaurants"), 200).json()["restaurants"]
    keys = ("id", "name", "timezone")
    assert _entries(listed, keys) == _entries(restaurants, keys)


def test_restaurant_detail_is_its_own_fixture_entry(reset, anon):
    """R85/R5: each restaurant answers its own configuration in the fixture's shape."""
    anker = fx.restaurant(opening_hours=[
        {"weekday": "thu", "opens": "18:00", "closes": "23:00"},
        {"weekday": "fri", "opens": "18:00", "closes": "23:30"}])
    harbor = fx.restaurant(
        "r_harbor", name="Harbor", timezone="America/New_York", slot_minutes=15,
        reservation_duration_minutes=120, cancellation_cutoff_minutes=0,
        opening_hours=[{"weekday": "mon", "opens": "11:30", "closes": "14:30"},
                       {"weekday": "sat", "opens": "17:00", "closes": "22:00"}],
        tables=[{"id": "t_1", "label": "Window", "capacity": 2},
                {"id": "t_9", "label": "Bar", "capacity": 8}])
    reset(fx.fixture(restaurants=[anker, harbor]))
    for expected in (anker, harbor):
        body = assert_status(anon.get(f"/restaurants/{expected['id']}"), 200).json()
        for field in ("id", "name", "timezone", "slot_minutes",
                      "reservation_duration_minutes", "cancellation_cutoff_minutes"):
            assert body.get(field) == expected[field], (expected["id"], field, body.get(field))
        hours = ("weekday", "opens", "closes")
        assert _entries(body["opening_hours"], hours) == _entries(expected["opening_hours"], hours)
        table = ("id", "label", "capacity")
        assert _entries(body["tables"], table) == _entries(expected["tables"], table)


# ---- reservation reads and time (§8, §9) -------------------------------------------------

def test_a_seeded_booking_reads_back_in_the_create_response_shape(reset, api):
    """R43/R106/R28: the seeded identity and every create-response field, with
    timestamps in RFC 3339 carrying an explicit offset."""
    reset(fx.fixture(reservations=[seeded(
        "SEED07", reservation_id="res_seed_7", table_id="t_3", party_size=5,
        starts_at_local="2026-07-16T19:30")]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    body = assert_status(ada.get("/reservations/SEED07"), 200).json()
    assert {key: body.get(key) for key in ("reservation_id", "reference", "restaurant_id",
                                           "table_id", "party_size", "status",
                                           "starts_at_local")} == {
        "reservation_id": "res_seed_7", "reference": "SEED07", "restaurant_id": "r_anker",
        "table_id": "t_3", "party_size": 5, "status": "confirmed",
        "starts_at_local": "2026-07-16T19:30"}
    assert_instant(body.get("starts_at"), "2026-07-16T19:30", "+02:00")
    assert_instant(body.get("ends_at"), "2026-07-16T21:00", "+02:00")
    created = body.get("created_at")
    assert isinstance(created, str) and RFC3339.fullmatch(created), f"created_at {created!r}"


IANA_CASES = [
    # zone, seeded local start, its offset, local end 90 absolute minutes later, its offset
    ("Europe/Berlin", "2026-07-15T19:00", "+02:00", "2026-07-15T20:30", "+02:00"),
    ("Europe/Berlin", "2026-01-14T19:00", "+01:00", "2026-01-14T20:30", "+01:00"),
    ("America/New_York", "2026-07-15T19:00", "-04:00", "2026-07-15T20:30", "-04:00"),
    ("America/New_York", "2026-01-14T19:00", "-05:00", "2026-01-14T20:30", "-05:00"),
    ("Europe/Berlin", "2026-03-29T01:30", "+01:00", "2026-03-29T04:00", "+02:00"),
    ("Europe/Berlin", "2026-03-29T03:00", "+02:00", "2026-03-29T04:30", "+02:00"),
    ("Europe/Berlin", "2026-10-25T01:30", "+02:00", "2026-10-25T02:00", "+01:00"),
    ("Europe/Berlin", "2026-10-25T02:30", "+02:00", "2026-10-25T03:00", "+01:00"),
    ("America/New_York", "2026-03-08T01:30", "-05:00", "2026-03-08T04:00", "-04:00"),
    ("America/New_York", "2026-11-01T00:30", "-04:00", "2026-11-01T01:00", "-05:00"),
    ("America/New_York", "2026-11-01T01:30", "-04:00", "2026-11-01T02:00", "-05:00"),
    ("Asia/Kolkata", "2026-07-15T19:00", "+05:30", "2026-07-15T20:30", "+05:30"),
    ("Australia/Lord_Howe", "2026-07-15T19:00", "+10:30", "2026-07-15T20:30", "+10:30"),
    ("Australia/Lord_Howe", "2026-01-14T19:00", "+11:00", "2026-01-14T20:30", "+11:00"),
]


@pytest.mark.parametrize("zone,local,offset,end_local,end_offset", IANA_CASES)
def test_seeded_times_carry_offsets_under_iana_rules(reset, api, zone, local, offset,
                                                     end_local, end_offset):
    """R128/R28/§9: offsets follow the zone's IANA rules; a repeated wall time is its
    first occurrence; the duration is absolute time."""
    restaurant = fx.restaurant(timezone=zone, opening_hours=fx.all_week("00:00", "23:30"))
    reset(fx.fixture(restaurants=[restaurant], reservations=[seeded(starts_at_local=local)]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    body = assert_status(ada.get("/reservations/SEED01"), 200).json()
    assert body["starts_at_local"] == local
    assert_instant(body["starts_at"], local, offset)
    assert_instant(body["ends_at"], end_local, end_offset)


def _two_zone_bookings(reset, api):
    """Ada's four bookings in Berlin and New York, seeded out of order, and one of Bob's."""
    hours = fx.all_week("08:00", "23:30")
    reset(fx.fixture(
        restaurants=[fx.restaurant("r_ber", opening_hours=hours),
                     fx.restaurant("r_nyc", name="Harbor", timezone="America/New_York",
                                   opening_hours=hours)],
        reservations=[
            seeded("BER190", reservation_id="res_1", restaurant_id="r_ber", table_id="t_1",
                   starts_at_local="2026-07-15T19:00"),                       # 17:00Z
            seeded("NYC090", reservation_id="res_2", restaurant_id="r_nyc", table_id="t_1",
                   starts_at_local="2026-07-16T09:00"),                       # 13:00Z next day
            seeded("BER120", reservation_id="res_3", restaurant_id="r_ber", table_id="t_2",
                   starts_at_local="2026-07-15T12:00"),                       # 10:00Z
            seeded("NYC140", reservation_id="res_4", restaurant_id="r_nyc", table_id="t_2",
                   starts_at_local="2026-07-15T14:00"),                       # 18:00Z
            seeded("BOB001", reservation_id="res_5", restaurant_id="r_ber", table_id="t_3",
                   user_id="u_bob", starts_at_local="2026-07-15T19:00"),
        ]))
    return (api().authenticate(fx.ADA["email"], fx.ADA["password"]),
            api().authenticate(fx.BOB["email"], fx.BOB["password"]))


def test_the_reservation_list_is_starts_at_descending_across_zones(reset, api):
    """R105/D16: `starts_at` descending compares instants, not local wall times."""
    ada, _ = _two_zone_bookings(reset, api)
    assert references(ada) == ["NYC090", "NYC140", "BER190", "BER120"]


def test_the_reservation_list_holds_only_the_callers_bookings(reset, api, anon):
    """R105: the caller's reservations; an empty list is exactly {"reservations": []}."""
    _, bob = _two_zone_bookings(reset, api)
    assert references(bob) == ["BOB001"]
    token = assert_status(signup(anon, CAROL), 201).json()["token"]
    assert assert_status(api(token).get("/reservations"), 200).json() == {"reservations": []}


def test_list_entries_are_the_single_reservation_reads(reset, api):
    """R105: each list entry has the same shape as the single read (create response)."""
    ada, _ = _two_zone_bookings(reset, api)
    entries = assert_status(ada.get("/reservations"), 200).json()["reservations"]
    assert len(entries) == 4
    for entry in entries:
        assert assert_status(ada.get(f"/reservations/{entry['reference']}"), 200).json() == entry


# ---- no 5xx on odd input (§5) -------------------------------------------------------------

def _odd_fixture(**restaurant_fields) -> dict:
    return fx.fixture(restaurants=[{**fx.restaurant(), **restaurant_fields}])


ODD_REQUESTS = [
    ("/auth/signup", {"email": "a@b", "password": "x" * 100_000, "display_name": "\u0000"}),
    ("/auth/signup", {"email": ["ada@example.com"], "password": {}, "display_name": 1.5}),
    ("/auth/signup", b'{"email": "\\ud800@example.com", "password": "correct horse", '
                     b'"display_name": "\\udfff"}'),
    ("/auth/signup", b'{"email": "a@example.com", "password": 1e400, "display_name": "A"}'),
    ("/auth/signup", b"[" * 100_000 + b"]" * 100_000),
    ("/auth/login", {"email": None, "password": None}),
    ("/auth/login", b'{"email": "ada@example.com", "password": NaN}'),
    ("/_test/reset", _odd_fixture(timezone="../../etc/passwd")),
    ("/_test/reset", _odd_fixture(timezone="")),
    ("/_test/reset", _odd_fixture(timezone="Europe/Berlin\u0000")),
    ("/_test/reset", _odd_fixture(slot_minutes=10**30, reservation_duration_minutes=10**30)),
    ("/_test/reset", _odd_fixture(opening_hours=_hours(opens="24:00", closes="99:99"))),
    ("/_test/reset", fx.fixture(reservations=[seeded(starts_at_local="9999-12-31T23:30")])),
    ("/_test/reset", fx.fixture(reservations=[seeded(starts_at_local="0001-01-01T00:00")])),
]


@pytest.mark.parametrize("path,body", ODD_REQUESTS, ids=[f"{p}#{i}" for i, (p, _) in
                                                        enumerate(ODD_REQUESTS)])
def test_odd_input_never_answers_5xx(world, anon, path, body):
    """R60: requests must not produce 5xx; a refusal carries the error envelope."""
    if isinstance(body, bytes):
        resp = anon.post(path, content=body, token=None)
    else:
        resp = anon.post(path, json=body, token=None)
    assert resp.status_code < 500, f"{path} -> {resp.status_code} {resp.text[:200]}"
    if resp.status_code >= 400:
        error_code(resp)
