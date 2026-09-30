"""S3-I7 acceptance check (verifier seat): answers the stage-3 correction makes off the event loop
are answers of one state - no write lands inside an answer (stage-1 §7, the plan's "the answer
made off the event loop under the store lock"). The check of
acceptance/stage-4/test_s4_i7_consistency.py (two bookings swapping places in every move batch
while readers ask, some giving up early), run on the stage-3 service.

Resets the service; run it alone, with nothing else loading the service. `-rP` prints the
counts.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

pytestmark = pytest.mark.stage(3)

_spec = importlib.util.spec_from_file_location(
    "s4i7_consistency", pathlib.Path(__file__).resolve().parents[1] / "stage-4" / "test_s4_i7_consistency.py")
c = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(c)


def test_no_write_lands_inside_an_answer(reset, base_url):
    c.test_no_write_lands_inside_an_answer(reset, base_url)
