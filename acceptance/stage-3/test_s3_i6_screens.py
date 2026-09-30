"""S3-I6 acceptance checks (verifier seat): the screens follow the selected policy, from the
stage-3 specification (R318, R328: "Availability and booking decisions use the selected policy,
not that detail"), the task's design direction, DESIGN.md 917186b section 2 ("Dated policies",
"Cutoff sentence"), sections 4 and 5.3, and the plan's H7 and G3.

Browser checks in the harness's headless Chromium. The restaurant's fixture seats 2, 4 and 6 at
tables 1, 2 and 3 (pair 1 + 2); a policy from ON seats 6, 2 and 2 (pair 8). R.., H.. and G..
name the room plan's lines and decisions.
"""
from __future__ import annotations

import datetime as dt
import os

import pytest

import fixtures as fx
from harness.http import RESET_TIMEOUT, Api, assert_status, new_key

pytestmark = pytest.mark.stage(3)

BEFORE = fx.booking_date()
ON = (dt.date.fromisoformat(BEFORE) + dt.timedelta(weeks=1)).isoformat()
NEAR = fx.booking_date(lead=3)
YESTERDAY = fx.booking_date(lead=-1)
RESTAURANT = {**fx.managed_restaurant(), "combinable": [["t_1", "t_2"]]}
POLICY = fx.policy(ON, reservation_duration_minutes=60, capacities={"t_1": 6, "t_2": 2, "t_3": 2})
CAPACITY = {BEFORE: {"t_1": 2, "t_2": 4, "t_3": 6}, ON: POLICY["capacities"]}

ROWS = """() => { const out = {fitting: [], small: [], caption: null}; let group = 'fitting';
  for (const n of document.querySelectorAll('.rows > *')) {
    if (n.classList.contains('group-caption')) { group = 'small'; out.caption = n.innerText.trim(); continue; }
    if (!n.classList.contains('table-row')) continue;
    out[group].push([n.querySelector('.row-title').innerText.trim(),
                     n.querySelector('.row-description').innerText.replace(/\\u00a0/g, ' ').trim(),
                     n.querySelectorAll('.drawing-box circle').length]);
  }
  return out; }"""
CELLS = """() => Object.fromEntries([...document.querySelectorAll("[data-testid^='slot-']")]
  .map((n) => [n.dataset.testid, n.getAttribute('data-available')]))"""
OUTSIDE = """() => [...document.body.querySelectorAll('*')].filter((n) => n.checkVisibility()
    && [...n.childNodes].some((c) => c.nodeType === 3 && c.textContent.trim()))
  .map((n) => [n.innerText.trim().slice(0, 30), Math.round(n.getBoundingClientRect().left), Math.round(n.getBoundingClientRect().right)])
  .filter(([, left, right]) => left < 0 || right > window.innerWidth)"""

# the rows a party reads on each date: (title, description, seat dots), fitting then too small
EXPECTED_ROWS = {
    (ON, 5): {"fitting": [["Table 1", "Large table, seats 6", 6], ["Tables 1 + 2", "Joined pair, seats 8", 8]],
              "small": [["Table 2", "Small table, seats 2", 2], ["Table 3", "Small table, seats 2", 2]],
              "caption": "Too small for five"},
    (ON, 7): {"fitting": [["Tables 1 + 2", "Joined pair, seats 8", 8]],
              "small": [["Table 1", "Large table, seats 6", 6], ["Table 2", "Small table, seats 2", 2],
                        ["Table 3", "Small table, seats 2", 2]], "caption": "Too small for seven"},
    (BEFORE, 5): {"fitting": [["Table 3", "Large table, seats 6", 6], ["Tables 1 + 2", "Joined pair, seats 6", 6]],
                  "small": [["Table 1", "Small table, seats 2", 2], ["Table 2", "Medium table, seats 4", 4]],
                  "caption": "Too small for five"},
    (BEFORE, 7): {"fitting": [],
                  "small": [["Table 1", "Small table, seats 2", 2], ["Table 2", "Medium table, seats 4", 4],
                            ["Table 3", "Large table, seats 6", 6]], "caption": "Too small for seven"},
}


@pytest.fixture
def world(reset, api):
    reset(fx.fixture(restaurants=[RESTAURANT]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    assert_status(ada.post("/restaurants/r_anker/policies", idempotency_key=new_key(), json=POLICY), 201)
    return ada


def log_in(page, tid) -> None:
    page.goto("/login")
    page.fill(tid("login-email"), fx.ADA["email"])
    page.fill(tid("login-password"), fx.ADA["password"])
    page.click(tid("login-submit"))
    page.wait_for_selector(tid("current-user"))


def submit(page, tid, date: str, party: int) -> None:
    page.select_option(tid("restaurant-select"), "r_anker")
    page.fill(tid("date-input"), date)
    page.fill(tid("party-size-input"), str(party))
    page.click(tid("search-button"))


def search(page, tid, date: str, party: int, *, fresh: bool = True) -> None:
    if fresh:
        page.goto("/")
        page.wait_for_selector(tid("search-button"))
    submit(page, tid, date, party)
    page.wait_for_selector(f"{tid('availability-grid')}, {tid('no-slots')}, .results-notice-failed")


def expected_cells(anon, date: str, party: int, capacity: dict) -> dict:
    """R328/E1: a cell per table per slot, available when the service lists the table; a cell
    for the pair when its summed capacity under the date's rules seats the party, available
    when the service offers it: `data-available` stays the service's."""
    slots = assert_status(anon.get("/availability", params={"restaurant_id": "r_anker", "date": date,
                                                            "party_size": party}), 200).json()["slots"]
    cells = {}
    for slot in slots:
        hhmm = slot["starts_at_local"][11:16]
        for table in ("t_1", "t_2", "t_3"):
            cells[f"slot-{table}-{hhmm}"] = str(table in slot["available_table_ids"]).lower()
        if capacity["t_1"] + capacity["t_2"] >= party:
            offered = [o["table_ids"] for o in slot.get("available_options", [])]
            cells[f"slot-t_1+t_2-{hhmm}"] = str(["t_1", "t_2"] in offered).lower()
    return cells


# ---- the grid (R328, H7, DESIGN 2) -----------------------------------------------------------------

@pytest.mark.parametrize("date,party", list(EXPECTED_ROWS), ids=["on_5", "on_7", "before_5", "before_7"])
def test_a_search_reads_the_searched_dates_capacities(world, page, tid, anon, date, party):
    """R328/H7/DESIGN 2: every row's "seats N", size word and seat dots, the "Too small for"
    grouping and which pair gets a row follow the policy the service selects for the searched
    date; the day before still reads the fixture's; `data-available` is the service's."""
    search(page, tid, date, party)
    assert page.evaluate(ROWS) == EXPECTED_ROWS[(date, party)]
    assert page.evaluate(CELLS) == expected_cells(anon, date, party, CAPACITY[date])


def test_the_panel_and_its_refusal_follow_the_searched_date(world, page, tid):
    """DESIGN 2/S3N-2: the booking panel's "for up to ..." and a refused create's "... seats ...
    at most" take the table's capacity from the searched date's policy (Table 2: four in the
    fixture, two on ON), the same lookup as the grid."""
    log_in(page, tid)
    for date, words in ((BEFORE, "Medium table, for up to four"), (ON, "Small table, for up to two")):
        search(page, tid, date, 2)
        page.locator("[data-testid^='slot-t_2-'][data-available='true']").first.click()
        page.wait_for_selector(tid("booking-form"))
        assert words in page.inner_text(tid("booking-form")).replace("\u00a0", " "), date
    page.fill(tid("booking-party-size"), "3")
    page.click(tid("booking-submit"))
    page.wait_for_selector(tid("booking-error"))
    assert "Table 2 seats two at most" in page.inner_text(tid("booking-error")).replace("\u00a0", " ")


def test_a_same_date_tie_reads_the_services_choice(world, page, tid, anon):
    """R323/H7: with two policies from the same date, the grid reads the one the service
    selects (the later version), never a choice of its own."""
    assert_status(world.post("/restaurants/r_anker/policies", idempotency_key=new_key(),
                             json={**POLICY, "capacities": {"t_1": 3, "t_2": 2, "t_3": 2}}), 201)
    explained = assert_status(anon.get("/availability", params={"restaurant_id": "r_anker", "date": ON, "party_size": 2,
                                                                "explain": "true"}), 200).json()["slots"]
    assert explained[0]["explain"][0]["policy_version"] == 2, "precondition: the service selects version 2"
    search(page, tid, ON, 2)
    rows = page.evaluate(ROWS)
    assert ["Table 1", "Medium table, seats 3", 3] in rows["fitting"], rows


# ---- bookings already made (DESIGN 2, 5.3) -------------------------------------------------------------

def look_up(page, tid, reference: str) -> None:
    page.goto("/lookup")
    page.wait_for_selector(tid("lookup-submit"))
    page.fill(tid("lookup-reference-input"), reference)
    page.click(tid("lookup-submit"))
    page.wait_for_selector(tid("reservation-detail"))


def test_the_lookup_draws_the_bookings_own_terms(world, page, tid):
    """DESIGN 2/H7: a booking made on ON at Table 1 (six seats then) is drawn with six seats in
    the lookup after a newer same-date policy seats three there (the fixture seats two)."""
    booking = assert_status(world.post("/reservations", idempotency_key=new_key(), json={
        "restaurant_id": "r_anker", "table_id": "t_1", "starts_at_local": fx.local(ON), "party_size": 5}), 201).json()
    assert_status(world.post("/restaurants/r_anker/policies", idempotency_key=new_key(),
                             json={**POLICY, "capacities": {"t_1": 3, "t_2": 2, "t_3": 2}}), 201)
    log_in(page, tid)
    look_up(page, tid, booking["reference"])
    assert page.locator(f"{tid('reservation-detail')} svg circle").count() == 6


CUTOFFS = {"seven_days": (NEAR, 10080, "This booking can be cancelled until seven days before it starts"),
           "until_it_starts": (YESTERDAY, 0, "This booking can be cancelled until it starts")}


@pytest.mark.parametrize("case", list(CUTOFFS))
def test_the_cancel_refusal_states_the_bookings_own_cutoff(reset, api, page, tid, case):
    """DESIGN 2 and 5.3 item 7: a refused cancel states the booking's accepted cutoff in its
    largest whole unit ("until it starts" for 0), even after a newer same-date policy with
    another cutoff."""
    date, cutoff, sentence = CUTOFFS[case]
    reset(fx.fixture(restaurants=[RESTAURANT]))
    ada = api().authenticate(fx.ADA["email"], fx.ADA["password"])
    assert_status(ada.post("/restaurants/r_anker/policies", idempotency_key=new_key(),
                           json=fx.policy(date, cancellation_cutoff_minutes=cutoff)), 201)
    booking = assert_status(ada.post("/reservations", idempotency_key=new_key(), json={
        "restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": fx.local(date), "party_size": 2}), 201).json()
    assert_status(ada.post("/restaurants/r_anker/policies", idempotency_key=new_key(),
                           json=fx.policy(date, cancellation_cutoff_minutes=60)), 201)
    log_in(page, tid)
    look_up(page, tid, booking["reference"])
    page.click(tid("reservation-cancel-button"))
    page.wait_for_selector(tid("reservation-error"))
    text = page.inner_text(tid("reservation-error")).replace("\u00a0", " ")
    assert "It is too close to the booking to cancel online" in text and sentence in text, text


# ---- older APIs, late answers, requests and widths (G3, stage-2 R207, R290, R296) ---------------------

def test_the_screens_fall_back_to_the_detail_against_a_stage_2_api(world, page, tid, base_url):
    """G3/H7: with the page's API answered by the stage-2 service (no `explain`, no policies),
    the grid reads the restaurant detail's capacities on ON and nothing fails on the page."""
    previous = os.environ.get("TABLEKEEPER_STAGE2_URL")
    assert previous, "set TABLEKEEPER_STAGE2_URL to the stage-2 service of the same checkout"
    previous = previous.rstrip("/")
    with Api(previous, timeout=RESET_TIMEOUT) as stage2:
        assert_status(stage2.post("/_test/reset", json=fx.fixture(restaurants=[
            {**fx.restaurant(), "combinable": [["t_1", "t_2"]]}])), 204)
        slots = assert_status(stage2.get("/availability", params={"restaurant_id": "r_anker", "date": ON,
                                                                  "party_size": 5}), 200).json()["slots"]
    assert all("explain" not in slot for slot in slots), "precondition: a stage-2 answer"
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    def to_stage_2(route):
        route.fulfill(response=route.fetch(url=previous + route.request.url[len(base_url.rstrip("/")):]))

    for pattern in ("**/availability?*", "**/restaurants", "**/restaurants/*", "**/restaurants/*/policies"):
        page.route(pattern, to_stage_2)
    search(page, tid, ON, 5)
    assert page.evaluate(ROWS) == {**EXPECTED_ROWS[(BEFORE, 5)]}
    assert errors == []


RELEASE_LAST = {"availability_last": "/availability", "detail_last": "detail", "policies_last": "/policies"}


def kind(url: str) -> str:
    return "/availability" if "/availability" in url else "/policies" if url.endswith("/policies") else "detail"


@pytest.mark.parametrize("last", list(RELEASE_LAST))
def test_a_late_answer_never_replaces_a_later_search_whichever_request_is_last(world, page, tid, anon, last):
    """Stage-2 R207/G2 with the search's third request: search A (ON) holds its availability,
    detail and policies requests; search B (BEFORE) is answered; A's three answers, released
    afterwards with any one of them last, never replace B's rows or cells."""
    held, gate = [], {"closed": False}

    def through(route):
        (held.append(route) if gate["closed"] else route.continue_())

    for pattern in ("**/availability?*", "**/restaurants/*", "**/restaurants/*/policies"):
        page.route(pattern, through)
    search(page, tid, BEFORE, 2)
    gate["closed"] = True
    submit(page, tid, ON, 5)
    for _ in range(50):
        if len(held) >= 3:
            break
        page.wait_for_timeout(100)
    assert sorted(kind(r.request.url) for r in held) == ["/availability", "/policies", "detail"], \
        [r.request.url for r in held]
    gate["closed"] = False
    submit(page, tid, BEFORE, 5)
    expected = expected_cells(anon, BEFORE, 5, CAPACITY[BEFORE])
    page.wait_for_function(f"""(expected) => {{ const shown = ({CELLS})();
      return Object.keys(shown).length === Object.keys(expected).length
        && Object.keys(expected).every((k) => shown[k] === expected[k]); }}""", arg=expected, timeout=10_000)
    for route in sorted(held, key=lambda r: kind(r.request.url) == RELEASE_LAST[last]):
        try:
            route.continue_()
        except Exception:  # the page may have abandoned A's request already
            pass
        page.wait_for_timeout(300)
    page.wait_for_timeout(1200)
    assert page.evaluate(ROWS) == EXPECTED_ROWS[(BEFORE, 5)]
    assert page.evaluate(CELLS) == expected


def test_no_off_site_request_or_page_error_on_the_changed_screens(world, page, tid, base_url):
    """R290 (no fetches off the service) and a working page: a search on ON, a booking and its
    lookup request only the service's own origin and raise no page error."""
    requests, errors = [], []
    page.on("request", lambda r: requests.append(r.url))
    page.on("pageerror", lambda e: errors.append(str(e)))
    log_in(page, tid)
    search(page, tid, ON, 2)
    page.locator("[data-testid^='slot-t_1-'][data-available='true']").first.click()
    page.click(tid("booking-submit"))
    page.wait_for_selector(tid("confirmation"))
    reference = page.inner_text(tid("confirmation-reference")).strip()
    look_up(page, tid, reference)
    origin = base_url.rstrip("/")
    assert [u for u in requests if not u.startswith(origin + "/")] == []
    assert errors == []


@pytest.mark.parametrize("width", [375, 900, 1280])
def test_the_policy_date_grid_fits_every_width(world, page, tid, width):
    """R296 and the design direction: on ON, at 375, 900 and 1280 px, nothing scrolls sideways
    and no text leaves the viewport; every row still says "seats N"."""
    page.set_viewport_size({"width": width, "height": 900})
    search(page, tid, ON, 5)
    assert page.evaluate("() => document.scrollingElement.scrollWidth") <= width
    assert page.evaluate(OUTSIDE) == []
    rows = page.evaluate(ROWS)
    assert all("seats " in r[1] for r in rows["fitting"] + rows["small"]), rows
