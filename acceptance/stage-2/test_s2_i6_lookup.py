"""S2-I6 acceptance checks (verifier seat): the lookup screen, from the stage-2 specification
("Lookup — `/lookup`", `reservation-tables` in "UI", "Existing clients after an upgrade") and
the task's design direction, with the plan's E5 (lookup needs the owner's session) and E12
(refusals in our own words on every screen; the service's message never shown).

Browser checks in the harness's headless Chromium; the upgrade check needs
`--previous-base-url` (the stage-1 service of the same checkout) and resets it, so run this
file alone. R.., E.. and G.. name the room plan's requirement lines and decisions.
"""
from __future__ import annotations

import datetime as dt
import re

import pytest

import fixtures as fx
from harness.http import RESET_TIMEOUT, Api, assert_status, new_key

pytestmark = pytest.mark.stage(2)

DATE = fx.booking_date()
LINDEN = {**fx.restaurant("r_linden", name="Zwei Linden",
                          tables=[{"id": "t_w", "label": "Window", "capacity": 2},
                                  {"id": "t_b", "label": "Bar", "capacity": 4},
                                  {"id": "t_c", "label": "Corner", "capacity": 6}]),
          "combinable": [["t_b", "t_w"]]}
LATE = fx.restaurant("r_late", name="Spaete Stube", cancellation_cutoff_minutes=20160,     # 14 days
                     tables=[{"id": "t_x", "label": "Alcove", "capacity": 4}])
CLARET = "rgb(236, 148, 132)"
BRASS = "rgb(210, 166, 90)"
RAW = "RAW-MESSAGE-7 must never reach the page"


def seed(reference, user, restaurant, tables, hhmm, party=2, **extra) -> dict:
    return {"id": f"res_{reference}", "reference": reference, "user_id": user, "restaurant_id": restaurant,
            "table_ids": tables, "starts_at_local": fx.local(DATE, hhmm), "party_size": party, **extra}


WORLD = fx.fixture(restaurants=[LINDEN, LATE], reservations=[
    seed("LOOK01", "u_ada", "r_linden", ["t_b"], "19:00", 3),
    seed("LOOK02", "u_ada", "r_linden", ["t_b", "t_w"], "21:00", 5),
    seed("LOOK03", "u_ada", "r_late", ["t_x"], "19:00"),
    seed("LOOK04", "u_bob", "r_linden", ["t_c"], "19:00", 4),
    seed("LOOK05", "u_ada", "r_linden", ["t_c"], "21:00", 4, status="cancelled")])
CASES = {"single": ("LOOK01", ["Bar"], "19:00"), "pair": ("LOOK02", ["Bar", "Window"], "21:00")}

OUTSIDE = """() => [...document.body.querySelectorAll('*')].filter((n) => n.checkVisibility()
    && [...n.childNodes].some((c) => c.nodeType === 3 && c.textContent.trim()))
  .map((n) => [n.innerText.trim().slice(0, 30), Math.round(n.getBoundingClientRect().left), Math.round(n.getBoundingClientRect().right)])
  .filter(([, left, right]) => left < 0 || right > window.innerWidth)"""
CONTRAST = """() => {
  const parse = (s) => { const m = s && s.match(/rgba?\\(([^)]+)\\)/); if (!m) return null;
    const p = m[1].split(/[\\s,\\/]+/).filter(Boolean).map(Number);
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const over = (top, under) => ({ r: top.r * top.a + under.r * (1 - top.a),
    g: top.g * top.a + under.g * (1 - top.a), b: top.b * top.a + under.b * (1 - top.a), a: 1 });
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const backdrop = (node) => { const layers = [];
    for (let n = node; n; n = n.parentElement) { const c = parse(getComputedStyle(n).backgroundColor);
      if (c && c.a > 0) { layers.push(c); if (c.a >= 1) break; } }
    let base = { r: 255, g: 255, b: 255, a: 1 };
    for (const layer of layers.reverse()) base = over(layer, base);
    return base; };
  const shown = (n) => n.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })
    && n.getBoundingClientRect().width > 0 && n.getBoundingClientRect().height > 0;
  return [...document.body.querySelectorAll('*')].filter((n) => shown(n) && (
    ['INPUT', 'SELECT'].includes(n.tagName) || [...n.childNodes].some((c) => c.nodeType === 3 && c.textContent.trim())))
    .map((n) => { const bg = backdrop(n); const fg = over(parse(getComputedStyle(n).color), bg);
      const [hi, lo] = [lum(fg), lum(bg)].sort((a, b) => b - a);
      return { text: (n.innerText || n.value || '').trim().slice(0, 30), ratio: Math.round(((hi + 0.05) / (lo + 0.05)) * 100) / 100 }; })
    .filter((r) => r.ratio < 4.5);
}"""
CLARET_USERS = """([claret, scope]) => [...document.querySelectorAll(scope)].filter((n) => n.checkVisibility()).filter((n) => {
  const s = getComputedStyle(n);
  const side = (k) => s[`border${k}Color`] === claret && parseFloat(s[`border${k}Width`]) > 0;
  return s.color === claret || s.backgroundColor === claret || ['Top', 'Right', 'Bottom', 'Left'].some(side);
}).map((n) => n.dataset.testid || n.getAttribute('class') || n.tagName)"""


def in_words(iso: str) -> str:
    day = dt.date.fromisoformat(iso)
    return rf"{day.strftime('%A')},?\s+{day.day}\s+{day.strftime('%B')}"


@pytest.fixture
def world(reset):
    reset(WORLD)


def log_in(page, tid, email=fx.ADA["email"], password=fx.ADA["password"]) -> None:
    page.goto("/login")
    page.fill(tid("login-email"), email)
    page.fill(tid("login-password"), password)
    page.click(tid("login-submit"))
    page.wait_for_selector(tid("current-user"))


def look_up(page, tid, reference: str) -> None:
    page.goto("/lookup")
    page.wait_for_selector(tid("lookup-submit"))
    page.fill(tid("lookup-reference-input"), reference)
    page.click(tid("lookup-submit"))
    page.wait_for_selector(f"{tid('reservation-detail')}, {tid('reservation-error')}")


def status_on_service(api, reference: str, who=fx.ADA) -> str:
    client = api().authenticate(who["email"], who["password"])
    return assert_status(client.get(f"/reservations/{reference}"), 200).json()["status"]


# ---- found (R244, R269, R271, R295) ------------------------------------------------------------

@pytest.mark.parametrize("name", list(CASES))
def test_a_found_booking_shows_its_status_and_every_table(world, page, tid, name):
    """R244/R269/R271/R295: the booking's status reads exactly `confirmed`,
    `reservation-tables` names every table, the details say the restaurant, the date in words
    and the local time, and a cancel button is offered; no `reservation-error`."""
    reference, labels, at = CASES[name]
    log_in(page, tid)
    look_up(page, tid, reference)
    assert page.text_content(tid("reservation-status")).strip() == "confirmed"
    tables = page.inner_text(tid("reservation-tables"))
    assert all(label in tables for label in labels), tables
    detail = page.inner_text(tid("reservation-detail"))
    assert "Zwei Linden" in detail and at in detail and re.search(in_words(DATE), detail), detail
    assert not re.search(r"\b\d{4}-\d{2}-\d{2}\b", detail), detail
    assert page.query_selector(tid("reservation-cancel-button")) is not None
    assert page.query_selector(tid("reservation-error")) is None


def test_a_cancelled_booking_reads_cancelled_and_offers_no_cancel(world, page, tid):
    """R244: a cancelled booking's status reads exactly `cancelled` and has no cancel button."""
    log_in(page, tid)
    look_up(page, tid, "LOOK05")
    assert page.text_content(tid("reservation-status")).strip() == "cancelled"
    assert page.query_selector(tid("reservation-cancel-button")) is None


@pytest.mark.parametrize("name", list(CASES))
def test_cancelling_updates_the_booking_in_place(world, page, tid, api, name):
    """R244/R267: cancelling turns the status to `cancelled` and removes the button without a
    reload; the service holds the booking as cancelled."""
    reference, _, _ = CASES[name]
    log_in(page, tid)
    look_up(page, tid, reference)
    page.evaluate("() => { window.__notReloaded = true; }")
    page.click(tid("reservation-cancel-button"))
    page.wait_for_function("() => document.querySelector(\"[data-testid='reservation-status']\")?.textContent.trim() === 'cancelled'",
                           timeout=10_000)
    assert page.query_selector(tid("reservation-cancel-button")) is None
    assert page.query_selector(tid("reservation-error")) is None
    assert page.evaluate("() => window.__notReloaded === true"), "the page was reloaded"
    assert status_on_service(api, reference) == "cancelled"


def test_a_refused_cancel_shows_reservation_error_and_changes_nothing(world, page, tid, api):
    """R244: a cancel the service refuses (inside the cancellation cutoff) shows
    `reservation-error`; the booking stays confirmed on the page and on the service."""
    log_in(page, tid)
    look_up(page, tid, "LOOK03")
    page.click(tid("reservation-cancel-button"))
    page.wait_for_selector(tid("reservation-error"), timeout=10_000)
    assert page.inner_text(tid("reservation-error")).strip()
    assert page.text_content(tid("reservation-status")).strip() == "confirmed"
    assert page.query_selector(tid("reservation-cancel-button")) is not None
    assert status_on_service(api, "LOOK03") == "confirmed"


# ---- not shown (R244, E5) ------------------------------------------------------------------------

@pytest.mark.parametrize("reference", ["NOPE99", "LOOK04"], ids=["unknown", "someone_elses"])
def test_a_reference_that_is_not_yours_shows_reservation_error(world, page, tid, reference):
    """R244/E5: an unknown reference and another diner's reference show `reservation-error`
    and no booking detail; nothing of the other diner's booking is shown."""
    log_in(page, tid)
    look_up(page, tid, reference)
    text = page.inner_text(tid("reservation-error")).strip()
    assert text
    assert page.query_selector(tid("reservation-detail")) is None
    assert "Corner" not in page.inner_text("main")


def test_reservation_error_is_there_only_when_there_is_one(world, page, tid):
    """R244: no `reservation-error` before a lookup; a found lookup after a not-found one
    removes it."""
    log_in(page, tid)
    page.goto("/lookup")
    page.wait_for_selector(tid("lookup-submit"))
    assert page.query_selector(tid("reservation-error")) is None
    look_up(page, tid, "NOPE99")
    assert page.query_selector(tid("reservation-error")) is not None
    page.fill(tid("lookup-reference-input"), "LOOK01")
    page.click(tid("lookup-submit"))
    page.wait_for_selector(tid("reservation-detail"))
    assert page.query_selector(tid("reservation-error")) is None


def test_a_signed_out_visitor_is_asked_to_log_in_on_a_neutral_surface(world, page, tid):
    """E5/R296: signed out, submitting a reference shows the log-in prompt as
    `reservation-error` on a neutral surface (no claret) with a brass "Log in", and no detail;
    before asking there is no `reservation-error`."""
    page.goto("/lookup")
    page.wait_for_selector(tid("lookup-submit"))
    assert page.query_selector(tid("reservation-error")) is None
    page.fill(tid("lookup-reference-input"), "LOOK01")
    page.click(tid("lookup-submit"))
    page.wait_for_selector(tid("reservation-error"))
    assert page.query_selector(tid("reservation-detail")) is None
    scope = "[data-testid='reservation-error'], [data-testid='reservation-error'] *"
    assert page.evaluate(CLARET_USERS, [CLARET, scope]) == []
    actions = page.evaluate("""() => [...document.querySelectorAll("[data-testid='reservation-error'] a, [data-testid='reservation-error'] button")]
      .filter((n) => n.innerText.trim() === 'Log in').map((n) => getComputedStyle(n).backgroundColor)""")
    assert BRASS in actions, actions


# ---- the upgrade (R247, R246) ------------------------------------------------------------------------

def test_a_reference_booked_before_the_upgrade_still_looks_up(reset, page, tid, previous_api, base_url):
    """R247/R246: signed in while the page talks to the stage-1 service, a booking made
    there, stage 1 exported and imported into stage 2: the page, now talking to stage 2, is
    still signed in and the reference looks up as confirmed with its table."""
    fixture = fx.fixture(restaurants=[LINDEN])
    assert_status(previous_api.post("/_test/reset", json=fixture), 204)
    reset(fx.fixture())
    previous, here = previous_api.base_url.rstrip("/"), base_url.rstrip("/")

    def to_stage_1(route):
        route.fulfill(response=route.fetch(url=previous + route.request.url[len(here):]))

    for pattern in ("**/auth/*", "**/reservations**", "**/restaurants**"):
        page.route(pattern, to_stage_1)
    log_in(page, tid)
    with Api(previous) as old:
        old.authenticate(fx.ADA["email"], fx.ADA["password"])
        reference = assert_status(old.post("/reservations", idempotency_key=new_key(), json={
            "restaurant_id": "r_linden", "table_id": "t_b", "starts_at_local": fx.local(DATE, "19:00"),
            "party_size": 3}), 201).json()["reference"]
    with Api(previous, timeout=RESET_TIMEOUT) as source, Api(here, timeout=RESET_TIMEOUT) as target:
        exported = assert_status(source.get("/_test/export"), 200).json()
        assert_status(target.post("/_test/import", json=exported), 204)
    for pattern in ("**/auth/*", "**/reservations**", "**/restaurants**"):
        page.unroute(pattern)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    look_up(page, tid, reference)
    assert page.query_selector(tid("current-user")) is not None
    assert page.text_content(tid("reservation-status")).strip() == "confirmed"
    assert "Bar" in page.inner_text(tid("reservation-tables"))
    assert not errors, errors


# ---- refusals in our own words on every screen (E12, R218, R226) ---------------------------------------

def refuse(status: int, code: str):
    body = f'{{"error":{{"code":"{code}","message":"{RAW}"}}}}'
    return lambda route: route.fulfill(status=status, content_type="application/json", body=body)


@pytest.mark.parametrize("screen", ["search_422", "search_500", "booking", "lookup_cancel", "login", "signup"])
def test_a_refusal_is_told_in_our_own_words(world, page, tid, screen):
    """E12/R218/R226: on every screen a refusal is shown, and the service's own message
    never reaches the page."""
    if screen.startswith("search"):
        page.route("**/availability?*", refuse(422 if screen == "search_422" else 500, "validation_failed"))
        page.goto("/")
        page.wait_for_selector(tid("search-button"))
        page.select_option(tid("restaurant-select"), "r_linden")
        page.fill(tid("date-input"), DATE)
        page.click(tid("search-button"))
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(500)
        shown = page.inner_text("main")
        assert re.search(r"could not|did not|check|again", shown, re.I), shown
    elif screen == "booking":
        log_in(page, tid)
        page.goto("/")
        page.wait_for_selector(tid("search-button"))
        page.select_option(tid("restaurant-select"), "r_linden")
        page.fill(tid("date-input"), DATE)
        page.fill(tid("party-size-input"), "2")
        page.click(tid("search-button"))
        page.click(tid("slot-t_w-18:00"))
        page.route("**/reservations", refuse(422, "unheard_of_rule"))
        page.click(tid("booking-submit"))
        page.wait_for_selector(tid("booking-error"))
        shown = page.inner_text(tid("booking-error"))
    elif screen == "lookup_cancel":
        log_in(page, tid)
        look_up(page, tid, "LOOK01")
        page.route("**/cancel", refuse(409, "unheard_of_rule"))
        page.click(tid("reservation-cancel-button"))
        page.wait_for_selector(tid("reservation-error"))
        shown = page.inner_text(tid("reservation-error"))
    else:
        page.route(f"**/auth/{screen}", refuse(422, "validation_failed"))
        page.goto(f"/{screen}")
        if screen == "signup":
            page.fill(tid("signup-display-name"), "Cy")
        page.fill(tid(f"{screen}-email"), "cy@example.com")
        page.fill(tid(f"{screen}-password"), "a long enough secret")
        page.click(tid(f"{screen}-submit"))
        page.wait_for_selector(tid("auth-error"))
        shown = page.inner_text(tid("auth-error"))
    assert shown.strip()
    assert "RAW-MESSAGE-7" not in page.inner_text("body"), shown


# ---- the look (R224, R225, R294, R296) ----------------------------------------------------------------

def lookup_states(page, tid, api):
    log_in(page, tid)
    for reference in ("LOOK01", "LOOK02", "LOOK05"):
        look_up(page, tid, reference)
        yield f"found {reference}", False
    look_up(page, tid, "NOPE99")
    yield "not found", True
    look_up(page, tid, "LOOK03")
    page.click(tid("reservation-cancel-button"))
    page.wait_for_selector(tid("reservation-error"))
    yield "cancel refused", True
    page.evaluate("() => localStorage.clear()")
    page.goto("/lookup")
    page.fill(tid("lookup-reference-input"), "LOOK01")
    page.click(tid("lookup-submit"))
    page.wait_for_selector(tid("reservation-error"))
    yield "signed out", False


@pytest.mark.parametrize("width", [375, 1280])
def test_every_lookup_state_fits_and_reads(world, page, tid, api, width):
    """R224/R225/R296: at 375 and 1280 px no lookup state scrolls sideways or puts text
    outside the viewport, every text has 4.5:1 contrast, and claret appears only on a
    refusal."""
    page.set_viewport_size({"width": width, "height": 900})
    problems = []
    for state, claret_allowed in lookup_states(page, tid, api):
        size = page.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
        if size[0] > size[1]:
            problems.append((state, "scroll", size))
        problems += [(state, "outside", t) for t in page.evaluate(OUTSIDE)]
        problems += [(state, "contrast", r) for r in page.evaluate(CONTRAST)]
        if not claret_allowed:
            problems += [(state, "claret", c) for c in page.evaluate(CLARET_USERS, [CLARET, "body *"])]
    assert not problems, problems[:8]


def test_the_cancel_button_keeps_its_width_while_cancelling(world, page, tid):
    """R294: the cancel button has one width idle and while its request is on its way."""
    log_in(page, tid)
    look_up(page, tid, "LOOK01")
    width = "() => document.querySelector(\"[data-testid='reservation-cancel-button']\").getBoundingClientRect().width"
    idle = page.evaluate(width)
    held = []
    page.route("**/cancel", lambda r: held.append(r))
    page.click(tid("reservation-cancel-button"))
    for _ in range(50):
        if held:
            break
        page.wait_for_timeout(100)
    busy = page.evaluate(width)
    held[0].continue_()
    assert idle == busy, (idle, busy)
