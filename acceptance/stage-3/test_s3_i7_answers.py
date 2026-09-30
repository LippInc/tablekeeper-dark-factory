"""S3-I7 acceptance checks (verifier seat): the stage-3 correction's answers stay the rule text's
(R302-R310, R329, stage-2 options) for every party size in both forms, and kept answers follow a
policy published for one date only (R305). The checks of acceptance/stage-4/test_s4_i7_answers.py
that use no stage-4 surface, run on the stage-3 service.

Resets the service: run it alone against other files that reset it.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

pytestmark = pytest.mark.stage(3)

_spec = importlib.util.spec_from_file_location(
    "s4i7_answers", pathlib.Path(__file__).resolve().parents[1] / "stage-4" / "test_s4_i7_answers.py")
a = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(a)
world = a.world  # the reset-world fixture


@pytest.mark.parametrize("explain", [False, True], ids=["plain", "explained"])
def test_every_party_size_is_answered_by_the_rule_text_and_asked_again_the_same(world, explain):
    """R302-R310/R329: parties 1-10 on a day with singles and pairs held, each asked twice,
    equal the rule-by-rule reference; parties with different fitting tables differ."""
    a.test_every_party_size_is_answered_by_the_rule_text_and_asked_again_the_same(world, explain)


def test_a_policy_for_one_date_changes_that_dates_answers_only(world):
    """R305/R329: a policy for one date changes that date's kept answers only."""
    a.test_a_policy_for_one_date_changes_that_dates_answers_only(world)
