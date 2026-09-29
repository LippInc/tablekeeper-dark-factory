"""S1-I2 acceptance checks (verifier seat), written from the stage-1 specification.

GET /availability (§8) over local time (§9): the response shape, the slot grid, closed
days and weekdays of the local date, capacity and fixture order, occupancy by seeded
bookings as a half-open interval in absolute time, daylight-saving days, and the query
parameter rules (§5). R.. and D.. name the room plan's requirement lines and decisions.
Timing checks are in test_s1_i2_load.py and run alone.
"""
from __future__ import annotations

import datetime as dt

import pytest

import fixtures as fx
from harness.http import assert_error, assert_status, error_code

pytestmark = pytest.mark.stage(1)

WEEK = {"mon": "2026-09-28", "tue": "2026-09-29", "wed": "2026-09-30", "thu": "2026-10-01",
        "fri": "2026-10-02", "sat": "2026-10-03", "sun": "2026-10-04"}
THURSDAY = WEEK["thu"]
BERLIN_SPRING, BERLIN_FALL = "2026-03-29", "2026-10-25"
NY_SPRING, NY_FALL = "2026-03-08", "2026-11-01"
AROUND_THE_CLOCK = fx.all_week("00:00", "23:30")


def hours(weekday: str = "thu", opens: str = "18:00", closes: str = "23:00") -> list[dict]:
    return [{"weekday": weekday, "opens": opens, "closes": closes}]


def availability(client, restaurant_id: str, date: str, party_size="2", **extra):
    return client.get("/availability", params={
        "restaurant_id": restaurant_id, "date": date, "party_size": party_size, **extra})


def slots(client, restaurant_id: str = "r_anker", date: str = THURSDAY, party_size="2"):
    return assert_status(availability(client, restaurant_id, date, party_size), 200).json()["slots"]


def times(slot_list: list[dict]) -> list[str]:
    return [slot["starts_at_local"].split("T")[1] for slot in slot_list]


def tables_at(slot_list: list[dict]) -> dict[str, list[str]]:
    return {slot["starts_at_local"].split("T")[1]: slot["available_table_ids"]
            for slot in slot_list}


def minutes(hhmm: str) -> int:
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


def hhmm(total: int) -> str:
    return f"{total // 60:02d}:{total % 60:02d}"


def grid(opens: str, closes: str, step: int, duration: int) -> list[str]:
    """§8 on a day without a transition: every `step` from `opens` while slot + duration
    <= closes."""
    return [hhmm(t) for t in range(minutes(opens), minutes(closes) - duration + 1, step)]


def seeded(reference: str, starts_at_local: str, *, table_id: str = "t_2",
           restaurant_id: str = "r_anker") -> dict:
    return {"id": f"res_{reference}", "reference": reference, "user_id": "u_ada",
            "restaurant_id": restaurant_id, "table_id": table_id,
            "starts_at_local": starts_at_local, "party_size": 2}


def offset_of(slot: dict) -> str:
    starts_at = slot["starts_at"]
    return "+00:00" if starts_at.endswith("Z") else starts_at[-6:]


# ---- shape and grid (§8) ----------------------------------------------------------------

def test_the_response_carries_the_documented_shape(reset, anon):
    """R87/R88/R28: restaurant_id, date, timezone and slots of starts_at_local (the full
    local YYYY-MM-DDTHH:MM), starts_at (RFC 3339 with the offset) and available_table_ids."""
    reset(fx.fixture(restaurants=[fx.restaurant(
        timezone="America/New_York", opening_hours=hours(closes="20:00"))]))
    body = assert_status(availability(anon, "r_anker", THURSDAY), 200).json()
    assert (body["restaurant_id"], body["date"], body["timezone"]) == \
        ("r_anker", THURSDAY, "America/New_York")
    shown = [(s["starts_at_local"], dt.datetime.fromisoformat(s["starts_at"]),
              s["available_table_ids"]) for s in body["slots"]]
    new_york = dt.timezone(dt.timedelta(hours=-4))
    assert shown == [
        (f"{THURSDAY}T18:00", dt.datetime(2026, 10, 1, 18, 0, tzinfo=new_york), ["t_1", "t_2", "t_3"]),
        (f"{THURSDAY}T18:30", dt.datetime(2026, 10, 1, 18, 30, tzinfo=new_york), ["t_1", "t_2", "t_3"]),
    ]
    assert [offset_of(s) for s in body["slots"]] == ["-04:00", "-04:00"]


@pytest.mark.parametrize("opens,closes,step,duration", [
    ("18:00", "23:00", 30, 90),
    ("17:10", "22:00", 45, 120),
    ("18:10", "21:00", 25, 50),
    ("09:00", "17:00", 60, 60),
    ("18:00", "19:30", 90, 90),   # slot + duration == closes is a slot
    ("12:00", "13:00", 30, 90),   # shorter than one booking: no slot
])
def test_slots_step_from_opens_while_the_booking_ends_by_closes(reset, anon, opens, closes,
                                                                step, duration):
    """R34/R35/R89: a slot for every slot_minutes step from opens such that
    slot + reservation_duration_minutes <= closes."""
    reset(fx.fixture(restaurants=[fx.restaurant(
        slot_minutes=step, reservation_duration_minutes=duration,
        opening_hours=hours(opens=opens, closes=closes))]))
    assert times(slots(anon)) == grid(opens, closes, step, duration)


@pytest.mark.parametrize("weekday", list(WEEK))
def test_a_weekday_is_open_only_on_its_own_local_dates(reset, anon, weekday):
    """R37/R92/R40: opening hours are per weekday of the local date; a day with no entry
    returns "slots": []."""
    reset(fx.fixture(restaurants=[fx.restaurant(opening_hours=hours(weekday=weekday))]))
    open_days = [day for day, date in WEEK.items() if slots(anon, date=date)]
    assert open_days == [weekday]


def test_a_restaurant_without_opening_hours_is_closed_every_day(reset, anon):
    """R37/R92: a day with no entry is closed."""
    reset(fx.fixture(restaurants=[fx.restaurant(opening_hours=[])]))
    assert [slots(anon, date=date) for date in WEEK.values()] == [[]] * 7


@pytest.mark.parametrize("zone,opens,closes,offset", [
    ("Pacific/Kiritimati", "00:00", "03:00", "+14:00"),
    ("Pacific/Pago_Pago", "21:00", "23:30", "-11:00"),
])
def test_the_date_is_the_restaurants_local_calendar_date(reset, anon, zone, opens, closes,
                                                         offset):
    """R86/R120: `date` is a local calendar date at the restaurant, whatever day it is in UTC."""
    reset(fx.fixture(restaurants=[fx.restaurant(
        timezone=zone, opening_hours=hours(opens=opens, closes=closes))]))
    found = slots(anon)
    assert times(found) == grid(opens, closes, 30, 90)
    assert {s["starts_at_local"][:10] for s in found} == {THURSDAY}
    assert {offset_of(s) for s in found} == {offset}


# ---- tables: capacity, order, occupancy (§1, §8) -----------------------------------------

MIXED_TABLES = [{"id": "t_9", "label": "9", "capacity": 8},
                {"id": "t_1", "label": "1", "capacity": 2},
                {"id": "t_5", "label": "5", "capacity": 4},
                {"id": "t_3", "label": "3", "capacity": 4}]


@pytest.mark.parametrize("party,expected", [
    ("1", ["t_9", "t_1", "t_5", "t_3"]),
    ("2", ["t_9", "t_1", "t_5", "t_3"]),
    ("3", ["t_9", "t_5", "t_3"]),
    ("4", ["t_9", "t_5", "t_3"]),
    ("8", ["t_9"]),
    ("9", []),
])
def test_tables_that_seat_the_party_in_fixture_order(reset, anon, party, expected):
    """R38/R90/R91: tables with capacity >= party_size, in fixture order; a slot with no
    such table still appears with an empty list."""
    reset(fx.fixture(restaurants=[fx.restaurant(tables=MIXED_TABLES,
                                                opening_hours=hours())]))
    found = slots(anon, party_size=party)
    assert times(found) == grid("18:00", "23:00", 30, 90)
    assert all(slot["available_table_ids"] == expected for slot in found), found


def test_a_seeded_booking_blocks_exactly_the_overlapping_slots(reset, anon):
    """R8/R90: occupancy is [starts_at, starts_at + duration): a booking at 19:00 for 90
    minutes blocks starts after 17:30 and before 20:30 on its table only."""
    reset(fx.fixture(
        restaurants=[fx.restaurant(slot_minutes=15, opening_hours=hours(opens="17:00"))],
        reservations=[seeded("SEED01", f"{THURSDAY}T19:00")]))
    found = tables_at(slots(anon))
    blocked = [t for t, ids in found.items() if "t_2" not in ids]
    assert blocked == grid("17:45", "21:45", 15, 90), blocked
    assert all({"t_1", "t_3"} <= set(ids) for ids in found.values())


def test_a_booking_on_another_date_blocks_nothing(reset, anon):
    """R90: only an overlapping booking removes a table."""
    reset(fx.fixture(
        restaurants=[fx.restaurant(opening_hours=fx.all_week())],
        reservations=[seeded("SEED01", f"{WEEK['fri']}T19:00")]))
    found = tables_at(slots(anon))
    assert all(ids == ["t_1", "t_2", "t_3"] for ids in found.values()), found


def test_a_booking_at_another_restaurant_blocks_nothing(reset, anon):
    """D1/R90: a table of the same id at another restaurant is another table."""
    reset(fx.fixture(
        restaurants=[fx.restaurant("r_a", opening_hours=hours()),
                     fx.restaurant("r_b", name="B", opening_hours=hours())],
        reservations=[seeded("SEED01", f"{THURSDAY}T19:00", restaurant_id="r_b")]))
    assert "t_2" in tables_at(slots(anon, "r_a"))["19:00"]
    assert "t_2" not in tables_at(slots(anon, "r_b"))["19:00"]


# ---- daylight-saving days (§9) -----------------------------------------------------------

AROUND_THE_CLOCK_TIMES = grid("00:00", "23:30", 30, 90)


@pytest.mark.parametrize("zone,date,before,after", [
    ("Europe/Berlin", BERLIN_SPRING, "+01:00", "+02:00"),
    ("America/New_York", NY_SPRING, "-05:00", "-04:00"),
])
def test_the_skipped_hour_never_appears(reset, anon, zone, date, before, after):
    """R121/R127/R128: local times in the skipped hour do not exist and never appear;
    every other slot carries the zone's offset for that instant."""
    reset(fx.fixture(restaurants=[fx.restaurant(timezone=zone, opening_hours=AROUND_THE_CLOCK)]))
    found = slots(anon, date=date)
    assert times(found) == [t for t in AROUND_THE_CLOCK_TIMES if t not in ("02:00", "02:30")]
    assert [offset_of(s) for s in found] == \
        [before if t < "02:00" else after for t in times(found)]


@pytest.mark.parametrize("zone,date,repeated,summer,winter", [
    ("Europe/Berlin", BERLIN_FALL, ("02:00", "02:30"), "+02:00", "+01:00"),
    ("America/New_York", NY_FALL, ("01:00", "01:30"), "-04:00", "-05:00"),
])
def test_the_repeated_hour_appears_once_at_its_first_occurrence(reset, anon, zone, date,
                                                                repeated, summer, winter):
    """R123/R124/R127/R128: each wall time of the repeated hour appears once, resolved
    to the occurrence before the clocks change."""
    reset(fx.fixture(restaurants=[fx.restaurant(timezone=zone, opening_hours=AROUND_THE_CLOCK)]))
    found = slots(anon, date=date)
    assert times(found) == AROUND_THE_CLOCK_TIMES
    change = hhmm(minutes(repeated[-1]) + 30)
    assert [offset_of(s) for s in found] == \
        [summer if t < change else winter for t in times(found)]


def test_occupancy_across_the_fall_back_night_is_absolute_time(reset, anon):
    """R126/R8: a 120-minute booking from 01:30 CEST ends at 02:30 CET, so it blocks the
    first-occurrence 02:00 and 02:30 and frees 03:00 CET."""
    reset(fx.fixture(
        restaurants=[fx.restaurant(reservation_duration_minutes=120,
                                   opening_hours=fx.all_week("00:00", "06:00"))],
        reservations=[seeded("SEED01", f"{BERLIN_FALL}T01:30")]))
    found = tables_at(slots(anon, date=BERLIN_FALL))
    assert list(found) == grid("00:00", "06:00", 30, 120)
    assert [t for t, ids in found.items() if "t_2" not in ids] == \
        ["00:00", "00:30", "01:00", "01:30", "02:00", "02:30"]


def test_occupancy_across_the_spring_forward_night_is_absolute_time(reset, anon):
    """R126/R8: a 90-minute booking from 01:30 CET ends at 04:00 CEST, so it blocks 03:00
    and 03:30 CEST and frees 04:00."""
    reset(fx.fixture(
        restaurants=[fx.restaurant(opening_hours=fx.all_week("00:00", "06:00"))],
        reservations=[seeded("SEED01", f"{BERLIN_SPRING}T01:30")]))
    found = tables_at(slots(anon, date=BERLIN_SPRING))
    assert list(found) == ["00:00", "00:30", "01:00", "01:30", "03:00", "03:30", "04:00", "04:30"]
    assert [t for t, ids in found.items() if "t_2" not in ids] == \
        ["00:30", "01:00", "01:30", "03:00", "03:30"]


# ---- several windows on one day (D19) ------------------------------------------------------

def test_each_opening_window_has_its_own_grid_in_time_order(reset, anon):
    """D19: several entries for one weekday are windows listed in time order, each with a
    grid from its own opens."""
    reset(fx.fixture(restaurants=[fx.restaurant(opening_hours=[
        {"weekday": "thu", "opens": "18:15", "closes": "22:00"},
        {"weekday": "thu", "opens": "12:00", "closes": "15:00"}])]))
    assert times(slots(anon)) == grid("12:00", "15:00", 30, 90) + grid("18:15", "22:00", 30, 90)


# ---- query parameters (§5, §8) ----------------------------------------------------------------

@pytest.mark.parametrize("party", ["4 ", "0x4", "٤", "", "1.5", "-0", "4,5", "true", "1e2"])
def test_party_size_must_be_plain_decimal_digits_of_at_least_1(world, anon, party):
    """R57/R54: an integer query parameter is plain decimal digits; anything else, or a
    value below 1, is 422 validation_failed."""
    assert_error(availability(anon, world.rid, world.date, party), 422, "validation_failed")


@pytest.mark.parametrize("party", ["04", "1"])
def test_party_size_in_plain_digits_is_accepted(world, anon, party):
    """R57: plain decimal digits are a valid integer query parameter."""
    expected = assert_status(availability(anon, world.rid, world.date, str(int(party))), 200)
    assert assert_status(availability(anon, world.rid, world.date, party), 200).json() == \
        expected.json()


@pytest.mark.parametrize("date", ["2026-9-24", "2026-10-01T00:00", "20261001", "",
                                  "2026-13-01", "2026-02-29", "2026-10-1", " 2026-10-01"])
def test_date_must_be_a_real_calendar_date(world, anon, date):
    """R54/R86: an invalid date is 422 validation_failed."""
    assert_error(availability(anon, world.rid, date), 422, "validation_failed")


def test_restaurant_id_longer_than_64_characters_is_422(world, anon):
    """D12/R54: a query id above the stated 64-character maximum is 422; an unknown id
    within it is 404."""
    assert_error(availability(anon, "r" * 65, world.date), 422, "validation_failed")
    assert_error(availability(anon, "r" * 64, world.date), 404, "not_found")


def test_unknown_query_parameters_change_nothing(world, anon):
    """R30: unknown query parameters are ignored."""
    plain = assert_status(availability(anon, world.rid, world.date), 200).json()
    tagged = availability(anon, world.rid, world.date, sort="desc", page="3", lang="de")
    assert assert_status(tagged, 200).json() == plain


ODD_QUERIES = [
    {"party_size": "9" * 5000},
    {"party_size": "9" * 20},
    {"date": "9999-12-31"},
    {"date": "9800-12-31"},
    {"date": "0001-01-01"},
    {"date": "0002-01-01"},
    {"restaurant_id": "r_ü\u0000"},
]


@pytest.mark.parametrize("override", ODD_QUERIES, ids=[f"q{i}" for i in range(len(ODD_QUERIES))])
def test_odd_availability_queries_never_answer_5xx(world, anon, override):
    """R60: requests must not produce 5xx; a refusal carries the error envelope."""
    params = {"restaurant_id": world.rid, "date": world.date, "party_size": "2", **override}
    resp = anon.get("/availability", params=params)
    assert resp.status_code < 500, f"{params} -> {resp.status_code} {resp.text[:200]}"
    if resp.status_code >= 400:
        error_code(resp)
