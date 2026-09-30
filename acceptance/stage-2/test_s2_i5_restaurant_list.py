"""S2-I5 acceptance checks (verifier seat): `/` while the restaurant list loads and when it
does not arrive, from the stage-2 specification ("Provide considered empty, loading and error
states") and the task's design direction ("the results area is still composed: ... the date in
words ... and one clear next step"). Closes the verifier's S2-I3 note N1 (a blank page and an
uncaught error when GET /restaurants fails).

Each case runs in its own browser context, so no case carries another's page error.
"""
from __future__ import annotations

import datetime as dt
import re

import pytest

import fixtures as fx

pytestmark = pytest.mark.stage(2)


def today_in_words(page) -> str:
    """The browser's today as the diner reads it: weekday, day and month."""
    year, month, day = page.evaluate("() => { const d = new Date(); return [d.getFullYear(), d.getMonth() + 1, d.getDate()]; }")
    date = dt.date(year, month, day)
    return rf"{date.strftime('%A')},?\s+{date.day}\s+{date.strftime('%B')}"


def main_text(page) -> str:
    return page.evaluate("() => (document.querySelector('main') || document.body).innerText.trim()")


def next_steps(page) -> list[str]:
    return page.evaluate("""() => [...document.querySelectorAll('main button, main a')]
      .filter((n) => n.checkVisibility()).map((n) => n.innerText.trim())""")


@pytest.fixture
def world(reset):
    reset(fx.fixture())


def test_while_the_restaurants_load_the_results_area_is_composed(world, page, tid):
    """R226/R292: while GET /restaurants is on its way, `/` shows a composed loading state
    with the date in words, then the search once the list arrives, without a page error."""
    errors, held = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route("**/restaurants", lambda r: held.append(r))
    page.goto("/")
    for _ in range(50):
        if held:
            break
        page.wait_for_timeout(100)
    page.wait_for_timeout(300)
    text = main_text(page)
    assert text and re.search(today_in_words(page), text), f"loading state: {text!r}"
    held[0].continue_()
    page.wait_for_selector(tid("restaurant-select"))
    assert not errors, errors


@pytest.mark.parametrize("failure", ["no_answer", "server_error", "unreadable_answer"])
def test_a_restaurant_list_that_does_not_arrive_leaves_a_composed_page(world, page, failure):
    """R226/R292: when GET /restaurants gets no answer, a 5xx or a body that does not parse,
    `/` shows a composed failed state (the date in words and one next step), without a page
    error."""
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    handlers = {
        "no_answer": lambda r: r.abort("connectionreset"),
        "server_error": lambda r: r.fulfill(status=500, content_type="application/json",
                                            body='{"error":{"code":"internal_error","message":"unexpected error"}}'),
        "unreadable_answer": lambda r: r.fulfill(status=200, content_type="application/json", body="{not json"),
    }
    page.route("**/restaurants", handlers[failure])
    page.goto("/")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)
    text = main_text(page)
    assert not errors, errors
    assert text and re.search(today_in_words(page), text), f"failed state: {text!r}"
    assert next_steps(page), f"no next step offered: {text!r}"


def test_trying_again_after_a_missing_list_shows_the_search(world, page, tid):
    """R226/R292: the failed state's next step, once the service answers, leads to the
    search, without a reload and without a page error."""
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route("**/restaurants", lambda r: r.abort("connectionreset"), times=1)
    page.goto("/")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)
    page.evaluate("() => { window.__notReloaded = true; }")
    [step] = next_steps(page)
    page.get_by_role("button", name=step).click()
    page.wait_for_selector(tid("restaurant-select"))
    assert page.evaluate("() => [...document.querySelectorAll(\"[data-testid='restaurant-select'] option\")].map((o) => o.value)") == ["r_anker"]
    assert page.evaluate("() => window.__notReloaded === true")
    assert not errors, errors
