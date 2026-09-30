"""S3-I7 acceptance checks (verifier seat): the stage-3 correction's dense availability within the
task's 5 s per request for every question mix, answers unchanged (R302-R310, R329), from the room
plan's S3-I7 "Done means".

The same checks as acceptance/stage-4/test_s4_i7_dense.py (its state builder, rule-by-rule
reference and bursts are reused), on the stage-3 service: the dense state is built through this
service's own API and its export imported into it and into the control named by
TABLEKEEPER_CONTROL_URL (c8cb447's stage-3), so both hold the same state. Bursts (a) and (b), 50
at once, explained then plain, the service and the control in turns: slowest under 5 s, the
explained burst at most half of the control's, every answer byte-identical to the control's and
three per burst equal to the reference.

S4I7_ROUNDS sets the rounds per test (default 1). Resets the service and the control: run it
alone, with nothing else loading them; `-rP` prints the values.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib

import pytest

pytestmark = pytest.mark.stage(3)

_spec = importlib.util.spec_from_file_location(
    "s4i7_dense", pathlib.Path(__file__).resolve().parents[1] / "stage-4" / "test_s4_i7_dense.py")
d = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(d)


@pytest.fixture(scope="module")
def dense(base_url):
    world = d.build(base_url, d.first_dense_day())
    world.control = os.environ.get("TABLEKEEPER_CONTROL_URL", "").rstrip("/") or None
    for base in filter(None, (base_url, world.control)):
        d.load(base, world.body)
    world.held = {}
    for b in world.bookings:
        world.held.setdefault((b["table"], b["date"]), []).append((b["start"], b["start"] + b["minutes"]))
    for intervals in world.held.values():
        intervals.sort()
    return world


def test_burst_a_50_different_questions_on_the_dense_day_and_the_four_after(dense, base_url):
    """R302-R310 and the task's 5 s per request, burst (a), on the stage-3 service."""
    d.test_burst_a_50_different_questions_on_the_dense_day_and_the_four_after(dense, base_url)


def test_burst_b_50_questions_on_50_different_dates(dense, base_url):
    """R302-R310 and the task's 5 s per request, burst (b), on the stage-3 service."""
    d.test_burst_b_50_questions_on_50_different_dates(dense, base_url)
