"""S4-I2 acceptance checks (verifier seat): the closure preview, from the stage-4
specification's "Seating changes after a table closure" (R402-R421, R423-R425, R445) with the
plan's Q1-Q12 and Q24 and the stage-1 keyed-write rules (D2, D3, D10, D11, D12).

The generated brute-force comparison is in test_s4_i2_planner.py and the worst cases' timing in
test_s4_i2_worst.py. Uses a second stage-4 service (TABLEKEEPER_SECOND_URL) and the stage-3
service of the same checkout (TABLEKEEPER_STAGE3_URL), and resets them: run it alone against
other files that reset them.
"""
from __future__ import annotations

import copy
import datetime as dt
import os
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import fixtures as fx
from harness.http import RESET_TIMEOUT, Api, assert_error, assert_status, new_key

pytestmark = pytest.mark.stage(4)

DATE = fx.booking_date()
BERLIN = ZoneInfo("Europe/Berlin")
PATH = "/restaurants/r_anker/replans"


def instant(hhmm: str, date: str = DATE) -> dt.datetime:
    return dt.datetime.combine(dt.date.fromisoformat(date), dt.time.fromisoformat(hhmm), tzinfo=BERLIN)


def closure(table: str = "t_2", start: str = "18:00", end: str = "23:00", date: str = DATE, **extra) -> dict:
    return {"table_id": table, "from": instant(start, date).isoformat(), "to": instant(end, date).isoformat(),
            **extra}


def restaurant(caps=(2, 4, 6), pairs=(), rid="r_anker", manager="u_ada", **kw) -> dict:
    tables = [{"id": f"t_{i}", "label": str(i), "capacity": c} for i, c in enumerate(caps, 1)]
    return {**fx.restaurant(rid, tables=tables, opening_hours=fx.all_week("12:00", "23:30"), **kw),
            "manager_user_ids": [manager], "combinable": [list(p) for p in pairs]}


def seed(reference, tables, hhmm="19:00", party=2, status="confirmed", rid="r_anker", date=DATE) -> dict:
    return {"id": f"res_{reference}", "reference": reference, "user_id": "u_bob", "restaurant_id": rid,
            **({"table_id": tables[0]} if len(tables) == 1 else {"table_ids": list(tables)}),
            "starts_at_local": fx.local(date, hhmm), "party_size": party, "status": status}


@pytest.fixture
def make(reset, api, base_url):
    """A reset world: r_anker (managed by ada) as given, r_other (managed by bob) with t_1..t_4."""
    def build(caps=(2, 4, 6), pairs=(), seeds=(), **kw):
        reset(fx.fixture(restaurants=[restaurant(caps, pairs, **kw),
                                      restaurant((2, 4, 6, 8), rid="r_other", manager="u_bob", name="Zum Anderen")],
                         reservations=list(seeds)))
        return SimpleNamespace(ada=api().authenticate(fx.ADA["email"], fx.ADA["password"]),
                               bob=api().authenticate(fx.BOB["email"], fx.BOB["password"]), base=base_url)
    return build


def preview(client, body, key=None, path=PATH):
    return client.post(path, json=body, idempotency_key=key or new_key())


def planned(client, body, key=None) -> dict:
    return assert_status(preview(client, body, key), 201).json()


def seats(plan: dict) -> list[tuple[str, list[str], bool]]:
    return [(a["reference"], a["table_ids"], a["changed"]) for a in plan["assignments"]]


def publish(world, date=DATE, **overrides):
    body = fx.policy(date, opening_hours=fx.all_week("12:00", "23:30"), **overrides)
    return assert_status(world.ada.post("/restaurants/r_anker/policies", idempotency_key=new_key(), json=body), 201)


def create(world, tables, hhmm, party, date=DATE) -> str:
    body = {"restaurant_id": "r_anker", "starts_at_local": fx.local(date, hhmm), "party_size": party,
            **({"table_id": tables[0]} if len(tables) == 1 else {"table_ids": list(tables)})}
    return assert_status(world.bob.post("/reservations", idempotency_key=new_key(), json=body), 201).json()["reference"]


def exported(base: str) -> dict:
    with Api(base, timeout=RESET_TIMEOUT) as control:
        return assert_status(control.get("/_test/export"), 200).json()


def url(name: str) -> str:
    value = os.environ.get(name)
    assert value, f"set {name} to the service of the same checkout"
    return value.rstrip("/")


def revision(base: str, rid: str = "r_anker") -> int:
    return next(r["revision"] for r in exported(base)["state"]["restaurants"] if r["id"] == rid)


# ---- the keyed write (R405, D3, D10, D11) ------------------------------------------------------------------

def test_the_keyed_write_basics_come_first(make):
    """R405/D3/Q3: no token is 401 (even for an unknown restaurant or an invalid body); a body
    that is not a JSON object is 400; a missing key 400; a key over 255 characters 422; the
    same key and body replays 200 with the original body; the same key with another body is
    409 idempotency_key_reuse even when that body is invalid; a refused first use leaves the
    key unused (D11)."""
    world = make(seeds=[seed("MOVE01", ["t_2"])])
    anon = Api(world.base)
    assert_error(anon.post(PATH, json=closure(), idempotency_key=new_key()), 401, "unauthenticated")
    assert_error(anon.post("/restaurants/r_nope/replans", json={"table_id": 5}, idempotency_key=new_key()),
                 401, "unauthenticated")
    for raw in ("[]", "{", '"text"', "null"):
        assert_error(world.ada.post(PATH, content=raw, idempotency_key=new_key()), 400, "malformed_request")
    assert_error(world.ada.post(PATH, json=closure()), 400, "missing_idempotency_key")
    assert_error(preview(world.ada, closure(), key="k" * 256), 422, "validation_failed")
    key = new_key()
    original = planned(world.ada, closure(), key)
    assert assert_status(preview(world.ada, closure(), key), 200).json() == original
    assert_error(preview(world.ada, closure(table="t_1"), key), 409, "idempotency_key_reuse")
    assert_error(preview(world.ada, closure(start="23:00", end="18:00"), key), 409, "idempotency_key_reuse")
    fresh_key = new_key()
    assert_error(preview(world.ada, closure(table="t_9"), fresh_key), 404, "not_found")
    assert_status(preview(world.ada, closure(), fresh_key), 201)


def test_a_replay_returns_the_original_plan_even_after_later_writes(make):
    """Q11/R423: a replayed preview returns its original 201 body with 200 after later writes
    changed the restaurant, and raises nothing."""
    world = make(seeds=[seed("MOVE01", ["t_2"])])
    key = new_key()
    original = planned(world.ada, closure(), key)
    create(world, ["t_1"], "19:00", 2)
    before = exported(world.base)
    assert assert_status(preview(world.ada, closure(), key), 200).json() == original
    assert exported(world.base) == before


# ---- who may preview, and in what order (Q3, P2) -----------------------------------------------------------

def test_an_unknown_restaurant_is_404_before_the_permission_and_the_fields(make):
    world = make()
    for body in (closure(), {"table_id": 5}, {}):
        assert_error(preview(world.ada, body, path="/restaurants/r_nope/replans"), 404, "not_found")


def test_only_a_manager_of_this_restaurant_may_preview_before_the_fields_are_read(make):
    """R405/Q3: a signed-in diner who manages no restaurant, and the manager of another
    restaurant, are 403 forbidden, even with an invalid body or an unknown table; nothing is
    stored."""
    world = make(seeds=[seed("MOVE01", ["t_2"])])
    before = exported(world.base)
    for body in (closure(), {"table_id": 5}, closure(table="t_9"), closure(start="23:00", end="18:00")):
        assert_error(preview(world.bob, body), 403, "forbidden")
        assert_error(preview(world.ada, body, path="/restaurants/r_other/replans"), 403, "forbidden")
    assert exported(world.base)["state"]["plans"] == before["state"]["plans"] == []


def naive(hhmm):
    return instant(hhmm).replace(tzinfo=None).isoformat()


INVALID = {
    "table_id_missing": lambda: {k: v for k, v in closure().items() if k != "table_id"},
    "table_id_number": lambda: closure(table=2),
    "table_id_null": lambda: closure(table=None),
    "table_id_true": lambda: closure(table=True),
    "table_id_list": lambda: closure(table=["t_2"]),
    "table_id_empty": lambda: closure(table=""),
    "table_id_65_characters": lambda: closure(table="t" * 65),
    "from_missing": lambda: {k: v for k, v in closure(table="t_9").items() if k != "from"},
    "to_missing": lambda: {k: v for k, v in closure(table="t_9").items() if k != "to"},
    "from_naive": lambda: {**closure(table="t_9"), "from": naive("18:00")},
    "to_naive": lambda: {**closure(table="t_9"), "to": naive("23:00")},
    "from_date_only": lambda: {**closure(table="t_9"), "from": DATE},
    "to_unparseable": lambda: {**closure(table="t_9"), "to": "tonight at eleven"},
    "from_number": lambda: {**closure(table="t_9"), "from": 1790000000},
    "to_null": lambda: {**closure(table="t_9"), "to": None},
    "from_equals_to": lambda: closure(table="t_9", start="19:00", end="19:00"),
    "from_after_to": lambda: closure(table="t_9", start="21:00", end="19:00"),
    "same_instant_other_offsets": lambda: {"table_id": "t_9", "from": instant("19:00").isoformat(),
                                           "to": instant("19:00").astimezone(dt.timezone.utc).isoformat()},
}


@pytest.mark.parametrize("case", list(INVALID))
def test_invalid_fields_are_422_before_the_unknown_table(make, case):
    """R407/Q3/D12: `table_id` a string of 1-64 characters; `from` and `to` instants with an
    explicit offset, `from` before `to` (the same instant in two offsets is not before);
    each violation is 422 validation_failed - ahead of the unknown table `t_9` - and stores
    nothing."""
    world = make(seeds=[seed("MOVE01", ["t_2"])])
    before = exported(world.base)
    assert_error(preview(world.ada, INVALID[case]()), 422, "validation_failed")
    assert exported(world.base) == before


def test_an_unknown_table_is_404_and_stores_nothing(make):
    """R407/Q3: a table the restaurant does not have (another restaurant's `t_4`, an unknown
    `t_9`) is 404 not_found with a valid interval."""
    world = make(seeds=[seed("MOVE01", ["t_2"])])
    before = exported(world.base)
    for table in ("t_4", "t_9"):
        assert_error(preview(world.ada, closure(table=table)), 404, "not_found")
    assert exported(world.base) == before


FORMS = {
    "offset_with_seconds": lambda at: at.isoformat(),
    "utc_z": lambda at: at.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
    "another_offset": lambda at: at.astimezone(dt.timezone(dt.timedelta(hours=-3, minutes=-30))).isoformat(),
    "space_separator": lambda at: at.isoformat(sep=" "),
    "no_seconds": lambda at: at.isoformat(timespec="minutes"),
    "fractional_seconds": lambda at: at.isoformat(timespec="milliseconds"),
}


@pytest.mark.parametrize("form", list(FORMS))
def test_every_offset_form_names_the_same_interval_and_is_echoed_as_written(make, form):
    """R406/R407/Q3 (v2.6 ruling)/Q7: `from` and `to` in any ISO 8601 form with an explicit
    offset (Z, another offset, a space for T, no seconds) are accepted and name the same
    instants: a booking ending at `from` and one starting at `to` stay out, the ones inside
    are considered; `closure` echoes the strings verbatim."""
    world = make(seeds=[seed("ENDS01", ["t_2"], "17:30"), seed("INSD01", ["t_2"], "19:30"),
                        seed("STRT01", ["t_2"], "21:00")])
    body = {"table_id": "t_2", "from": FORMS[form](instant("19:00")), "to": FORMS[form](instant("21:00"))}
    plan = planned(world.ada, body)
    assert plan["closure"] == body
    assert seats(plan) == [("INSD01", ["t_1"], True)]


def test_unknown_fields_are_ignored(make):
    """R445 (by rule): unknown body fields, even ones named like other endpoints' fields, change
    nothing about the plan."""
    world = make(seeds=[seed("MOVE01", ["t_2"])])
    plain = planned(world.ada, closure())
    extra = planned(world.ada, closure(table_ids=["t_1"], restaurant_id="r_other", note={"x": 1}))
    assert {**extra, "plan_id": None} == {**plain, "plan_id": None}
    assert extra["closure"] == {k: closure()[k] for k in ("table_id", "from", "to")}


# ---- the response (R420, R421, Q7, Q9, Q11) ------------------------------------------------------------------

def test_the_response_has_the_specified_shape_and_distinct_opaque_ids(make):
    """R420/R421/Q7/Q9/Q11: 201 with exactly plan_id (a non-empty string), restaurant_revision,
    closure (the request's three fields as written), assignments (reference, table_ids,
    changed), moved_count and unused_seats; two previews of one body have different ids."""
    world = make(seeds=[seed("MOVE01", ["t_2"], party=3)])
    body = closure()
    first, second = planned(world.ada, body), planned(world.ada, body)
    assert set(first) == {"plan_id", "restaurant_revision", "closure", "assignments", "moved_count", "unused_seats"}
    assert isinstance(first["plan_id"], str) and first["plan_id"] and first["plan_id"] != second["plan_id"]
    assert first["closure"] == body
    assert first["assignments"] == [{"reference": "MOVE01", "table_ids": ["t_3"], "changed": True}]
    assert (first["moved_count"], first["unused_seats"], first["restaurant_revision"]) == (1, 3, 0)
    assert {**second, "plan_id": None} == {**first, "plan_id": None}


def test_the_plan_reports_the_current_revision_and_does_not_raise_it(make):
    """R420/R423/Q5/Q12: after two creates and a publication the preview reports revision 3,
    and the export still says 3 after two previews."""
    world = make(seeds=[seed("MOVE01", ["t_2"])])
    create(world, ["t_1"], "12:00", 2)
    create(world, ["t_3"], "12:00", 2)
    publish(world, fx.booking_date(lead=21))
    assert revision(world.base) == 3
    assert planned(world.ada, closure())["restaurant_revision"] == 3
    assert planned(world.ada, closure(table="t_1"))["restaurant_revision"] == 3
    assert revision(world.base) == 3


# ---- which bookings are considered (R408, R409, R410, Q1, Q6, Q10) -------------------------------------------

def test_every_confirmed_overlapping_booking_is_considered_on_any_table(make):
    """R408/R409/R410/Q1/Q6/Q10: closing t_2 over [19:00, 21:00) considers the booking on t_2
    inside it (moved) and the one on t_1 that overlaps it (kept, changed false); not one that
    ends at 19:00 or starts at 21:00, not a cancelled one (which blocks nothing either), not
    another restaurant's."""
    world = make(seeds=[seed("ONT201", ["t_2"], "19:30", party=3), seed("OTHR01", ["t_1"], "20:00"),
                        seed("ENDS01", ["t_3"], "17:30"), seed("STRT01", ["t_3"], "21:00"),
                        seed("GONE01", ["t_3"], "19:30", status="cancelled"),
                        seed("ELSE01", ["t_2"], "19:30", rid="r_other")])
    plan = planned(world.ada, closure(start="19:00", end="21:00"))
    assert seats(plan) == [("ONT201", ["t_3"], True), ("OTHR01", ["t_1"], False)]
    assert (plan["moved_count"], plan["unused_seats"]) == (1, 3)


def test_a_booking_is_considered_for_its_own_accepted_duration(make):
    """Q1/Q6/H1: a booking made under a 150-minute policy at 18:00 lasts until 20:30, so closing
    t_1 from 20:00 considers it (kept on t_3); a 90-minute reading would miss it."""
    world = make(seeds=[seed("MOVE01", ["t_1"], "20:00")])
    publish(world, reservation_duration_minutes=150)
    long_one = create(world, ["t_3"], "18:00", 2)
    plan = planned(world.ada, closure(table="t_1", start="20:00", end="21:00"))
    assert seats(plan) == sorted([("MOVE01", ["t_2"], True), (long_one, ["t_3"], False)])


def test_fixed_bookings_block_for_their_own_durations(make):
    """R414/Q8/Q10/H1: a fixed booking made under a 150-minute policy at 17:00 holds t_3 until
    19:30, so the booking closed out of t_2 at 19:00 (party 3) goes to t_4 (8 seats), not to
    t_3; one made at 16:00 (ends 18:30) leaves t_3 free for it."""
    world = make(caps=(2, 4, 6, 8), seeds=[seed("MOVE01", ["t_2"], "19:00", party=3)])
    publish(world, reservation_duration_minutes=150, capacities={"t_1": 2, "t_2": 4, "t_3": 6, "t_4": 8})
    create(world, ["t_3"], "17:00", 2)
    plan = planned(world.ada, closure(start="19:30", end="23:00"))
    assert seats(plan) == [("MOVE01", ["t_4"], True)] and plan["unused_seats"] == 5
    world = make(caps=(2, 4, 6, 8), seeds=[seed("MOVE01", ["t_2"], "19:00", party=3)])
    publish(world, reservation_duration_minutes=150, capacities={"t_1": 2, "t_2": 4, "t_3": 6, "t_4": 8})
    create(world, ["t_3"], "16:00", 2)
    plan = planned(world.ada, closure(start="19:30", end="23:00"))
    assert seats(plan) == [("MOVE01", ["t_3"], True)] and plan["unused_seats"] == 3


# ---- where a booking may go (R412, R413, R414, R415, Q8) -------------------------------------------------------

def test_capacity_comes_from_the_bookings_own_accepted_terms(make):
    """R413/Q8: a party of 4 booked under policy 0 (t_1 2, t_3 6 seats) keeps those capacities
    after a policy for its date gives t_1 4 and t_3 2 seats: it goes to t_3 with 2 unused."""
    world = make(seeds=[seed("MOVE01", ["t_2"], party=4)])
    publish(world, capacities={"t_1": 4, "t_2": 4, "t_3": 2})
    plan = planned(world.ada, closure())
    assert seats(plan) == [("MOVE01", ["t_3"], True)] and plan["unused_seats"] == 2


def test_a_newer_booking_uses_its_own_newer_capacities(make):
    """R413/Q8: the other way round - a party of 4 booked under a policy giving t_1 4 seats may
    go to t_1 (0 unused) though policy 0 gives it 2."""
    world = make()
    publish(world, capacities={"t_1": 4, "t_2": 4, "t_3": 6})
    moved = create(world, ["t_2"], "19:00", 4)
    plan = planned(world.ada, closure())
    assert seats(plan) == [(moved, ["t_1"], True)] and plan["unused_seats"] == 0


def test_a_cutoff_does_not_stop_a_repair(make):
    """R415: a booking already inside its cancellation cutoff (7 days, tomorrow) is still moved."""
    tomorrow = fx.booking_date(lead=1)
    world = make(seeds=[seed("MOVE01", ["t_2"], date=tomorrow)], cancellation_cutoff_minutes=10080)
    plan = planned(world.ada, closure(date=tomorrow))
    assert seats(plan) == [("MOVE01", ["t_1"], True)]


def test_nobody_is_seated_on_the_closed_table_during_the_closure(make):
    """R414: a booking on t_1 overlapping the closure of t_1 must move even though staying is
    cheapest; t_1 is not offered to anyone overlapping [from, to)."""
    world = make(caps=(6, 4, 6), seeds=[seed("MOVE01", ["t_1"], party=4), seed("KEEP01", ["t_3"], party=4)])
    plan = planned(world.ada, closure(table="t_1"))
    assert seats(plan) == [("KEEP01", ["t_3"], False), ("MOVE01", ["t_2"], True)]


def test_overlapping_bookings_never_share_a_table_but_successive_ones_may(make):
    """R414: two bookings closed out of t_2 and t_1 at the same time need two tables; two that
    follow each other on t_2 may both go to t_3."""
    world = make(caps=(2, 2, 2, 2), seeds=[seed("AAAA01", ["t_1"]), seed("BBBB01", ["t_2"])])
    plan = planned(world.ada, closure(table="t_2"))
    assert seats(plan) == [("AAAA01", ["t_1"], False), ("BBBB01", ["t_3"], True)]
    world = make(caps=(1, 2, 2), seeds=[seed("AAAA01", ["t_2"], "18:00"), seed("BBBB01", ["t_2"], "19:30")])
    plan = planned(world.ada, closure(table="t_2"))
    assert seats(plan) == [("AAAA01", ["t_3"], True), ("BBBB01", ["t_3"], True)]


# ---- the objective (R417, R418, R419, Q8, Q9) -------------------------------------------------------------------

def test_fewest_moves_come_first(make):
    """R417: moving only the closed-out booking to t_3 (5 unused) beats moving two bookings
    that would leave no seat unused."""
    world = make(caps=(2, 2, 6, 1), seeds=[seed("BBBB01", ["t_2"], party=2), seed("OOOO01", ["t_1"], party=1)])
    plan = planned(world.ada, closure())
    assert seats(plan) == [("BBBB01", ["t_3"], True), ("OOOO01", ["t_1"], False)]
    assert (plan["moved_count"], plan["unused_seats"]) == (1, 5)


def test_then_the_fewest_unused_seats(make):
    """R418: among one-move plans, t_3 (2 seats, 0 unused) beats t_1 (6 seats, rank 0)."""
    world = make(caps=(6, 2, 2), seeds=[seed("MOVE01", ["t_2"], party=2)])
    plan = planned(world.ada, closure())
    assert seats(plan) == [("MOVE01", ["t_3"], True)] and plan["unused_seats"] == 0


def test_then_the_lowest_rank_with_singles_before_pairs(make):
    """R419/Q8: at equal moves and unused seats the single t_4 (rank 3) beats the pair t_3+t_1
    (rank 4); without t_4 the pair is chosen and named in its declared order."""
    world = make(caps=(2, 4, 2, 4), pairs=[("t_3", "t_1")], seeds=[seed("MOVE01", ["t_2"], party=4)])
    assert seats(planned(world.ada, closure())) == [("MOVE01", ["t_4"], True)]
    world = make(caps=(2, 4, 2), pairs=[("t_3", "t_1")], seeds=[seed("MOVE01", ["t_2"], party=4)])
    plan = planned(world.ada, closure())
    assert seats(plan) == [("MOVE01", ["t_3", "t_1"], True)] and plan["unused_seats"] == 0


def test_ties_go_to_the_least_rank_vector_in_reference_order(make):
    """R419/Q8: BOOK01 (closed out of t_3, party 3) must take t_1 or t_2 from OOOO01/OOOO02,
    which then goes to t_4: both plans move 2 and leave 1 seat unused. In reference order
    (BOOK01, OOOO01, OOOO02) the vector (0, 3, 1) beats (1, 0, 3), so BOOK01 gets t_1; in
    start order (OOOO01 18:30, OOOO02 19:00, BOOK01 19:30) the other plan would win."""
    world = make(caps=(3, 3, 3, 2), seeds=[seed("OOOO01", ["t_1"], "18:30", party=2),
                                           seed("OOOO02", ["t_2"], "19:00", party=2),
                                           seed("BOOK01", ["t_3"], "19:30", party=3)])
    plan = planned(world.ada, closure(table="t_3", start="19:00", end="23:00"))
    assert seats(plan) == [("BOOK01", ["t_1"], True), ("OOOO01", ["t_4"], True), ("OOOO02", ["t_2"], False)]
    assert (plan["moved_count"], plan["unused_seats"]) == (2, 1)


def test_a_pair_booking_keeps_its_declared_order_and_unused_seats_are_summed(make):
    """R418/Q9/E2: a pair booking on t_2+t_1 (declared that way) that is kept reads
    ["t_2", "t_1"], changed false; unused seats sum over every considered booking."""
    world = make(caps=(2, 4, 6, 3), pairs=[("t_2", "t_1")],
                 seeds=[seed("PAIR01", ["t_2", "t_1"], party=5), seed("MOVE01", ["t_3"], party=3)])
    plan = planned(world.ada, closure(table="t_3", start="18:30", end="20:00"))
    assert seats(plan) == [("MOVE01", ["t_4"], True), ("PAIR01", ["t_2", "t_1"], False)]
    assert (plan["moved_count"], plan["unused_seats"]) == (1, 1)


# ---- limits and infeasibility (R411, R425, Q2) ------------------------------------------------------------------

def overlapping(n):
    return [seed(f"OVER{i:02d}", [f"t_{i}"], "19:00", party=1) for i in range(1, n + 1)]


@pytest.mark.parametrize("case", ["seven_tables", "five_pairs", "seven_considered"])
def test_beyond_a_limit_is_422_planning_limit_changing_nothing(make, case):
    """R411/Q2: more than 6 tables, more than 4 declared pairs or more than 6 considered
    bookings is 422 planning_limit, and nothing is stored."""
    caps, pairs, seeds, body = (1,) * 6, (), [], closure(table="t_1", start="12:00", end="23:30")
    if case == "seven_tables":
        caps = (1,) * 7
    elif case == "five_pairs":
        pairs = [("t_1", "t_2"), ("t_2", "t_3"), ("t_3", "t_4"), ("t_4", "t_5"), ("t_5", "t_6")]
    else:
        seeds = [seed(f"LONG{i:02d}", ["t_2"], f"{12 + 2 * i:02d}:00", party=1) for i in range(5)] \
            + [seed("LATE01", ["t_3"], "20:00", party=1), seed("LATE02", ["t_4"], "20:00", party=1)]
    world = make(caps=caps, pairs=pairs, seeds=seeds)
    before = exported(world.base)
    assert_error(preview(world.ada, body), 422, "planning_limit")
    assert exported(world.base) == before


def test_exactly_at_the_limits_a_plan_is_made(make):
    """R411/Q2: 6 tables, 4 declared pairs and 6 considered bookings are planned (201)."""
    pairs = [("t_1", "t_2"), ("t_2", "t_3"), ("t_4", "t_5"), ("t_5", "t_6")]
    seeds = [seed(f"LONG{i:02d}", ["t_2"], f"{12 + 2 * i:02d}:00", party=1) for i in range(5)] \
        + [seed("LATE01", ["t_3"], "21:00", party=1)]
    world = make(caps=(1,) * 6, pairs=pairs, seeds=seeds)
    plan = planned(world.ada, closure(table="t_2", start="12:00", end="23:30"))
    assert [ref for ref, _, _ in seats(plan)] == sorted(s["reference"] for s in seeds)
    assert plan["moved_count"] == 5


def test_an_unknown_table_and_invalid_fields_come_before_the_limit(make):
    """Q3: with 7 tables an unknown table is still 404 and an invalid interval still 422."""
    world = make(caps=(1,) * 7)
    assert_error(preview(world.ada, closure(table="t_9")), 404, "not_found")
    assert_error(preview(world.ada, closure(start="21:00", end="19:00")), 422, "validation_failed")


def test_no_feasible_plan_is_409_changing_nothing_and_leaves_the_key_unused(make):
    """R425/Q3/D11: a party of 6 closed out of the only 6-seat table has nowhere to go: 409
    no_feasible_plan, the export unchanged; the key then serves a feasible body (201)."""
    world = make(seeds=[seed("MOVE01", ["t_3"], party=6), seed("MOVE02", ["t_2"], "12:00", party=2)])
    before = exported(world.base)
    key = new_key()
    assert_error(preview(world.ada, closure(table="t_3"), key), 409, "no_feasible_plan")
    assert exported(world.base) == before
    assert_status(preview(world.ada, closure(table="t_2", start="12:00", end="13:00"), key), 201)


# ---- a preview changes nothing else (R424, Q12) -----------------------------------------------------------------

def views(world) -> dict:
    """Everything a diner or the grid can read about r_anker's bookings on DATE."""
    read = {}
    for party in range(1, 7):
        for extra in ({}, {"explain": "true"}):
            response = assert_status(world.bob.get("/availability", params={
                "restaurant_id": "r_anker", "date": DATE, "party_size": party, **extra}), 200)
            read[f"availability {party} {extra}"] = response.content
    for reference in ("MOVE01", "KEEP01", "PAIR01"):
        read[reference] = assert_status(world.bob.get(f"/reservations/{reference}"), 200).json()
        read[f"{reference} history"] = assert_status(world.bob.get(f"/reservations/{reference}/history"), 200).json()
    read["list"] = assert_status(world.bob.get("/reservations"), 200).json()
    return read


def test_a_preview_changes_nothing_but_the_stored_plan(make):
    """R424/Q12/R423: after a preview that moves two bookings, every availability answer (plain
    and explained, parties 1-6) is byte-identical, every reservation, history and the list
    read the same, the restaurant revision is unchanged, and the export differs only by the
    stored plan and the preview's receipt."""
    world = make(caps=(2, 4, 6, 4), pairs=[("t_1", "t_4")],
                 seeds=[seed("MOVE01", ["t_2"], party=3), seed("KEEP01", ["t_3"], party=5),
                        seed("PAIR01", ["t_1", "t_4"], "21:00", party=5)])
    before, read = exported(world.base), views(world)
    plan = planned(world.ada, closure(table="t_2", start="19:00", end="20:30"))
    assert seats(plan) == [("KEEP01", ["t_3"], False), ("MOVE01", ["t_4"], True)]
    assert views(world) == read
    after = exported(world.base)
    assert {k: v for k, v in after["state"].items() if k not in ("plans", "receipts")} \
        == {k: v for k, v in before["state"].items() if k not in ("plans", "receipts")}
    assert {k: v for k, v in after.items() if k != "state"} == {k: v for k, v in before.items() if k != "state"}
    assert [p["plan_id"] for p in after["state"]["plans"]] == [plan["plan_id"]]
    assert len(after["state"]["receipts"]) == len(before["state"]["receipts"]) + 1
    assert all(receipt in after["state"]["receipts"] for receipt in before["state"]["receipts"])


# ---- export and import of stored plans (Q24, J6) -----------------------------------------------------------------

def test_stored_plans_restore_unchanged_in_another_stage_4_and_replay_there(make):
    """Q24/J6: the export carries the stored plans; imported into a second stage-4 it re-exports
    equal, and the preview's key replays there with the original body."""
    world = make(seeds=[seed("MOVE01", ["t_2"])])
    key = new_key()
    original = planned(world.ada, closure(), key)
    planned(world.ada, closure(table="t_1", start="12:00", end="13:00"))
    body = exported(world.base)
    assert len(body["state"]["plans"]) == 2
    second = url("TABLEKEEPER_SECOND_URL")
    with Api(second, timeout=RESET_TIMEOUT) as control:
        assert_status(control.post("/_test/import", json=body), 204)
    assert exported(second) == body
    with Api(second, token=world.ada.token) as ada2:
        assert assert_status(preview(ada2, closure(), key), 200).json() == original
    assert exported(second) == body


def test_an_earlier_stage_export_imports_with_no_plans(base_url):
    """Q24/J6: a stage-3 export imports into stage 4 with no stored plans."""
    with Api(url("TABLEKEEPER_STAGE3_URL"), timeout=RESET_TIMEOUT) as previous:
        assert_status(previous.post("/_test/reset", json=fx.fixture()), 204)
        body = assert_status(previous.get("/_test/export"), 200).json()
    with Api(base_url, timeout=RESET_TIMEOUT) as control:
        assert_status(control.post("/_test/import", json=body), 204)
    assert exported(base_url)["state"]["plans"] == []


BROKEN = {
    "unknown_restaurant": lambda p: p.update(restaurant_id="r_nope"),
    "unknown_booking": lambda p: p["assignments"][0].update(reference="NOPE99"),
    "not_a_table_or_pair": lambda p: p["assignments"][0].update(table_ids=["t_9"]),
    "changed_not_boolean": lambda p: p["assignments"][0].update(changed="yes"),
    "closure_from_after_to": lambda p: p["closure"].update({"from": p["closure"]["to"], "to": p["closure"]["from"]}),
    "closure_naive": lambda p: p["closure"].update({"from": naive("18:00")}),
    "plan_id_missing": lambda p: p.pop("plan_id"),
}


@pytest.mark.parametrize("case", list(BROKEN))
def test_a_broken_stored_plan_is_refused_on_import(make, case):
    """J6/D20: an export whose stored plan names an unknown restaurant or booking, a table set
    that is neither a table nor a declared pair, a non-boolean `changed`, an invalid closure or
    no id is 422 validation_failed, the destination unchanged."""
    world = make(seeds=[seed("MOVE01", ["t_2"])])
    planned(world.ada, closure())
    body = exported(world.base)
    bad = copy.deepcopy(body)
    BROKEN[case](bad["state"]["plans"][0])
    with Api(world.base, timeout=RESET_TIMEOUT) as control:
        assert_error(control.post("/_test/import", json=bad), 422, "validation_failed")
    assert exported(world.base) == body
