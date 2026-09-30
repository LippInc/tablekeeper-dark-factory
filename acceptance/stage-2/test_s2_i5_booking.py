"""S2-I5 acceptance checks (verifier seat): the booking panel and the confirmation, from the
stage-2 specification ("Competing clients and uncertain outcomes", "Booking form",
"Confirmation", "Existing clients after an upgrade", the combination lines of "UI") and the
task's design direction (R286-R294), with the plan's G2, G3, E7 and E8.

Every check runs for a single table and for a declared pair where the specification says the
rules apply to combinations too (R213, R273). Browser checks in the harness's headless
Chromium; the upgrade check needs `--previous-base-url` (the stage-1 service of the same
checkout). R.., E.. and G.. name the room plan's requirement lines and decisions.
"""
from __future__ import annotations

import pytest

import fixtures as fx
from harness.http import RESET_TIMEOUT, Api, assert_status

pytestmark = pytest.mark.stage(2)

DATE = fx.booking_date()
LINDEN = {**fx.restaurant("r_linden", name="Zwei Linden",
                          tables=[{"id": "t_w", "label": "Window", "capacity": 2},
                                  {"id": "t_b", "label": "Bar", "capacity": 4},
                                  {"id": "t_c", "label": "Corner", "capacity": 6}]),
          "combinable": [["t_b", "t_w"]]}                                   # 18:00-23:00
CASES = {
    "single": {"cell": "slot-t_b-19:00", "tables": ["t_b"], "labels": ["Bar"], "party": 3, "at": "19:00",
               "other_party": 2, "too_many": 5},
    "pair": {"cell": "slot-t_b+t_w-20:00", "tables": ["t_b", "t_w"], "labels": ["Bar", "Window"], "party": 5,
             "at": "20:00", "other_party": 6, "too_many": 7},
}
IDS = list(CASES)
TOKENS = {"brass": "rgb(210, 166, 90)", "claret": "rgb(236, 148, 132)", "sage": "rgb(169, 199, 156)",
          "pewter": "rgb(175, 184, 200)"}
OUTCOMES = ("confirmation", "booking-error", "booking-uncertain")

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
CLARET_USERS = """(claret) => [...document.querySelectorAll('body *')].filter((n) => n.checkVisibility()).filter((n) => {
  const s = getComputedStyle(n);
  const side = (k) => s[`border${k}Color`] === claret && parseFloat(s[`border${k}Width`]) > 0;
  return s.color === claret || s.backgroundColor === claret || ['Top', 'Right', 'Bottom', 'Left'].some(side);
}).map((n) => n.dataset.testid || n.getAttribute('class') || n.tagName)"""


@pytest.fixture
def world(reset):
    reset(fx.fixture(restaurants=[LINDEN]))


def log_in(page, tid) -> None:
    page.goto("/login")
    page.fill(tid("login-email"), fx.ADA["email"])
    page.fill(tid("login-password"), fx.ADA["password"])
    page.click(tid("login-submit"))
    page.wait_for_selector(tid("current-user"))


def submit_search(page, tid, party) -> None:
    page.select_option(tid("restaurant-select"), "r_linden")
    page.fill(tid("date-input"), DATE)
    page.fill(tid("party-size-input"), str(party))
    page.click(tid("search-button"))


def open_form(page, tid, case: dict, *, sign_in: bool = True) -> None:
    """Signed in, a search for the case's party, and its cell clicked."""
    if sign_in:
        log_in(page, tid)
    page.goto("/")
    page.wait_for_selector(tid("search-button"))
    submit_search(page, tid, case["party"])
    page.wait_for_selector(tid(case["cell"]))
    page.click(tid(case["cell"]))
    page.wait_for_selector(tid("booking-form"))


def posts(page) -> list[dict]:
    """Every POST /reservations the page sends: its key and its body."""
    sent = []
    page.on("request", lambda r: r.method == "POST" and r.url.endswith("/reservations") and sent.append(
        {"key": r.headers.get("idempotency-key"), "body": r.post_data_json}))
    return sent


def outcome(page, tid, testid: str) -> str:
    """Wait for one outcome; the other two must be absent from the page, not hidden."""
    page.wait_for_selector(tid(testid), timeout=15_000)
    text = page.inner_text(tid(testid)).strip()
    assert text, f"{testid} is empty"
    present = [other for other in OUTCOMES if other != testid and page.query_selector(tid(other)) is not None]
    assert not present, f"{testid} shown together with {present}"
    return text


def bookings(api, email=fx.ADA["email"], password=fx.ADA["password"]) -> list[dict]:
    return assert_status(api().authenticate(email, password).get("/reservations"), 200).json()["reservations"]


def body_of(case: dict, party=None) -> dict:
    tables = {"table_id": case["tables"][0]} if len(case["tables"]) == 1 else {"table_ids": case["tables"]}
    return {"restaurant_id": "r_linden", **tables, "starts_at_local": fx.local(DATE, case["at"]),
            "party_size": party or case["party"]}


# ---- the form (R239, R270, R286) ---------------------------------------------------------------

@pytest.mark.parametrize("name", IDS)
def test_the_form_names_every_table_and_the_time_with_the_party_filled_in(world, page, tid, name):
    """R239/R270: `booking-summary` names every table of the choice and its local start
    time; `booking-party-size` holds the searched party."""
    case = CASES[name]
    open_form(page, tid, case)
    summary = page.inner_text(tid("booking-summary"))
    assert all(label in summary for label in case["labels"]) and case["at"] in summary, summary
    assert page.input_value(tid("booking-party-size")) == str(case["party"])


# ---- booked (R240, R241, R243, R269, G3) --------------------------------------------------------------

@pytest.mark.parametrize("name", IDS)
def test_a_booking_is_confirmed_exactly_and_the_form_stays(world, page, tid, api, name):
    """R243/R269/R240/G3: the confirmation holds the service's reference and nothing else,
    details naming the restaurant, every table and the local time, `confirmation-tables`
    naming every table; the form stays; a single table is sent as `table_id`."""
    case = CASES[name]
    sent = posts(page)
    open_form(page, tid, case)
    page.click(tid("booking-submit"))
    outcome(page, tid, "confirmation")
    [booking] = bookings(api)
    assert page.text_content(tid("confirmation-reference")).strip() == booking["reference"]
    assert page.inner_text(tid("confirmation-reference")).strip() == booking["reference"]
    details = page.inner_text(tid("confirmation-details"))
    assert "Zwei Linden" in details and case["at"] in details, details
    assert all(label in details for label in case["labels"]), details
    tables = page.inner_text(tid("confirmation-tables"))
    assert all(label in tables for label in case["labels"]), tables
    assert page.query_selector(tid("booking-form")) is not None
    assert [s["body"] for s in sent] == [body_of(case)]
    assert booking["table_ids"] == case["tables"]


@pytest.mark.parametrize("name", IDS)
def test_an_unchanged_resubmit_returns_the_same_booking(world, page, tid, api, name):
    """R241/R210/§7: pressing again without changing a field sends the same key and body and
    shows the same reference, without `booking-error` and without another booking."""
    case = CASES[name]
    sent = posts(page)
    open_form(page, tid, case)
    page.click(tid("booking-submit"))
    first = outcome(page, tid, "confirmation")
    reference = page.inner_text(tid("confirmation-reference")).strip()
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/reservations")) as again:
        page.click(tid("booking-submit"))
    assert again.value.status == 200, again.value.status
    page.wait_for_timeout(300)
    outcome(page, tid, "confirmation")
    assert len(sent) == 2 and sent[0] == sent[1], sent
    assert page.inner_text(tid("confirmation-reference")).strip() == reference
    assert first
    assert len(bookings(api)) == 1


@pytest.mark.parametrize("name", IDS)
def test_a_changed_field_makes_a_new_request(world, page, tid, api, name):
    """R242: after a booking, a changed party size is a new request with a new key (here
    refused: the booking just made holds the table)."""
    case = CASES[name]
    sent = posts(page)
    open_form(page, tid, case)
    page.click(tid("booking-submit"))
    outcome(page, tid, "confirmation")
    page.fill(tid("booking-party-size"), str(case["other_party"]))
    page.click(tid("booking-submit"))
    outcome(page, tid, "booking-error")
    assert len(sent) == 2 and sent[1]["key"] != sent[0]["key"], sent
    assert sent[1]["body"] == body_of(case, case["other_party"])
    assert len(bookings(api)) == 1


# ---- refused (R208, R212, R274) -------------------------------------------------------------------------

def take(api, case: dict) -> None:
    """Another diner books the case's table (for a pair, one of its tables) at its time."""
    bob = api().authenticate(fx.BOB["email"], fx.BOB["password"])
    assert_status(bob.post("/reservations", idempotency_key=f"bob-{case['cell']}", json={
        "restaurant_id": "r_linden", "table_id": case["tables"][-1], "starts_at_local": fx.local(DATE, case["at"]),
        "party_size": 2}), 201)


@pytest.mark.parametrize("name", IDS)
def test_a_table_taken_meanwhile_is_refused_and_the_form_and_inputs_stay(world, page, tid, api, name):
    """R208/R274: another client takes the table after the form opens: `booking-error`, no
    confirmation, the availability is asked again and the cell shows taken, the form and the
    edited party size stay, nothing is booked."""
    case = CASES[name]
    open_form(page, tid, case)
    page.fill(tid("booking-party-size"), str(case["other_party"]))
    take(api, case)
    searches = []
    page.on("request", lambda r: "/availability" in r.url and searches.append(r.url))
    page.click(tid("booking-submit"))
    outcome(page, tid, "booking-error")
    assert searches, "availability was not refreshed"
    page.wait_for_function(f"() => document.querySelector(\"[data-testid='{case['cell']}']\")?.getAttribute('data-available') === 'false'",
                           timeout=5000)
    assert page.query_selector(tid("booking-form")) is not None
    assert page.input_value(tid("booking-party-size")) == str(case["other_party"])
    assert bookings(api) == []


@pytest.mark.parametrize("name", IDS)
def test_a_confirmed_rejection_shows_booking_error(world, page, tid, api, name):
    """R212/E7: a refusal the service states (a party the tables cannot seat) is
    `booking-error`, not uncertain and not booked."""
    case = CASES[name]
    open_form(page, tid, case)
    page.fill(tid("booking-party-size"), str(case["too_many"]))
    page.click(tid("booking-submit"))
    outcome(page, tid, "booking-error")
    assert bookings(api) == []


# ---- uncertain (R209, R210, R211, R215, E7) -----------------------------------------------------------------

@pytest.mark.parametrize("name", IDS)
def test_an_answer_lost_after_the_commit_is_uncertain_and_the_retry_recovers_it(world, page, tid, api, name):
    """R209/R210/R211/R213: the booking commits but its answer is lost: non-empty
    `booking-uncertain`, no error, no confirmation; the unchanged form retries with the same
    key and body and shows the original reference, the uncertainty gone, one booking."""
    case = CASES[name]
    sent = posts(page)
    open_form(page, tid, case)

    def lose(route):
        route.fetch()                         # the service commits
        route.abort("connectionreset")        # the answer never arrives

    page.route("**/reservations", lose, times=1)
    page.click(tid("booking-submit"))
    outcome(page, tid, "booking-uncertain")
    [committed] = bookings(api)
    page.click(tid("booking-submit"))
    outcome(page, tid, "confirmation")
    assert page.inner_text(tid("confirmation-reference")).strip() == committed["reference"]
    assert len(sent) == 2 and sent[0] == sent[1], sent
    assert len(bookings(api)) == 1


@pytest.mark.parametrize("failure", ["server_error", "unreadable_success", "no_answer", "client_timeout"])
def test_an_answer_that_confirms_nothing_is_uncertain(world, page, tid, api, failure):
    """R209/E7: a 5xx, a 2xx whose body does not parse, a connection that fails, and no
    answer within the client's patience are uncertain: `booking-uncertain`, no error, no
    confirmation."""
    case = CASES["single"]
    open_form(page, tid, case)
    held = []
    handlers = {
        "server_error": lambda r: r.fulfill(status=500, content_type="application/json",
                                            body='{"error":{"code":"internal_error","message":"unexpected error"}}'),
        "unreadable_success": lambda r: r.fulfill(status=201, content_type="application/json", body="{not json"),
        "no_answer": lambda r: r.abort("connectionreset"),
        "client_timeout": lambda r: held.append(r),
    }
    page.route("**/reservations", handlers[failure])
    page.click(tid("booking-submit"))
    outcome(page, tid, "booking-uncertain")


@pytest.mark.parametrize("name", IDS)
def test_no_confirmation_is_made_from_cached_data(world, page, tid, api, name):
    """R215: after a booking, an attempt that gets no answer shows uncertainty, never the
    earlier confirmation."""
    case = CASES[name]
    open_form(page, tid, case)
    page.click(tid("booking-submit"))
    outcome(page, tid, "confirmation")
    page.route("**/reservations", lambda r: r.abort("connectionreset"))
    page.click(tid("booking-submit"))
    outcome(page, tid, "booking-uncertain")


# ---- competing searches (R207 form) ------------------------------------------------------------------------------

def test_a_late_search_answer_never_changes_the_open_form(world, page, tid):
    """R207: search A is answered only after search B's form is open; the form, its summary
    and its party size stay as B left them."""
    case = CASES["single"]
    log_in(page, tid)
    page.goto("/")
    page.wait_for_selector(tid("search-button"))
    held, gate = [], {"closed": True}
    page.route("**/availability?*", lambda r: held.append(r) if gate["closed"] else r.continue_())
    page.route("**/restaurants/*", lambda r: held.append(r) if gate["closed"] else r.continue_())
    submit_search(page, tid, 2)                                    # A: held
    for _ in range(50):
        if len(held) >= 2:
            break
        page.wait_for_timeout(100)
    gate["closed"] = False
    submit_search(page, tid, case["party"])                        # B
    page.wait_for_selector(tid(case["cell"]))
    page.click(tid(case["cell"]))
    page.wait_for_selector(tid("booking-form"))
    page.fill(tid("booking-party-size"), "4")
    before = page.inner_text(tid("booking-summary"))
    for route in held:
        try:
            route.continue_()
        except Exception:  # the page may have abandoned A's request
            pass
    page.wait_for_timeout(1500)
    assert page.query_selector(tid("booking-form")) is not None
    assert page.inner_text(tid("booking-summary")) == before
    assert page.input_value(tid("booking-party-size")) == "4"


# ---- times in another zone (G2) ---------------------------------------------------------------------------------

def test_times_are_the_local_start_whatever_the_browsers_zone(world, browser, base_url, tid):
    """R239/R243/G2: in a browser far from the restaurant's zone, the summary and the
    confirmation show the restaurant's local start time."""
    case = CASES["single"]
    context = browser.new_context(base_url=base_url, timezone_id="Pacific/Kiritimati")
    context.set_default_timeout(10_000)
    page = context.new_page()
    try:
        open_form(page, tid, case)
        assert case["at"] in page.inner_text(tid("booking-summary"))
        page.click(tid("booking-submit"))
        outcome(page, tid, "confirmation")
        assert case["at"] in page.inner_text(tid("confirmation-details"))
    finally:
        context.close()


# ---- the look of the moments (R294, R291, R288, R285, R224, R225, R296) --------------------------------------------

def width_of(page) -> float:
    return page.evaluate("() => document.querySelector(\"[data-testid='booking-submit']\").getBoundingClientRect().width")


@pytest.mark.parametrize("width", [375, 1280])
def test_the_submit_keeps_its_width_in_every_moment(world, page, tid, width):
    """R294: `booking-submit` has one width idle, loading, uncertain, refused and booked."""
    page.set_viewport_size({"width": width, "height": 900})
    case = CASES["single"]
    open_form(page, tid, case)
    widths = {"idle": width_of(page)}
    held = []
    page.route("**/reservations", lambda r: held.append(r), times=1)
    page.click(tid("booking-submit"))
    for _ in range(50):
        if held:
            break
        page.wait_for_timeout(100)
    widths["loading"] = width_of(page)
    held[0].abort("connectionreset")
    outcome(page, tid, "booking-uncertain")
    widths["uncertain"] = width_of(page)
    page.fill(tid("booking-party-size"), str(case["too_many"]))
    page.click(tid("booking-submit"))
    outcome(page, tid, "booking-error")
    widths["refused"] = width_of(page)
    page.fill(tid("booking-party-size"), str(case["party"]))
    page.click(tid("booking-submit"))
    outcome(page, tid, "confirmation")
    widths["booked"] = width_of(page)
    assert len(set(widths.values())) == 1, widths


def test_the_reference_uses_cormorant_lining_tabular_numerals(world, page, tid):
    """R285 (S2N-4): the booking reference is Cormorant with lining, tabular numerals."""
    open_form(page, tid, CASES["single"])
    page.click(tid("booking-submit"))
    outcome(page, tid, "confirmation")
    family, numerals = page.evaluate("""() => { const s = getComputedStyle(document.querySelector("[data-testid='confirmation-reference']"));
      return [s.fontFamily, s.fontVariantNumeric]; }""")
    assert family.strip('"').startswith("Cormorant"), family
    assert {"lining-nums", "tabular-nums"} <= set(numerals.split()), numerals


RULE = """(testid) => { const n = testid ? document.querySelector(`[data-testid='${testid}']`)
    : [...document.querySelectorAll("[data-testid='booking-form'] *")].find((e) => parseFloat(getComputedStyle(e).borderLeftWidth) > 0
      && !['booking-summary'].includes(e.dataset.testid));
  const s = getComputedStyle(n); return [s.borderLeftColor, s.borderLeftStyle]; }"""


@pytest.mark.parametrize("name", IDS)
@pytest.mark.parametrize("width", [375, 1280])
def test_every_moment_fits_reads_and_looks_its_own(world, page, tid, api, name, width):
    """R291/R288/R224/R225/R296: loading, uncertain, refused and booked each have their own
    rule (uncertain dashed pewter, refused claret, booked sage); the panel is beside the
    results on desktop and below them on a phone; no moment scrolls sideways, puts text
    outside the viewport or has text under 4.5:1; claret only on the refusal."""
    page.set_viewport_size({"width": width, "height": 900})
    case = CASES[name]
    open_form(page, tid, case)
    layout = page.evaluate("""() => { const panel = document.querySelector("[data-testid='booking-form']").getBoundingClientRect();
      const grid = document.querySelector("[data-testid='availability-grid']").getBoundingClientRect();
      return { beside: panel.left >= grid.right - 1, below: panel.top >= grid.bottom - 1 }; }""")
    assert layout["beside" if width >= 1024 else "below"], layout
    problems, rules = [], {}

    def look(moment, claret_allowed):
        size = page.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
        if size[0] > size[1]:
            problems.append((moment, "scroll", size))
        problems.extend((moment, "outside", t) for t in page.evaluate(OUTSIDE))
        problems.extend((moment, "contrast", r) for r in page.evaluate(CONTRAST))
        if not claret_allowed:
            problems.extend((moment, "claret", c) for c in page.evaluate(CLARET_USERS, TOKENS["claret"]))

    look("form", False)
    held = []
    page.route("**/reservations", lambda r: held.append(r), times=1)
    page.click(tid("booking-submit"))
    for _ in range(50):
        if held:
            break
        page.wait_for_timeout(100)
    page.wait_for_timeout(200)
    rules["loading"] = tuple(page.evaluate(RULE, None))
    look("loading", False)
    held[0].abort("connectionreset")
    outcome(page, tid, "booking-uncertain")
    rules["uncertain"] = tuple(page.evaluate(RULE, "booking-uncertain"))
    look("uncertain", False)
    page.fill(tid("booking-party-size"), str(case["too_many"]))
    page.click(tid("booking-submit"))
    outcome(page, tid, "booking-error")
    rules["refused"] = tuple(page.evaluate(RULE, "booking-error"))
    look("refused", True)
    page.fill(tid("booking-party-size"), str(case["party"]))
    page.click(tid("booking-submit"))
    outcome(page, tid, "confirmation")
    rules["booked"] = tuple(page.evaluate(RULE, "confirmation"))
    look("booked", False)
    assert rules["uncertain"] == (TOKENS["pewter"], "dashed"), rules
    assert rules["refused"][0] == TOKENS["claret"] and rules["booked"][0] == TOKENS["sage"], rules
    assert len(set(rules.values())) == 4, rules
    assert not problems, problems[:8]


# ---- the upgrade in the middle (R246, R248, R249, G3, E8) ----------------------------------------------------------

def test_a_booking_lost_before_the_upgrade_is_recovered_after_it(reset, page, tid, previous_api, base_url):
    """R246/R248/R249/G3/E8: the stage-2 page talks to the stage-1 service (stage-1 shapes: no
    pair cells); a booking commits there but its answer is lost; stage 1 is exported and
    imported into stage 2 between browser requests; with the page now talking to stage 2,
    the unchanged form retries with the same key and a `table_id` body, gets 200 with the
    stored stage-1 body and shows the original reference, still signed in, never reloaded."""
    case = CASES["single"]
    fixture = fx.fixture(restaurants=[LINDEN])
    assert_status(previous_api.post("/_test/reset", json=fixture), 204)
    reset(fx.fixture())
    previous = previous_api.base_url.rstrip("/")
    here = base_url.rstrip("/")
    state = {"lose": True, "stage_1_answer": None}

    def to_stage_1(route):
        answer = route.fetch(url=previous + route.request.url[len(here):])
        if route.request.method == "POST" and route.request.url.endswith("/reservations") and state["lose"]:
            state["lose"] = False
            state["stage_1_answer"] = (answer.status, answer.text()[:120])
            route.abort("connectionreset")          # committed on stage 1, answer lost
            return
        route.fulfill(response=answer)

    patterns = ("**/auth/*", "**/restaurants", "**/restaurants/*", "**/availability?*", "**/reservations",
                "**/reservations/*")
    for pattern in patterns:
        page.route(pattern, to_stage_1)
    sent, errors = posts(page), []
    page.on("pageerror", lambda e: errors.append(str(e)))
    log_in(page, tid)
    page.goto("/")
    page.wait_for_selector(tid("search-button"))
    submit_search(page, tid, case["party"])
    page.wait_for_selector(tid(case["cell"]))
    cells = page.evaluate("""() => Object.fromEntries([...document.querySelectorAll("[data-testid^='slot-']")]
      .map((n) => [n.dataset.testid, n.getAttribute('data-available')]))""")
    assert cells and not [c for c in cells if "+" in c], "stage-1 shapes: no pair cells"
    assert cells[case["cell"]] == "true", f"stage-1 shapes: {case['cell']} is open on the stage-1 service"
    page.click(tid(case["cell"]))
    page.wait_for_selector(tid("booking-form"))
    page.evaluate("() => { window.__notReloaded = true; }")
    page.click(tid("booking-submit"))
    outcome(page, tid, "booking-uncertain")
    with Api(previous) as old:
        made = assert_status(old.authenticate(fx.ADA["email"], fx.ADA["password"]).get("/reservations"),
                             200).json()["reservations"]
    assert len(made) == 1, f"the booking did not commit on the stage-1 service: {state['stage_1_answer']}"
    committed = made[0]
    with Api(previous, timeout=RESET_TIMEOUT) as source, Api(here, timeout=RESET_TIMEOUT) as target:
        exported = assert_status(source.get("/_test/export"), 200).json()
        assert_status(target.post("/_test/import", json=exported), 204)
    receipt = next(r for r in exported["state"]["receipts"] if r["key"] == sent[0]["key"])
    for pattern in patterns:
        page.unroute(pattern)
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/reservations")) as retry:
        page.click(tid("booking-submit"))
    assert len(sent) == 2 and sent[0] == sent[1], sent
    assert "table_id" in sent[1]["body"] and "table_ids" not in sent[1]["body"], sent[1]
    assert retry.value.status == 200, (retry.value.status, retry.value.text()[:200])
    assert retry.value.json() == receipt["response"], retry.value.text()[:300]
    page.wait_for_timeout(500)
    assert not errors, errors
    outcome(page, tid, "confirmation")
    assert page.inner_text(tid("confirmation-reference")).strip() == committed["reference"]
    assert "Bar" in page.inner_text(tid("confirmation-tables"))
    assert page.query_selector(tid("current-user")) is not None
    assert page.evaluate("() => window.__notReloaded === true"), "the page was reloaded"
