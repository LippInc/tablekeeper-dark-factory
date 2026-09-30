"""S4-I4 acceptance checks (verifier seat): series amendments under simultaneous requests, from
the stage-4 specification ("Concurrent amendments from the same expected revision may not both
make a real change"; "The resulting occurrences must not conflict with ... applied closures";
R437, R450, R451, R455, R461) with the plan's Q21 and Q23.

Resets the service; run it alone, with nothing else loading the service. `-rP` prints every
round.
"""
from __future__ import annotations

import importlib.util
import pathlib
from collections import Counter

import pytest

import fixtures as fx
from harness.http import new_key

pytestmark = pytest.mark.stage(4)


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, pathlib.Path(__file__).with_name(file))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


am = _load("s4i4_amend", "test_s4_i4_amend.py")
r3 = _load("s4i3_races", "test_s4_i3_races.py")  # together(), outcome(), overlapping()
make = am.make  # the reset-world fixture

TIMES = [f"{12 + i // 2:02d}:{30 * (i % 2):02d}" for i in range(20)]  # 12:00 .. 21:30


@pytest.mark.parametrize("round_", range(3))
def test_twenty_amendments_from_one_revision_make_one_real_change(make, round_):
    """R461/Q23: 20 amendments from revision 1, each to another time under its own key: one 201,
    19 × 409 stale_revision; the series at revision 2, the restaurant one revision further,
    each occurrence with exactly one `changed` entry, all at the winner's time."""
    world = am.series_world(make, count=3)
    restaurant_before = am.revision(world)
    responses = r3.together(world, [("bob", "POST", f"/series/{world.sid}/amend",
                                     {"expected_revision": 1, "from_index": 0, "local_time": t}, new_key())
                                    for t in TIMES])
    outcomes = Counter(r3.outcome(r) for r in responses)
    print(f"round {round_}: {dict(outcomes)}")
    assert outcomes == {"201": 1, "409 stale_revision": 19}
    winner = TIMES[next(i for i, r in enumerate(responses) if r.status_code == 201)]
    series = am.get_series(world, world.sid)
    assert series["revision"] == 2 and am.revision(world) == restaurant_before + 1
    for ref in world.refs:
        assert am.local(am.read(world, ref)).endswith(winner)
        assert [e["event"] for e in am.history(world, ref)].count("changed") == 1


@pytest.mark.parametrize("round_", range(8))
def test_an_amendment_racing_an_application_is_whole_or_absent_and_never_overlaps(make, round_):
    """R437/R450/R451/Q21/Q23: an amendment of three occurrences to 21:00 races the application
    of a plan closing t_2 on occurrence 1's date from 20:45 and creates on t_2 at 21:00 on the
    other occurrences' dates: the amendment moves all three or none, and afterwards no two
    holds (bookings or the closure) share a table at the same time."""
    world = am.series_world(make, count=3)
    plan = am.planned(world.ada, am.closure(start="20:45", end="23:00", date=am.later(1)))
    create = lambda date: {"restaurant_id": "r_anker", "table_id": "t_2", "party_size": 2,
                           "starts_at_local": fx.local(date, "21:00")}
    responses = r3.together(world, [
        ("bob", "POST", f"/series/{world.sid}/amend", {"expected_revision": 1, "from_index": 0, "local_time": "21:00"}, new_key()),
        ("ada", "POST", f"/restaurants/r_anker/replans/{plan['plan_id']}/apply", {}, new_key()),
        ("bob", "POST", "/reservations", create(am.DATE), new_key()),
        ("bob", "POST", "/reservations", create(am.later(2)), new_key())])
    times = [am.local(am.read(world, ref))[11:] for ref in world.refs]
    overlaps = r3.overlapping(world)
    print(f"round {round_}: amendment {r3.outcome(responses[0])}, application {r3.outcome(responses[1])}, "
          f"creates {[r3.outcome(r) for r in responses[2:]]}, occurrences at {times}, overlaps {len(overlaps)}")
    assert times in (["19:00"] * 3, ["21:00"] * 3), times
    assert (responses[0].status_code == 201) == (times == ["21:00"] * 3)
    assert overlaps == [], overlaps
