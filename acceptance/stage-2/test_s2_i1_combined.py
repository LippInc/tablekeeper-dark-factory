"""S2-I1 acceptance checks (verifier seat), written from the stage-2 specification.

Combined tables in the API ("Combined tables", "Model", "API"): the fixture's
`combinable` pairs and seeded `status`/`table_ids`; `available_options` beside an unchanged
`available_table_ids`; `table_ids` on create, PATCH and move items with every refusal;
response shapes; cancel freeing every table; table-set occupancy after every writer; and
schema-2 export/import. R.. and E.. name the room plan's requirement lines and decisions.
The races and the dense day are in test_s2_i1_races.py (run alone).
"""
from __future__ import annotations

import pytest

import fixtures as fx
from harness.http import RESET_TIMEOUT, assert_error, assert_status, error_code, new_key

pytestmark = pytest.mark.stage(2)

DATE = fx.booking_date()
TABLES = [{"id": "t_1", "label": "Window", "capacity": 2},
          {"id": "t_2", "label": "Bar", "capacity": 4},
          {"id": "t_3", "label": "Corner", "capacity": 6}]
PAIRS = [["t_1", "t_2"], ["t_3", "t_2"]]           # the second pair is declared "backwards"
CAPACITY = {t["id"]: t["capacity"] for t in TABLES}
DURATION = 90


def restaurant(**overrides) -> dict:
    return {**fx.restaurant(tables=[dict(t) for t in TABLES],
                            opening_hours=fx.all_week("12:00", "23:00")),
            "combinable": [list(p) for p in PAIRS], **overrides}


def other_restaurant() -> dict:
    return {**fx.restaurant("r_other", name="Other",
                            tables=[{"id": "t_x", "label": "X", "capacity": 8}]), "combinable": []}


def minutes(hhmm: str) -> int:
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


def at(hhmm: str) -> str:
    return fx.local(DATE, hhmm)


def seed(reference: str, *, at_time: str, user_id: str = "u_ada", party_size: int = 2, **tables) -> dict:
    return {"id": f"res_{reference}", "reference": reference, "user_id": user_id,
            "restaurant_id": "r_anker", "starts_at_local": at(at_time), "party_size": party_size,
            **tables}


def body(tables: dict, hhmm: str = "19:00", party_size: int = 2, restaurant_id: str = "r_anker") -> dict:
    return {"restaurant_id": restaurant_id, "starts_at_local": at(hhmm), "party_size": party_size,
            **tables}


def create(client, payload: dict, key: str | None = None):
    return client.post("/reservations", json=payload, idempotency_key=key or new_key())


def availability(client, party: int) -> list[dict]:
    return assert_status(client.get("/availability", params={
        "restaurant_id": "r_anker", "date": DATE, "party_size": party}), 200).json()["slots"]


def reference(booked: dict[str, list[int]], party: int) -> list[tuple]:
    """Per slot (12:00 to 21:30, every 30 minutes): the single tables and the options the
    specification prescribes, from the confirmed bookings this check knows of."""
    def free(table: str, start: int) -> bool:
        return all(abs(start - b) >= DURATION for b in booked[table])

    found = []
    for start in range(minutes("12:00"), minutes("23:00") - DURATION + 1, 30):
        singles = [{"table_ids": [t["id"]], "capacity": t["capacity"]} for t in TABLES
                   if t["capacity"] >= party and free(t["id"], start)]
        pairs = [{"table_ids": list(pair), "capacity": sum(CAPACITY[t] for t in pair)}
                 for pair in PAIRS if sum(CAPACITY[t] for t in pair) >= party
                 and all(free(t, start) for t in pair)]
        found.append((f"{start // 60:02d}:{start % 60:02d}",
                      [o["table_ids"][0] for o in singles], singles + pairs))
    return found


def shown(slots: list[dict]) -> list[tuple]:
    return [(s["starts_at_local"][-5:], s["available_table_ids"], s.get("available_options"))
            for s in slots]


def assert_shape(booking: dict, table_ids: list[str]) -> None:
    """R260: `table_ids` always; `table_id` exactly when the set has one member."""
    assert booking.get("table_ids") == table_ids, booking
    if len(table_ids) == 1:
        assert booking.get("table_id") == table_ids[0], booking
    else:
        assert "table_id" not in booking, booking


@pytest.fixture
def pairs(reset, api):
    reset(fx.fixture(restaurants=[restaurant(), other_restaurant()]))
    return (api().authenticate(fx.ADA["email"], fx.ADA["password"]),
            api().authenticate(fx.BOB["email"], fx.BOB["password"]))


# ---- fixture (Model, E4) ----------------------------------------------------------------------

def pair_options(client) -> list[list[str]]:
    seven = next(s for s in availability(client, 1) if s["starts_at_local"].endswith("19:00"))
    return [o["table_ids"] for o in seven["available_options"] if len(o["table_ids"]) == 2]


def test_a_restaurant_without_combinable_offers_no_pairs(reset, anon):
    """R202/E4: `combinable` is optional and absent means no pairs; a declared list
    offers its pairs, in declared order and member order."""
    reset(fx.fixture(restaurants=[{k: v for k, v in restaurant().items() if k != "combinable"}]))
    assert pair_options(anon) == []
    reset(fx.fixture(restaurants=[restaurant()]))
    assert pair_options(anon) == PAIRS


@pytest.mark.parametrize("combinable,status", [
    ([["t_1", "t_2", "t_3"]], 422), ([["t_1"]], 422), ([["t_1", "t_9"]], 422),
    ([["t_1", "t_1"]], 422), ([["t_1", "t_2"], ["t_2", "t_1"]], 422),
    ("t_1,t_2", 400), (["t_1", "t_2"], 400), ([["t_1", 2]], 400),
], ids=["three_ids", "one_id", "unknown_id", "same_table_twice", "pair_repeated_reversed",
        "not_a_list", "pair_not_a_list", "member_not_a_string"])
def test_an_invalid_combinable_list_is_refused_and_changes_nothing(reset, anon, combinable, status):
    """R252 (pairs only, of that restaurant's tables) / E4 / D13: an invalid list refuses
    the reset and the previous state stays."""
    reset(fx.fixture(restaurants=[restaurant()]))
    code = "validation_failed" if status == 422 else "malformed_request"
    assert_error(reset(fx.fixture(restaurants=[restaurant(combinable=combinable)]), raw=True),
                 status, code)
    assert pair_options(anon) == PAIRS


def test_seeded_status_and_table_sets(reset, api):
    """R255: seeded reservations are confirmed unless `status` is cancelled, and hold
    `table_id` or `table_ids`; a seeded pair is stored in declared order (E2)."""
    reset(fx.fixture(restaurants=[restaurant()], reservations=[
        seed("SEEDP1", at_time="19:00", table_ids=["t_2", "t_1"]),
        seed("SEEDC1", at_time="19:00", table_id="t_3", status="cancelled"),
        seed("SEEDS1", at_time="21:00", table_ids=["t_3"], status="confirmed"),
        seed("SEEDS2", at_time="12:00", table_id="t_1")]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    got = {r["reference"]: r for r in assert_status(ada.get("/reservations"), 200).json()["reservations"]}
    assert_shape(got["SEEDP1"], ["t_1", "t_2"])
    assert got["SEEDC1"]["status"] == "cancelled" and got["SEEDP1"]["status"] == "confirmed"
    assert_shape(got["SEEDS1"], ["t_3"])
    assert_shape(got["SEEDS2"], ["t_1"])
    at_seven = next(s for s in availability(ada, 1) if s["starts_at_local"].endswith("19:00"))
    assert at_seven["available_table_ids"] == ["t_3"], "the cancelled seed occupies nothing"


@pytest.mark.parametrize("bad", [
    {"table_ids": ["t_1", "t_3"]}, {"table_ids": ["t_1", "t_2", "t_3"]},
    {"table_id": "t_1", "table_ids": ["t_1", "t_2"]}, {"table_id": "t_1", "status": "pending"},
], ids=["undeclared_pair", "three_tables", "both_fields", "unknown_status"])
def test_an_invalid_seeded_reservation_refuses_the_reset(reset, bad):
    """R253/R252/R255/E4: seeded pairs must be declared, sets hold at most two tables,
    `table_id` and `table_ids` exclude each other, and a status is confirmed or cancelled."""
    assert_error(reset(fx.fixture(restaurants=[restaurant()], reservations=[
        seed("SEEDX1", at_time="19:00", **bad)]), raw=True), 422, "validation_failed")


def test_seeded_pairs_may_not_overlap_confirmed_bookings_on_a_member(reset):
    """R250/R7: a seeded pair occupies both tables; a confirmed seed overlapping one member
    refuses the reset; a cancelled one does not."""
    pair = seed("SEEDP1", at_time="19:00", table_ids=["t_1", "t_2"])
    assert_error(reset(fx.fixture(restaurants=[restaurant()], reservations=[
        pair, seed("SEEDS1", at_time="20:00", table_id="t_2")]), raw=True), 422, "validation_failed")
    reset(fx.fixture(restaurants=[restaurant()], reservations=[
        pair, seed("SEEDS1", at_time="20:00", table_id="t_2", status="cancelled")]))


# ---- availability (API, R256/R257) --------------------------------------------------------------

@pytest.mark.parametrize("party", [1, 2, 3, 5, 6, 7, 10, 11])
def test_available_options_list_singles_then_declared_pairs(reset, anon, party):
    """R256/R257/R254/R253: singles in fixture order, then declared pairs in declared order
    with summed capacity >= party and both members free; available_table_ids unchanged."""
    reset(fx.fixture(restaurants=[restaurant()], reservations=[
        seed("SEEDP1", at_time="12:00", table_ids=["t_1", "t_2"], party_size=5),
        seed("SEEDS1", at_time="19:00", table_id="t_2"),
        seed("SEEDS2", at_time="20:30", table_id="t_3")]))
    booked = {"t_1": [minutes("12:00")], "t_2": [minutes("12:00"), minutes("19:00")],
              "t_3": [minutes("20:30")]}
    assert shown(availability(anon, party)) == reference(booked, party)


# ---- create (API, E3 order) --------------------------------------------------------------------

@pytest.mark.parametrize("tables,expected", [
    ({"table_ids": ["t_1", "t_2"]}, ["t_1", "t_2"]),
    ({"table_ids": ["t_2", "t_1"]}, ["t_1", "t_2"]),
    ({"table_ids": ["t_2", "t_3"]}, ["t_3", "t_2"]),
    ({"table_ids": ["t_3"]}, ["t_3"]),
    ({"table_id": "t_3"}, ["t_3"]),
], ids=["declared_pair", "reversed_pair", "other_pair_reversed", "one_member_list", "table_id"])
def test_a_booking_holds_the_named_table_set(pairs, tables, expected):
    """R250/R251/R258/R259/R260/E2: a pair books both tables and is answered in declared
    order without `table_id`; a set of one carries both fields; reads, the list and a
    replay answer the same body."""
    ada, _ = pairs
    key = new_key()
    created = assert_status(create(ada, body(tables, party_size=5), key), 201).json()
    assert_shape(created, expected)
    assert assert_status(ada.get(f"/reservations/{created['reference']}"), 200).json() == created
    assert assert_status(ada.get("/reservations"), 200).json() == {"reservations": [created]}
    assert assert_status(create(ada, body(tables, party_size=5), key), 200).json() == created


@pytest.mark.parametrize("tables,party,status,code", [
    ({"table_id": "t_1", "table_ids": ["t_1", "t_2"]}, 2, 422, "validation_failed"),
    ({"table_id": "t_1", "table_ids": ["t_1", "t_2"], "starts_at_local": 1900}, 2, 422, "validation_failed"),
    ({"table_ids": "t_1"}, 2, 400, "malformed_request"),
    ({"table_ids": ["t_1", 2]}, 2, 400, "malformed_request"),
    ({"table_ids": []}, 2, 422, "validation_failed"),
    ({"table_ids": ["t" * 65]}, 2, 422, "validation_failed"),
    ({"table_ids": ["t_1", "t_1"]}, 2, 422, "validation_failed"),
    ({"table_ids": ["t_1", "t_1", "t_2"]}, 2, 422, "validation_failed"),
    ({"table_ids": ["t_1", "t_2", "t_3"]}, 2, 422, "combination_not_allowed"),
    ({"table_ids": ["t_7", "t_8", "t_9"]}, 2, 422, "combination_not_allowed"),
    ({"table_ids": ["t_1", "t_9"]}, 2, 404, "not_found"),
    ({"table_ids": ["t_1", "t_x"]}, 2, 404, "not_found"),
    ({"table_ids": ["t_1", "t_3"]}, 2, 422, "combination_not_allowed"),
    ({"table_ids": ["t_1", "t_2"], "starts_at_local": "__OFF_GRID__"}, 2, 422, "not_on_slot_grid"),
    ({"table_ids": ["t_1", "t_2"]}, 7, 422, "party_exceeds_capacity"),
], ids=["both_fields", "both_fields_before_wrong_type", "not_a_list", "member_not_a_string",
        "empty", "id_65_chars", "duplicate", "duplicate_before_count", "three_tables",
        "three_unknown_tables", "unknown_member", "other_restaurants_table", "not_transitive",
        "off_grid_pair", "summed_capacity_exceeded"])
def test_a_table_set_that_breaks_a_rule_is_refused_and_leaves_nothing(pairs, anon, tables, party,
                                                                     status, code):
    """R259/R261/R262/R264/R265/R253/E3: each rule's status and code in E3 order; the
    refused request creates nothing."""
    ada, _ = pairs
    payload = body({k: v for k, v in tables.items() if k != "starts_at_local"}, party_size=party)
    if "starts_at_local" in tables:
        off = tables["starts_at_local"]
        payload["starts_at_local"] = at("19:15") if off == "__OFF_GRID__" else off
    before = availability(anon, 1)
    assert_error(create(ada, payload), status, code)
    assert assert_status(ada.get("/reservations"), 200).json() == {"reservations": []}
    assert availability(anon, 1) == before


def test_a_pair_fits_the_summed_capacity_only(pairs):
    """R254/R264: a party too big for either member alone books the pair up to its summed
    capacity."""
    ada, _ = pairs
    assert_error(create(ada, body({"table_id": "t_2"}, party_size=6)), 422, "party_exceeds_capacity")
    assert_shape(assert_status(create(ada, body({"table_ids": ["t_1", "t_2"]}, party_size=6)),
                               201).json(), ["t_1", "t_2"])
    assert_error(create(ada, body({"table_ids": ["t_3", "t_2"]}, "21:00", party_size=11)), 422,
                 "party_exceeds_capacity")
    assert_status(create(ada, body({"table_ids": ["t_3", "t_2"]}, "21:00", party_size=10)), 201)


@pytest.mark.parametrize("taken", ["t_1", "t_2"])
def test_a_pair_is_refused_when_any_member_is_taken(pairs, taken):
    """R263/R250: any member taken for an overlapping interval is 409 table_unavailable;
    a member booked by a pair refuses a single on it."""
    ada, bob = pairs
    assert_status(create(bob, body({"table_id": taken}, "19:30")), 201)
    assert_error(create(ada, body({"table_ids": ["t_1", "t_2"]}, "19:00")), 409, "table_unavailable")
    assert_status(create(ada, body({"table_ids": ["t_3", "t_2"]}, "12:00", party_size=8)), 201)
    assert_error(create(bob, body({"table_id": "t_3"}, "12:30")), 409, "table_unavailable")


def test_cancelling_a_pair_frees_both_tables(pairs, anon):
    """R267: cancelling frees every table in the set, at once."""
    ada, bob = pairs
    pair = assert_status(create(ada, body({"table_ids": ["t_1", "t_2"]}, party_size=5)), 201).json()
    cancelled = assert_status(ada.post(f"/reservations/{pair['reference']}/cancel"), 200).json()
    assert cancelled["status"] == "cancelled"
    assert_shape(cancelled, ["t_1", "t_2"])
    seven = next(s for s in availability(anon, 1) if s["starts_at_local"].endswith("19:00"))
    assert {"table_ids": ["t_1", "t_2"], "capacity": 6} in seven["available_options"]
    for table in ("t_1", "t_2"):
        assert_status(create(bob, body({"table_id": table})), 201)


# ---- PATCH (API, R266, E9) ------------------------------------------------------------------------

def test_patch_moves_between_a_single_and_a_pair(pairs):
    """R266/E9: PATCH takes `table_ids` under the same rules: single to pair, the same pair
    reversed as a no-op, `table_id` on a pair as a set of one; identity survives."""
    ada, _ = pairs
    booking = assert_status(create(ada, body({"table_id": "t_1"})), 201).json()
    ref = booking["reference"]
    paired = assert_status(ada.patch(f"/reservations/{ref}", json={"table_ids": ["t_2", "t_1"]}), 200).json()
    assert_shape(paired, ["t_1", "t_2"])
    assert (paired["reservation_id"], paired["reference"], paired["created_at"]) == \
        (booking["reservation_id"], ref, booking["created_at"])
    again = assert_status(ada.patch(f"/reservations/{ref}", json={"table_ids": ["t_1", "t_2"]}), 200).json()
    assert again == paired
    single = assert_status(ada.patch(f"/reservations/{ref}", json={"table_id": "t_3"}), 200).json()
    assert_shape(single, ["t_3"])


@pytest.mark.parametrize("change,status,code", [
    ({"table_id": "t_3", "table_ids": ["t_1", "t_2"]}, 422, "validation_failed"),
    ({"table_ids": ["t_1", "t_3"]}, 422, "combination_not_allowed"),
    ({"table_ids": ["t_1", "t_2", "t_3"]}, 422, "combination_not_allowed"),
    ({"table_ids": ["t_1", "t_1"]}, 422, "validation_failed"),
    ({"table_ids": ["t_3", "t_2"], "party_size": 11}, 422, "party_exceeds_capacity"),
    ({"table_ids": ["t_3", "t_2"]}, 409, "table_unavailable"),
], ids=["both_fields", "undeclared_pair", "three_tables", "duplicate", "summed_capacity",
        "member_taken"])
def test_a_refused_patch_leaves_the_booking_and_its_tables(pairs, anon, change, status, code):
    """R266/R117: PATCH refusals follow the create rules and change nothing."""
    ada, bob = pairs
    ref = assert_status(create(ada, body({"table_id": "t_1"})), 201).json()["reference"]
    assert_status(create(bob, body({"table_id": "t_3"}, "19:30")), 201)
    before = (assert_status(ada.get(f"/reservations/{ref}"), 200).json(), availability(anon, 1))
    assert_error(ada.patch(f"/reservations/{ref}", json=change), status, code)
    assert (ada.get(f"/reservations/{ref}").json(), availability(anon, 1)) == before


# ---- moves (API, R272) --------------------------------------------------------------------------------

def test_a_move_swaps_a_pair_and_a_single(pairs, anon):
    """R272/R260: move items take `table_ids`; a pair and a single swap tables in one
    batch; the answer keeps input order and each item's shape."""
    ada, _ = pairs
    pair = assert_status(create(ada, body({"table_ids": ["t_1", "t_2"]}, party_size=5)), 201).json()
    single = assert_status(create(ada, body({"table_id": "t_3"}, party_size=5)), 201).json()
    moved = assert_status(ada.post("/reservation-moves", idempotency_key=new_key(), json={"moves": [
        {"reference": pair["reference"], "table_id": "t_3"},
        {"reference": single["reference"], "table_ids": ["t_2", "t_1"]}]}), 201).json()["reservations"]
    assert [m["reference"] for m in moved] == [pair["reference"], single["reference"]]
    assert_shape(moved[0], ["t_3"])
    assert_shape(moved[1], ["t_1", "t_2"])
    seven = next(s for s in availability(anon, 1) if s["starts_at_local"].endswith("19:00"))
    assert seven["available_options"] == []


def test_a_move_onto_a_taken_member_changes_nothing(pairs, anon):
    """R272/R150/R151: no table may belong to overlapping resulting bookings; a refused
    batch changes nothing; an item naming both fields is 422."""
    ada, bob = pairs
    single = assert_status(create(ada, body({"table_id": "t_3"}, "12:00")), 201).json()
    other = assert_status(create(ada, body({"table_id": "t_1"}, "12:00")), 201).json()
    assert_status(create(bob, body({"table_id": "t_2"}, "19:30")), 201)
    before = (ada.get("/reservations").json(), availability(anon, 1))
    assert_error(ada.post("/reservation-moves", idempotency_key=new_key(), json={"moves": [
        {"reference": other["reference"], "starts_at_local": at("13:30")},
        {"reference": single["reference"], "table_ids": ["t_1", "t_2"],
         "starts_at_local": at("19:00")}]}), 409, "table_unavailable")
    assert_error(ada.post("/reservation-moves", idempotency_key=new_key(), json={"moves": [
        {"reference": single["reference"], "table_id": "t_1", "table_ids": ["t_1", "t_2"]}]}),
        422, "validation_failed")
    assert (ada.get("/reservations").json(), availability(anon, 1)) == before


# ---- table-set occupancy after every writer (critic B1) -------------------------------------------------

def test_availability_equals_the_reference_after_every_writer(reset, api, anon, base_url):
    """R250/R267/R266/R272/R7: after each writer that makes or changes a table set -- a
    seeded pair, a created pair, PATCH pair to single and single to pair, cancel of a pair,
    a move swapping a pair and a single, an import of the export -- availability equals
    the reference in singles and options; a create on each occupied member at an
    overlapping time is 409, on each freed member 201."""
    reset(fx.fixture(restaurants=[restaurant()], reservations=[
        seed("SEEDP1", at_time="18:00", table_ids=["t_1", "t_2"], party_size=5)]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    bob = api().authenticate(fx.BOB["email"], fx.BOB["password"])
    booked = {"t_1": [minutes("18:00")], "t_2": [minutes("18:00")], "t_3": []}

    def matches(step: str) -> None:
        for party in (1, 5):
            assert shown(availability(anon, party)) == reference(booked, party), f"after {step}, party {party}"

    def single(client, table: str, hhmm: str, expected: int) -> None:
        resp = create(client, body({"table_id": table}, hhmm))
        assert resp.status_code == expected, (table, hhmm, resp.status_code, resp.text[:200])
        if expected == 201:
            booked[table].append(minutes(hhmm))

    def move(table: str, old: str, new_table: str, new: str) -> None:
        booked[table].remove(minutes(old))
        booked[new_table].append(minutes(new))

    matches("a seeded pair")
    single(bob, "t_1", "18:30", 409)
    single(bob, "t_2", "19:00", 409)
    created = assert_status(create(ada, body({"table_ids": ["t_2", "t_3"]}, "20:00", 6)), 201).json()
    assert_shape(created, ["t_3", "t_2"])
    ref = created["reference"]
    booked["t_3"].append(minutes("20:00"))
    booked["t_2"].append(minutes("20:00"))
    matches("a created pair")
    single(bob, "t_3", "21:00", 409)
    single(bob, "t_2", "19:30", 409)
    assert_status(ada.patch(f"/reservations/{ref}", json={"table_id": "t_3"}), 200)
    booked["t_2"].remove(minutes("20:00"))
    matches("PATCH pair to single")
    single(bob, "t_2", "21:00", 201)
    single(bob, "t_3", "20:30", 409)
    assert_status(ada.patch(f"/reservations/{ref}", json={
        "table_ids": ["t_2", "t_1"], "starts_at_local": at("19:30")}), 200)
    move("t_3", "20:00", "t_1", "19:30")
    booked["t_2"].append(minutes("19:30"))
    matches("PATCH single to pair")
    single(bob, "t_3", "20:30", 201)
    single(bob, "t_1", "20:00", 409)
    assert_status(ada.post("/reservations/SEEDP1/cancel"), 200)
    booked["t_1"].remove(minutes("18:00"))
    booked["t_2"].remove(minutes("18:00"))
    matches("cancel of a pair")
    single(bob, "t_1", "18:00", 201)
    single(bob, "t_2", "17:30", 201)
    pair = assert_status(create(ada, body({"table_ids": ["t_1", "t_2"]}, "12:00", 5)), 201).json()
    one = assert_status(create(ada, body({"table_id": "t_3"}, "13:00", 5)), 201).json()
    for table, hhmm in (("t_1", "12:00"), ("t_2", "12:00"), ("t_3", "13:00")):
        booked[table].append(minutes(hhmm))
    matches("two creates")
    assert_status(ada.post("/reservation-moves", idempotency_key=new_key(), json={"moves": [
        {"reference": pair["reference"], "table_id": "t_3"},
        {"reference": one["reference"], "table_ids": ["t_1", "t_2"]}]}), 201)
    move("t_1", "12:00", "t_1", "13:00")
    move("t_2", "12:00", "t_2", "13:00")
    move("t_3", "13:00", "t_3", "12:00")
    matches("a move swapping a pair and a single")
    single(bob, "t_3", "14:00", 201)
    single(bob, "t_1", "14:00", 409)
    exported = assert_status(anon.get("/_test/export", timeout=RESET_TIMEOUT), 200).json()
    reset(fx.fixture())
    assert_status(anon.post("/_test/import", json=exported, timeout=RESET_TIMEOUT), 204)
    matches("an import of the export")
    single(bob, "t_2", "13:30", 409)
    single(bob, "t_3", "16:00", 201)
    matches("a create after the import")


# ---- receipts and odd input ---------------------------------------------------------------------------

def test_a_pair_receipt_replays_after_changes_and_after_import(pairs, anon):
    """R273/R82/R138: a combined booking's receipt replays its original body after a
    PATCH and a cancel, and after export and import."""
    ada, _ = pairs
    key = new_key()
    payload = body({"table_ids": ["t_2", "t_1"]}, party_size=5)
    original = assert_status(create(ada, payload, key), 201).json()
    assert_status(ada.patch(f"/reservations/{original['reference']}", json={"table_id": "t_3"}), 200)
    assert_status(ada.post(f"/reservations/{original['reference']}/cancel"), 200)
    assert assert_status(create(ada, payload, key), 200).json() == original
    exported = assert_status(anon.get("/_test/export", timeout=RESET_TIMEOUT), 200).json()
    assert_status(anon.post("/_test/import", json=exported, timeout=RESET_TIMEOUT), 204)
    assert assert_status(create(ada, payload, key), 200).json() == original


ODD = [{"table_ids": None}, {"table_ids": {"0": "t_1"}}, {"table_ids": [["t_1"], ["t_2"]]},
       {"table_ids": ["t_1"] * 1000}, {"table_ids": ["\u0000", "éé"]}, {"table_ids": [True, False]}]


@pytest.mark.parametrize("tables", ODD, ids=[f"o{i}" for i in range(len(ODD))])
def test_odd_table_sets_never_answer_5xx(pairs, tables):
    """R60: requests must not produce 5xx; a refusal carries the error envelope."""
    ada, _ = pairs
    for resp in (create(ada, body(tables)),
                 ada.patch("/reservations/NOPE99", json=tables),
                 ada.post("/reservation-moves", idempotency_key=new_key(),
                          json={"moves": [{"reference": "NOPE99", **tables}]})):
        assert resp.status_code < 500, f"{resp.request.method} -> {resp.status_code} {resp.text[:200]}"
        if resp.status_code >= 400:
            error_code(resp)
