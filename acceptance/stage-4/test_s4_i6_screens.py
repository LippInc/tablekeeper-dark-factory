"""S4-I6 acceptance checks (verifier seat): the existing screens reflect an applied plan, from the
stage-4 specification ("No new screens are required. Existing availability, confirmation and
lookup screens must reflect an applied plan."; R404), DESIGN.md b1ed386 (section 2 "a closure
reads exactly as a taken slot", "a moved booking's lookup shows only its current tables"; 3.8 the
refused body) and the plan's J7 and Q25; the CSS merge's pass criterion (v3.6): every element's
computed style equal to the S4-I6 base (5b77876) in each state at 375, 900 and 1280.

Browser checks in headless Chromium. The restaurant seats 2, 4, 4 and 6 at tables 1-4 with the
pairs 1 + 2 and 2 + 3 (the designer's fixture); the lookups use pairs 1 + 3 and a table 3 of two,
so a move can go from a single to a pair. The computed-style check needs the base service of
the same checkout as TABLEKEEPER_BASE_UI_URL (5b77876's stage-4). Resets the services.
"""
from __future__ import annotations

import datetime as dt
import os
from zoneinfo import ZoneInfo

import pytest

import fixtures as fx
from harness.http import Api, assert_status, new_key

pytestmark = pytest.mark.stage(4)

DATE = fx.booking_date()
NEAR = fx.booking_date(lead=3)
BERLIN = ZoneInfo("Europe/Berlin")
NEW_BODY = "It was booked or closed a moment ago. The times are refreshed and your details are kept: choose another time or table."
OLD_BODY = "Another guest booked it a moment ago."


def tables(*caps):
    return [{"id": f"t_{i}", "label": str(i), "capacity": c} for i, c in enumerate(caps, 1)]


GRID_RESTAURANT = {**fx.managed_restaurant(tables=tables(2, 4, 4, 6)), "combinable": [["t_1", "t_2"], ["t_2", "t_3"]]}
LOOKUP_RESTAURANT = {**fx.managed_restaurant(tables=tables(2, 4, 2, 6), cancellation_cutoff_minutes=10080),
                     "combinable": [["t_1", "t_3"]]}


def seed(reference, table, date, hhmm, party=2):
    return {"id": f"res_{reference}", "reference": reference, "user_id": "u_ada", "restaurant_id": "r_anker",
            "table_id": table, "starts_at_local": fx.local(date, hhmm), "party_size": party}


def instant(date, hhmm):
    return dt.datetime.combine(dt.date.fromisoformat(date), dt.time.fromisoformat(hhmm), BERLIN).isoformat()


def close(ada, table, date, start, end) -> dict:
    """Preview and apply a plan closing `table` over [start, end); the plan's assignments."""
    plan = assert_status(ada.post("/restaurants/r_anker/replans", idempotency_key=new_key(), json={
        "table_id": table, "from": instant(date, start), "to": instant(date, end)}), 201).json()
    assert_status(ada.post(f"/restaurants/r_anker/replans/{plan['plan_id']}/apply", idempotency_key=new_key(), json={}), 201)
    return {a["reference"]: a["table_ids"] for a in plan["assignments"]}


def world(reset, api, restaurant, seeds=()):
    reset(fx.fixture(restaurants=[restaurant], reservations=list(seeds)))
    return api().authenticate(fx.ADA["email"], fx.ADA["password"]), api().authenticate(fx.BOB["email"], fx.BOB["password"])


def log_in(page, tid):
    page.goto("/login")
    page.fill(tid("login-email"), fx.ADA["email"])
    page.fill(tid("login-password"), fx.ADA["password"])
    page.click(tid("login-submit"))
    page.wait_for_selector(tid("current-user"))


def search(page, tid, date, party):
    page.goto("/")
    page.wait_for_selector(tid("search-button"))
    page.select_option(tid("restaurant-select"), "r_anker")
    page.fill(tid("date-input"), date)
    page.fill(tid("party-size-input"), str(party))
    page.click(tid("search-button"))
    page.wait_for_selector(f"{tid('availability-grid')}, {tid('no-slots')}")


def open_form(page, tid, cell):
    page.click(tid(cell))
    page.wait_for_selector(tid("booking-form"))


def look_up(page, tid, reference):
    page.goto("/lookup")
    page.wait_for_selector(tid("lookup-submit"))
    page.fill(tid("lookup-reference-input"), reference)
    page.click(tid("lookup-submit"))
    page.wait_for_selector(tid("reservation-detail"))


def detail(page, tid) -> dict:
    return page.evaluate("""(sel) => { const d = document.querySelector(sel);
      const dts = [...d.querySelectorAll('dt')].map(n => n.innerText.trim());
      const dds = [...d.querySelectorAll('dd')].map(n => n.innerText.replace(/\\u00a0/g, ' ').trim());
      return {tables: d.querySelector("[data-testid='reservation-tables']").innerText.trim(),
              seats: d.querySelectorAll('svg circle').length, rows: Object.fromEntries(dts.map((t, i) => [t, dds[i]])),
              text: d.innerText}; }""", tid("reservation-detail"))


CELLS = """() => Object.fromEntries([...document.querySelectorAll("[data-testid^='slot-']")]
  .map((n) => [n.dataset.testid, n.getAttribute('data-available')]))"""
ROWS = """() => { const out = {fitting: [], small: []}; let group = 'fitting';
  for (const n of document.querySelectorAll('.rows > *')) {
    if (n.classList.contains('group-caption')) { group = 'small'; continue; }
    if (n.classList.contains('table-row')) out[group].push(n.querySelector('.row-title').innerText.trim()); }
  return out; }"""
WORDS = """() => (document.body.innerText + ' ' + [...document.querySelectorAll('[aria-label],[title],[alt]')]
  .map(n => [n.getAttribute('aria-label'), n.getAttribute('title'), n.getAttribute('alt')].join(' ')).join(' ')).toLowerCase()"""


def expected_cells(anon, date, party, capacity, pairs) -> dict:
    """E1/J7: a cell per table per slot, available when the service lists the table; a cell per
    declared pair whose summed capacity seats the party, available when the service offers it."""
    slots = assert_status(anon.get("/availability", params={"restaurant_id": "r_anker", "date": date,
                                                            "party_size": party}), 200).json()["slots"]
    cells = {}
    for slot in slots:
        hhmm = slot["starts_at_local"][11:16]
        for table in capacity:
            cells[f"slot-{table}-{hhmm}"] = str(table in slot["available_table_ids"]).lower()
        offered = [o["table_ids"] for o in slot.get("available_options", [])]
        for pair in pairs:
            if capacity[pair[0]] + capacity[pair[1]] >= party:
                cells[f"slot-{pair[0]}+{pair[1]}-{hhmm}"] = str(pair in offered).lower()
    return cells


def off_site(page, base_url) -> list:
    requests = []
    page.on("request", lambda r: requests.append(r.url))
    return requests


# ---- the grid after an application (R404, DESIGN 2, E1, J7) -----------------------------------------------------

@pytest.mark.parametrize("party", [2, 5])
def test_the_grid_shows_a_closure_as_taken_exactly_during_it(reset, api, anon, page, tid, base_url, party):
    """R404/DESIGN 2/J7: after a plan closing Table 2 from 19:00 to 21:00 is applied (moving its
    booking to Table 1), every cell's data-available is the service's; Table 2 and the pairs 1 + 2
    and 2 + 3 are taken from 18:00 to 20:30 (90-minute bookings overlapping the closure) and
    offered again at 21:00; the rows stay in the groups they had before; the word "closed"
    appears nowhere; nothing is fetched off the service."""
    ada, _ = world(reset, api, GRID_RESTAURANT, [seed("MOVE01", "t_2", DATE, "19:00")])
    requests = off_site(page, base_url)
    log_in(page, tid)
    search(page, tid, DATE, party)
    rows_before = page.evaluate(ROWS)
    assert close(ada, "t_2", DATE, "19:00", "21:00") == {"MOVE01": ["t_1"]}
    search(page, tid, DATE, party)
    capacity, pairs = {"t_1": 2, "t_2": 4, "t_3": 4, "t_4": 6}, [["t_1", "t_2"], ["t_2", "t_3"]]
    cells = page.evaluate(CELLS)
    assert cells == expected_cells(anon, DATE, party, capacity, pairs)
    for hhmm in ("18:00", "18:30", "19:00", "19:30", "20:00", "20:30"):
        assert cells[f"slot-t_2-{hhmm}"] == "false", hhmm
        for pair in ("t_1+t_2", "t_2+t_3"):
            assert cells[f"slot-{pair}-{hhmm}"] == "false", (pair, hhmm)
    assert cells["slot-t_2+t_3-21:00"] == "true"  # the pair seats both parties
    assert cells["slot-t_2-21:00"] == ("true" if party <= 4 else "false")  # Table 2 seats four
    assert "closed" not in page.evaluate(WORDS)
    assert page.evaluate(ROWS) == rows_before
    assert all(url.startswith(base_url) for url in requests), [u for u in requests if not u.startswith(base_url)]


@pytest.mark.parametrize("party", [2, 5])
def test_a_whole_evening_closure_is_still_just_taken(reset, api, anon, page, tid, party):
    """DESIGN 2 (the designer's fixture: Table 2 closed 18:00-23:00): every cell of Table 2 and of
    both pairs holding it is taken, the cells are the service's, the rows keep their groups, and
    no "closed" label, legend entry or banner appears on the fully taken rows."""
    ada, _ = world(reset, api, GRID_RESTAURANT, [seed("MOVE01", "t_2", DATE, "19:00")])
    log_in(page, tid)
    search(page, tid, DATE, party)
    rows_before = page.evaluate(ROWS)
    close(ada, "t_2", DATE, "18:00", "23:00")
    search(page, tid, DATE, party)
    cells = page.evaluate(CELLS)
    assert cells == expected_cells(anon, DATE, party, {"t_1": 2, "t_2": 4, "t_3": 4, "t_4": 6}, [["t_1", "t_2"], ["t_2", "t_3"]])
    assert {v for k, v in cells.items() if k.startswith(("slot-t_2-", "slot-t_1+t_2-", "slot-t_2+t_3-"))} == {"false"}
    assert "closed" not in page.evaluate(WORDS)
    assert page.evaluate(ROWS) == rows_before


# ---- the refused create (DESIGN 3.8, E12) ---------------------------------------------------------------------------

def refusal_text(page, tid) -> str:
    page.wait_for_selector(tid("booking-error"), timeout=15_000)
    return page.inner_text(tid("booking-error")).replace(" ", " ")


def test_a_create_refused_on_a_time_closed_after_the_search_reads_the_new_body(reset, api, page, tid):
    """DESIGN 3.8/E12: Table 2 at 19:00 is chosen, then a plan closes Table 2 from 19:00 to 21:00;
    booking it is refused under the unchanged title "Table 2 at 19:00 was just taken" with the
    new body, and the old body is gone."""
    ada, _ = world(reset, api, GRID_RESTAURANT)
    log_in(page, tid)
    search(page, tid, DATE, 2)
    open_form(page, tid, "slot-t_2-19:00")
    close(ada, "t_2", DATE, "19:00", "21:00")
    page.click(tid("booking-submit"))
    text = refusal_text(page, tid)
    assert "Table 2 at 19:00 was just taken" in text and NEW_BODY in text and OLD_BODY not in text, text


def test_a_create_refused_because_another_guest_took_the_slot_reads_the_same(reset, api, page, tid):
    """DESIGN 3.8: Table 3 at 20:00 chosen, then another guest books it: the same title shape and
    the same new body."""
    _, bob = world(reset, api, GRID_RESTAURANT)
    log_in(page, tid)
    search(page, tid, DATE, 2)
    open_form(page, tid, "slot-t_3-20:00")
    assert_status(bob.post("/reservations", idempotency_key=new_key(), json={
        "restaurant_id": "r_anker", "table_id": "t_3", "starts_at_local": fx.local(DATE, "20:00"), "party_size": 2}), 201)
    page.click(tid("booking-submit"))
    text = refusal_text(page, tid)
    assert "Table 3 at 20:00 was just taken" in text and NEW_BODY in text and OLD_BODY not in text, text


# ---- the booked notice reads the booking back (Q25, R404) -----------------------------------------------------------

def lost_answer_then_moved(reset, api, page, tid):
    """A booking of Table 2 at 19:00 whose answer is lost (the request reaches the service), then
    a plan moves it to Table 1; returns (ada, the booking's reference)."""
    ada, _ = world(reset, api, GRID_RESTAURANT)
    log_in(page, tid)
    search(page, tid, DATE, 2)
    open_form(page, tid, "slot-t_2-19:00")

    def drop_answer(route):
        if route.request.method == "POST":
            route.fetch()
            route.abort()
        else:
            route.continue_()
    page.route("**/reservations", drop_answer)
    page.click(tid("booking-submit"))
    page.wait_for_selector(tid("booking-uncertain"), timeout=15_000)
    page.unroute("**/reservations")
    [booking] = assert_status(ada.get("/reservations"), 200).json()["reservations"]
    assert close(ada, "t_2", DATE, "19:00", "21:00") == {booking["reference"]: ["t_1"]}
    return ada, booking["reference"]


def test_a_retried_lost_booking_shows_the_tables_it_has_now(reset, api, page, tid):
    """Q25/R404: the retry with the same key gets the original answer (Table 2) replayed, and the
    booked notice shows Table 1, where the plan put it, under the same reference."""
    _, reference = lost_answer_then_moved(reset, api, page, tid)
    replays = []
    page.on("response", lambda r: r.request.method == "POST" and r.url.endswith("/reservations") and replays.append(r.status))
    page.click(tid("booking-submit"))
    page.wait_for_selector(tid("confirmation"), timeout=15_000)
    assert replays == [200]
    assert page.inner_text(tid("confirmation-tables")).strip() == "Table 1"
    assert page.inner_text(tid("confirmation-reference")).strip() == reference


def test_when_the_booking_cannot_be_read_back_the_notice_shows_the_answer(reset, api, page, tid):
    """Q25: if GET /reservations/{reference} fails, the booked notice is built from the answer
    (the replayed Table 2), still a booked notice with the reference."""
    _, reference = lost_answer_then_moved(reset, api, page, tid)
    page.route(f"**/reservations/{reference}", lambda route: route.abort())
    page.click(tid("booking-submit"))
    page.wait_for_selector(tid("confirmation"), timeout=15_000)
    assert page.inner_text(tid("confirmation-tables")).strip() == "Table 2"
    assert page.inner_text(tid("confirmation-reference")).strip() == reference


# ---- the lookup of moved and amended bookings (R404, DESIGN 2, H7) ---------------------------------------------------

def test_a_moved_bookings_lookup_shows_only_its_current_tables(reset, api, page, tid):
    """R404/DESIGN 2/H7: a plan closing Table 2 moves A (party 4) to the pair Tables 1 + 3 and B
    (party 2) to Table 1; each lookup names and draws its new tables (seats from its accepted
    terms: 4 and 2 dots) with When, Where and Party as before, no word "moved", and a refused
    cancel still states its 7-day cutoff."""
    ada, _ = world(reset, api, LOOKUP_RESTAURANT, [seed("MOVEAA", "t_2", NEAR, "18:00", party=4),
                                                   seed("MOVEBB", "t_2", NEAR, "21:00", party=2)])
    log_in(page, tid)
    before = {}
    for ref in ("MOVEAA", "MOVEBB"):
        look_up(page, tid, ref)
        before[ref] = detail(page, tid)
    assert close(ada, "t_2", NEAR, "18:00", "23:00") == {"MOVEAA": ["t_1", "t_3"], "MOVEBB": ["t_1"]}
    for ref, (name, seats) in {"MOVEAA": ("Tables 1 + 3", 4), "MOVEBB": ("Table 1", 2)}.items():
        look_up(page, tid, ref)
        now = detail(page, tid)
        assert (now["tables"], now["seats"]) == (name, seats), now
        assert now["rows"] == before[ref]["rows"] and before[ref]["tables"] == "Table 2", (now, before[ref])
        assert "moved" not in now["text"].lower()
        page.click(tid("reservation-cancel-button"))
        page.wait_for_selector(tid("reservation-error"))
        assert "until seven days before it starts" in page.inner_text(tid("reservation-error")).replace(" ", " ")


def test_an_amended_occurrences_lookup_shows_its_new_time(reset, api, page, tid):
    """R404/DESIGN 2: a series of two amended to 20:30 - occurrence 1's lookup reads 20:30 on its date."""
    ada, _ = world(reset, api, GRID_RESTAURANT, [seed("ANCH01", "t_2", DATE, "19:00")])
    series = assert_status(ada.post("/series", idempotency_key=new_key(), json={
        "anchor_reference": "ANCH01", "count": 2, "interval_weeks": 1}), 201).json()
    assert_status(ada.post(f"/series/{series['series_id']}/amend", idempotency_key=new_key(), json={
        "expected_revision": 1, "from_index": 0, "local_time": "20:30"}), 201)
    log_in(page, tid)
    look_up(page, tid, series["occurrences"][1]["reference"])
    when = detail(page, tid)["rows"]["When"]
    later = dt.date.fromisoformat(DATE) + dt.timedelta(weeks=1)
    assert when.endswith("20:30") and f"{later.day} {later.strftime('%B')}" in when, when


# ---- widths and requests (DESIGN, R404) ------------------------------------------------------------------------------

@pytest.mark.parametrize("width", [375, 1280])
def test_the_changed_screens_fit_and_fetch_nothing_off_site(reset, api, page, tid, base_url, width):
    """No sideways scroll and no off-site request on the grid after an application (party 5), the
    refused create and a moved booking's lookup."""
    page.set_viewport_size({"width": width, "height": 900})
    requests = off_site(page, base_url)
    ada, _ = world(reset, api, GRID_RESTAURANT, [seed("MOVE01", "t_2", DATE, "19:00")])
    close(ada, "t_2", DATE, "19:00", "21:00")
    log_in(page, tid)
    search(page, tid, DATE, 5)
    widths = {"grid": page.evaluate("() => document.documentElement.scrollWidth")}
    search(page, tid, DATE, 2)
    open_form(page, tid, "slot-t_3-20:00")
    assert_status(api().authenticate(fx.BOB["email"], fx.BOB["password"]).post("/reservations", idempotency_key=new_key(), json={
        "restaurant_id": "r_anker", "table_id": "t_3", "starts_at_local": fx.local(DATE, "20:00"), "party_size": 2}), 201)
    page.click(tid("booking-submit"))
    refusal_text(page, tid)
    widths["refused"] = page.evaluate("() => document.documentElement.scrollWidth")
    look_up(page, tid, "MOVE01")
    widths["lookup"] = page.evaluate("() => document.documentElement.scrollWidth")
    assert all(w <= width for w in widths.values()), widths
    assert all(url.startswith(base_url) for url in requests), [u for u in requests if not u.startswith(base_url)]


# ---- the CSS merge: computed styles unchanged (v3.6 pass criterion) --------------------------------------------------

STYLES = """() => { const out = {}; const hash = (s) => { let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return h; };
  const path = (el) => { const parts = []; for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      let i = 1; for (let s = n.previousElementSibling; s; s = s.previousElementSibling) if (s.tagName === n.tagName) i++;
      parts.unshift(`${n.tagName.toLowerCase()}:${i}`); } return parts.join('>'); };
  for (const el of document.querySelectorAll('*')) for (const pseudo of [null, '::before', '::after']) {
    const cs = getComputedStyle(el, pseudo); const text = [...cs].sort().map((p) => `${p}:${cs.getPropertyValue(p)}`).join(';');  // custom properties come in no fixed order
    out[path(el) + (pseudo || '')] = hash(text); }
  return out; }"""
STILL = "*, *::before, *::after { transition: none !important; animation: none !important; caret-color: transparent !important; }"


def states(page, tid, base, api_base):
    """Drive one service through the nine states, yielding each name when it is on screen."""
    with Api(api_base) as control:
        assert_status(control.post("/_test/reset", json=fx.fixture(restaurants=[GRID_RESTAURANT], reservations=[
            seed("LOOK01", "t_4", DATE, "18:00", party=5)])), 204)
    bob = Api(api_base).authenticate(fx.BOB["email"], fx.BOB["password"])
    page.goto(f"{base}/login"); page.wait_for_selector(tid("login-submit")); yield "login"
    page.goto(f"{base}/signup"); page.wait_for_selector(tid("signup-submit")); yield "signup"
    page.goto(f"{base}/login")
    page.fill(tid("login-email"), fx.ADA["email"]); page.fill(tid("login-password"), fx.ADA["password"])
    page.click(tid("login-submit")); page.wait_for_selector(tid("current-user"))
    page.goto(f"{base}/"); page.wait_for_selector(tid("search-button")); yield "idle"
    held = []
    page.route("**/availability?*", lambda route: held.append(route))
    page.select_option(tid("restaurant-select"), "r_anker"); page.fill(tid("date-input"), DATE)
    page.fill(tid("party-size-input"), "2"); page.click(tid("search-button"))
    page.wait_for_selector(".loading-track", timeout=5000)
    yield "loading"
    for route in held:
        route.continue_()
    page.unroute("**/availability?*")
    page.wait_for_selector(tid("availability-grid")); yield "results"
    open_form(page, tid, "slot-t_3-20:00")
    assert_status(bob.post("/reservations", idempotency_key=new_key(), json={
        "restaurant_id": "r_anker", "table_id": "t_3", "starts_at_local": fx.local(DATE, "20:00"), "party_size": 2}), 201)
    page.click(tid("booking-submit")); page.wait_for_selector(tid("booking-error"))
    page.evaluate("(sel) => { for (const n of document.querySelectorAll(sel + ' p')) n.textContent = 'x'; }", tid("booking-error"))
    yield "refused"
    open_form(page, tid, "slot-t_1-21:00")
    page.route("**/reservations", lambda route: route.abort() if route.request.method == "POST" else route.continue_())
    page.click(tid("booking-submit")); page.wait_for_selector(tid("booking-uncertain")); yield "uncertain"
    page.unroute("**/reservations")
    page.click(tid("booking-submit")); page.wait_for_selector(tid("confirmation")); yield "booked"
    page.goto(f"{base}/lookup"); page.wait_for_selector(tid("lookup-submit"))
    page.fill(tid("lookup-reference-input"), "LOOK01"); page.click(tid("lookup-submit"))
    page.wait_for_selector(tid("reservation-detail")); yield "lookup"


@pytest.mark.parametrize("width", [375, 900, 1280])
def test_every_computed_style_equals_the_base_in_every_state(browser, base_url, tid, width):
    """v3.6/R470: for every element (and its ::before/::after) in nine states - log in, sign up,
    idle, loading, results, refused, uncertain, booked, lookup - the computed style on this
    service equals the base's (5b77876), property for property; transitions stilled on both, the
    refusal text blanked on both (its wording is the intended change)."""
    base = os.environ.get("TABLEKEEPER_BASE_UI_URL", "").rstrip("/")
    assert base, "set TABLEKEEPER_BASE_UI_URL to the S4-I6 base (5b77876's stage-4) service"
    both = browser.browser_type.launch(channel="chromium", args=[f"--unsafely-treat-insecure-origin-as-secure={base_url},{base}"])
    seen = {}
    for name, service in (("new", base_url), ("base", base)):
        context = both.new_context(viewport={"width": width, "height": 900})
        context.add_init_script(f"document.addEventListener('DOMContentLoaded', () => {{ const s = document.createElement('style'); "
                                f"s.textContent = {STILL!r}; document.head.append(s); }});")
        page = context.new_page()
        page.set_default_timeout(10_000)
        seen[name] = {}
        for state in states(page, tid, service, service):
            page.evaluate("document.fonts.ready")
            seen[name][state] = page.evaluate(STYLES)
        context.close()
    both.close()
    differences = {state: sorted(k for k in seen["new"][state].keys() | seen["base"][state].keys()
                                 if seen["new"][state].get(k) != seen["base"][state].get(k))
                   for state in seen["new"]}
    print({state: (len(seen["new"][state]), len(diff)) for state, diff in differences.items()})
    assert not any(differences.values()), {state: diff[:5] for state, diff in differences.items() if diff}
