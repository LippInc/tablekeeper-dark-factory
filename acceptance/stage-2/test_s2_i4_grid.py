"""S2-I4 acceptance checks (verifier seat): the search and the availability grid, from the
stage-2 specification ("Search and availability grid", "Competing clients and uncertain
outcomes", the combination cells of "UI") and the task's design direction (R286-R296), with
the plan's decisions E1 (combination rows), E6 (signed-out click), G2 (sequence check) and
G3 (stage-1 shapes).

Browser checks in the harness's headless Chromium. Which element carries which colour follows
the design system (DESIGN.md 3.4-3.6); every value is an R284 token. R.., E.. and G.. name the
room plan's requirement lines and decisions.
"""
from __future__ import annotations

import datetime as dt
import re
from urllib.parse import urlsplit

import pytest

import fixtures as fx
from harness.http import Api, assert_status

pytestmark = pytest.mark.stage(2)

DATE = fx.booking_date()
TOKENS = {"page": "rgb(28, 20, 24)", "raised": "rgb(40, 29, 35)", "recess": "rgb(18, 12, 15)",
          "taken": "rgb(143, 128, 132)", "brass": "rgb(210, 166, 90)"}
CLARET = "rgb(236, 148, 132)"

ANKER = {**fx.restaurant(), "combinable": [["t_1", "t_2"], ["t_3", "t_2"]]}          # 18:00-23:00
LINDEN = {**fx.restaurant("r_linden", name="Zwei Linden", opening_hours=fx.all_week("12:00", "15:00"),
                          tables=[{"id": "t_w", "label": "Window", "capacity": 2},
                                  {"id": "t_b", "label": "Bar", "capacity": 4}]),
          "combinable": [["t_b", "t_w"]]}                                            # declared "backwards"
CLOSED = fx.restaurant("r_closed", name="Am Ruhetag",
                       opening_hours=[h for h in fx.all_week() if h["weekday"] != fx.weekday_of(DATE)])
FULL = fx.restaurant("r_full", name="Kleine Stube", opening_hours=fx.all_week("18:00", "20:00"),
                     tables=[{"id": "t_s", "label": "Stube", "capacity": 4}])
RESTAURANTS = {r["id"]: r for r in (ANKER, LINDEN, CLOSED, FULL)}


def seed(reference: str, restaurant_id: str, tables: list[str], hhmm: str, party: int = 2) -> dict:
    return {"id": f"res_{reference}", "reference": reference, "user_id": fx.BOB["id"],
            "restaurant_id": restaurant_id, "table_ids": tables,
            "starts_at_local": fx.local(DATE, hhmm), "party_size": party}


WORLD = fx.fixture(restaurants=[ANKER, LINDEN, CLOSED, FULL], reservations=[
    seed("GRID01", "r_anker", ["t_2"], "19:00"), seed("GRID02", "r_anker", ["t_1", "t_2"], "21:00", 5),
    seed("GRID03", "r_anker", ["t_3"], "18:00"), seed("GRID04", "r_full", ["t_s"], "18:00"),
    seed("GRID05", "r_linden", ["t_b"], "13:30")])

CELLS = """() => Object.fromEntries([...document.querySelectorAll("[data-testid^='slot-']")]
  .map((n) => [n.dataset.testid, n.getAttribute('data-available')]))"""
OUTSIDE_FORM_TEXT = """() => { const main = document.querySelector('main').cloneNode(true);
  main.querySelectorAll('form.search-band-form, select, input').forEach((n) => n.remove());
  return main.innerText; }"""
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
    """The date as the diner reads it: weekday, day and month (R295)."""
    day = dt.date.fromisoformat(iso)
    return rf"{day.strftime('%A')},?\s+{day.day}\s+{day.strftime('%B')}"


@pytest.fixture
def world(reset):
    reset(WORLD)


def log_in(page, tid) -> None:
    page.goto("/login")
    page.fill(tid("login-email"), fx.ADA["email"])
    page.fill(tid("login-password"), fx.ADA["password"])
    page.click(tid("login-submit"))
    page.wait_for_selector(tid("current-user"))


def submit(page, tid, restaurant: str, party, date: str = DATE) -> None:
    page.select_option(tid("restaurant-select"), restaurant)
    page.fill(tid("date-input"), date)
    page.fill(tid("party-size-input"), str(party))
    page.click(tid("search-button"))


def search(page, tid, restaurant: str, party, date: str = DATE) -> None:
    """A search from a freshly loaded `/`, waited for until its answer is shown."""
    page.goto("/")
    page.wait_for_selector(tid("search-button"))
    submit(page, tid, restaurant, party, date)
    page.wait_for_selector(f"{tid('availability-grid')}, {tid('no-slots')}")


def expected_cells(anon, restaurant_id: str, party: int) -> dict[str, str]:
    """R234/R236/R268/E1 from `GET /availability`: a cell per table per slot, available when
    the table is in `available_table_ids`; a cell per declared pair (declared order) that
    seats the party, available when the pair is in `available_options`."""
    restaurant = RESTAURANTS[restaurant_id]
    capacity = {t["id"]: t["capacity"] for t in restaurant["tables"]}
    slots = assert_status(anon.get("/availability", params={
        "restaurant_id": restaurant_id, "date": DATE, "party_size": party}), 200).json()["slots"]
    cells = {}
    for slot in slots:
        hhmm = slot["starts_at_local"][11:16]
        for table in restaurant["tables"]:
            cells[f"slot-{table['id']}-{hhmm}"] = str(table["id"] in slot["available_table_ids"]).lower()
        for pair in restaurant.get("combinable", []):
            if sum(capacity[t] for t in pair) >= party:
                cells[f"slot-{'+'.join(pair)}-{hhmm}"] = str(
                    any(option["table_ids"] == pair for option in slot["available_options"])).lower()
    return cells


def first_cell(page, available: bool, pair: bool = False) -> str:
    return page.evaluate("""([available, pair]) => [...document.querySelectorAll("[data-testid^='slot-']")]
      .find((n) => n.getAttribute('data-available') === String(available) && n.dataset.testid.includes('+') === pair)
      .dataset.testid""", [available, pair])


# ---- search band (R231-R233, R295) -------------------------------------------------------------

def test_the_search_band_offers_restaurant_ids_a_date_and_a_party_size(world, page, tid, anon):
    """R231/R232/R233/R295: option values are the restaurant ids in the service's order and
    their text is the name; the date input holds YYYY-MM-DD; the party size is a number."""
    page.goto("/")
    page.wait_for_selector(tid("search-button"))
    options = page.evaluate("""() => [...document.querySelectorAll("[data-testid='restaurant-select'] option")]
      .map((o) => [o.value, o.textContent.trim()])""")
    listed = assert_status(anon.get("/restaurants"), 200).json()["restaurants"]
    assert options == [[r["id"], r["name"]] for r in listed]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", page.input_value(tid("date-input")))
    assert page.get_attribute(tid("party-size-input"), "type") == "number"


# ---- the grid (R234-R236, R268, E1) -----------------------------------------------------------------

@pytest.mark.parametrize("restaurant,party", [("r_anker", p) for p in (1, 2, 4, 5, 6, 7, 11)]
                         + [("r_linden", p) for p in (2, 5, 7)])
def test_every_cell_says_what_the_service_says(world, page, tid, anon, restaurant, party):
    """R234/R236/R268/E1: exactly one cell per table per slot and one per declared pair that
    seats the party (ids in declared order), each `data-available` as `GET /availability`
    answers for the searched party."""
    search(page, tid, restaurant, party)
    assert page.evaluate(CELLS) == expected_cells(anon, restaurant, party)


def test_a_closed_day_shows_no_slots_and_no_grid(world, page, tid):
    """R235/R292: a day without slots shows `no-slots` instead of the grid, naming the
    restaurant and the date in words."""
    search(page, tid, "r_closed", 2)
    assert page.query_selector(tid("availability-grid")) is None
    assert page.evaluate(CELLS) == {}
    text = page.inner_text(tid("no-slots"))
    assert "Am Ruhetag" in text and re.search(in_words(DATE), text), text


# ---- composed states (R292, R295) --------------------------------------------------------------------

def composed(page, name: str, date: str, *, action: bool) -> None:
    text = page.evaluate(OUTSIDE_FORM_TEXT)
    assert name in text and re.search(in_words(date), text), text
    assert not re.search(r"\b\d{4}-\d{2}-\d{2}\b", text), f"a date shown as digits: {text}"
    if action:
        buttons = page.evaluate("""() => [...document.querySelectorAll('main button, main a')]
          .filter((n) => n.checkVisibility() && !n.closest('form.search-band-form') && !n.dataset.testid?.startsWith('slot-'))
          .map((n) => n.innerText.trim())""")
        assert buttons, "one clear next step"


@pytest.mark.parametrize("state", ["before_search", "fully_booked", "failed_refused", "failed_no_answer"])
def test_the_results_area_is_composed_in_every_state(world, page, tid, state):
    """R292/R295/R226: before a search, when no time is free, and when the search fails
    (refused, or no answer), the results area names the restaurant and the date in words and
    offers one next step."""
    page.goto("/")
    page.wait_for_selector(tid("search-button"))
    if state == "before_search":
        page.wait_for_function("() => document.querySelector('main').innerText.includes('Zum Anker')")
        composed(page, "Zum Anker", page.input_value(tid("date-input")), action=False)
        return
    if state == "failed_refused":
        page.route("**/availability?*", lambda r: r.fulfill(status=500, content_type="application/json",
                                                           body='{"error":{"code":"internal_error","message":"x"}}'))
    if state == "failed_no_answer":
        page.route("**/availability?*", lambda r: r.abort("connectionreset"))
    restaurant, name = ("r_full", "Kleine Stube") if state == "fully_booked" else ("r_anker", "Zum Anker")
    submit(page, tid, restaurant, 2)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)
    composed(page, name, DATE, action=True)


# ---- competing searches (R207, G2) --------------------------------------------------------------------

@pytest.mark.parametrize("first,second", [(("r_anker", 5), ("r_linden", 4)), (("r_anker", 5), ("r_anker", 2))],
                         ids=["other_restaurant", "same_restaurant_other_party"])
def test_a_late_answer_never_replaces_a_later_search(world, page, tid, anon, first, second):
    """R207/G2: search A starts, B starts after it and is answered first; A's answer, released
    only then, never replaces B's grid or table labels."""
    held, gate = [], {"closed": False}

    def through(route):
        if gate["closed"]:
            held.append(route)
        else:
            route.continue_()

    page.route("**/availability?*", through)
    page.route("**/restaurants/*", through)
    search(page, tid, "r_linden", 2)                       # an earlier grid on the page
    gate["closed"] = True
    submit(page, tid, *first)                              # A: held
    for _ in range(50):
        if len(held) >= 2:
            break
        page.wait_for_timeout(100)
    assert len(held) >= 2, "search A was not held"
    gate["closed"] = False
    submit(page, tid, *second)                             # B: answered
    expected = expected_cells(anon, *second)
    page.wait_for_function(f"""(expected) => {{ const shown = ({CELLS})();
      return Object.keys(shown).length === Object.keys(expected).length
        && Object.keys(expected).every((k) => shown[k] === expected[k]); }}""", arg=expected, timeout=10_000)
    for route in held:
        try:
            route.continue_()
        except Exception:  # the page may have abandoned A's request already
            pass
    page.wait_for_timeout(1500)
    assert page.evaluate(CELLS) == expected
    grid = page.inner_text(tid("availability-grid"))
    labels = [t["label"] for t in RESTAURANTS[second[0]]["tables"]]
    assert all(label in grid for label in labels), grid
    if first[0] != second[0]:
        assert RESTAURANTS[first[0]]["name"] not in page.evaluate(OUTSIDE_FORM_TEXT)


def test_a_new_search_closes_the_booking_form(world, page, tid):
    """R207/G2: a new search closes an open booking form."""
    log_in(page, tid)
    search(page, tid, "r_linden", 2)
    page.click(tid(first_cell(page, True)))
    page.wait_for_selector(tid("booking-form"))
    submit(page, tid, "r_linden", 2)
    page.wait_for_selector(tid("booking-form"), state="detached", timeout=5000)


# ---- clicks (R237, R238, E6, R296) -------------------------------------------------------------------------

@pytest.mark.parametrize("signed_in", [False, True], ids=["signed_out", "signed_in"])
def test_an_unavailable_cell_does_nothing(world, page, tid, signed_in):
    """R237: clicking an unavailable cell changes nothing: no form, no auth-error, same page."""
    if signed_in:
        log_in(page, tid)
    search(page, tid, "r_anker", 2)
    before = (page.url, page.evaluate(CELLS), page.inner_text("main"))
    page.click(tid(first_cell(page, False)), force=True)
    page.wait_for_timeout(500)
    assert page.query_selector(tid("booking-form")) is None
    assert page.query_selector(tid("auth-error")) is None
    assert (page.url, page.evaluate(CELLS), page.inner_text("main")) == before


@pytest.mark.parametrize("pair", [False, True], ids=["table", "pair"])
def test_an_open_cell_opens_the_form_for_that_seating_and_time(world, page, tid, pair):
    """R237/R233/R270: signed in, an open cell opens `booking-form` for that table (or both
    tables of a pair) and that time, with the searched party size."""
    log_in(page, tid)
    search(page, tid, "r_linden", 5 if pair else 2)
    cell = first_cell(page, True, pair)
    page.click(tid(cell))
    page.wait_for_selector(tid("booking-form"))
    summary = page.inner_text(tid("booking-summary"))
    labels = {"t_w": "Window", "t_b": "Bar"}
    for table in cell.split("-")[1].split("+"):
        assert labels[table] in summary, (cell, summary)
    assert cell[-5:] in summary, (cell, summary)
    assert page.input_value(tid("booking-party-size")) == ("5" if pair else "2")


def test_a_signed_out_click_asks_to_log_in_in_place(world, page, tid):
    """R238/E6/R296: signed out, an open cell shows `auth-error` (no form, no navigation);
    the request to log in is a neutral surface with a brass "Log in"."""
    search(page, tid, "r_linden", 2)
    page.click(tid(first_cell(page, True)))
    page.wait_for_selector(tid("auth-error"))
    assert page.inner_text(tid("auth-error")).strip()
    assert page.query_selector(tid("booking-form")) is None
    assert urlsplit(page.url).path == "/", page.url
    assert page.query_selector(tid("availability-grid")) is not None
    assert page.evaluate(CLARET_USERS, [CLARET, "[data-testid='auth-error'], [data-testid='auth-error'] *"]) == []
    actions = page.evaluate("""() => [...document.querySelectorAll("[data-testid='auth-error'] a, [data-testid='auth-error'] button")]
      .filter((n) => n.innerText.trim() === 'Log in').map((n) => getComputedStyle(n).backgroundColor)""")
    assert TOKENS["brass"] in actions, actions


# ---- labels and looks (R223, R286, R287, R293, R284, S2N-4) ----------------------------------------------------

@pytest.mark.parametrize("restaurant,party", [("r_anker", 5), ("r_linden", 5)])
def test_rows_use_human_labels_and_say_how_many_they_seat(world, page, tid, restaurant, party):
    """R223/R287/R219: rows name every table by its label and say "seats N" (summed for a
    pair; any space between the word and the number, a no-break one included); no table or
    restaurant id is shown."""
    search(page, tid, restaurant, party)
    grid = page.inner_text(tid("availability-grid"))
    tables = RESTAURANTS[restaurant]["tables"]
    for table in tables:
        assert table["label"] in grid and re.search(rf"seats\s{table['capacity']}\b", grid), (table, grid)
    capacity = {t["id"]: t["capacity"] for t in tables}
    for pair in RESTAURANTS[restaurant]["combinable"]:
        if sum(capacity[t] for t in pair) >= party:
            assert re.search(rf"seats\s{sum(capacity[t] for t in pair)}\b", grid), (pair, grid)
    shown = page.evaluate(OUTSIDE_FORM_TEXT)
    for identifier in [t["id"] for t in tables] + [restaurant]:
        assert identifier not in shown, identifier


def test_slot_times_are_cormorant_with_lining_tabular_numerals(world, page, tid):
    """R285 (S2N-4): slot times are set in Cormorant with lining, tabular numerals."""
    search(page, tid, "r_anker", 2)
    style = page.evaluate("""() => { const s = getComputedStyle(document.querySelector("[data-testid^='slot-']"));
      return [s.fontFamily, s.fontVariantNumeric]; }""")
    assert style[0].strip('"').startswith("Cormorant"), style
    assert {"lining-nums", "tabular-nums"} <= set(style[1].split()), style


def test_open_taken_and_selected_cells_and_their_legend(world, page, tid):
    """R284/R287/R293: an open cell has the raised fill, a taken one the recessed fill with
    its time struck through in the taken colour, the selected one solid brass with dark
    text; each legend swatch has the fill of the cell it names, and the three differ."""
    log_in(page, tid)
    search(page, tid, "r_anker", 2)
    look = """(id) => { const s = getComputedStyle(document.querySelector(`[data-testid='${id}']`));
      return { fill: s.backgroundColor, color: s.color, line: s.textDecorationLine }; }"""
    open_cell, taken_cell = first_cell(page, True), first_cell(page, False)
    assert page.evaluate(look, open_cell)["fill"] == TOKENS["raised"]
    taken = page.evaluate(look, taken_cell)
    assert (taken["fill"], taken["color"]) == (TOKENS["recess"], TOKENS["taken"]) and "line-through" in taken["line"], taken
    page.click(tid(open_cell))
    page.wait_for_selector(tid("booking-form"))
    selected = page.evaluate(look, open_cell)
    assert (selected["fill"], selected["color"]) == (TOKENS["brass"], TOKENS["page"]), selected
    swatches = page.evaluate("""() => Object.fromEntries(['Open', 'Taken', 'Your choice'].map((word) => {
      const item = [...document.querySelectorAll("[data-testid='availability-grid'] *")]
        .find((n) => [...n.childNodes].some((c) => c.nodeType === 3 && c.textContent.trim() === word));
      const swatch = item && [...item.querySelectorAll('*')].find((n) => getComputedStyle(n).backgroundColor !== 'rgba(0, 0, 0, 0)');
      return [word, swatch ? getComputedStyle(swatch).backgroundColor : null]; }))""")
    assert swatches == {"Open": TOKENS["raised"], "Taken": TOKENS["recess"], "Your choice": TOKENS["brass"]}, swatches


# ---- layout (R224, R289) and every state together (R225, R280, R296) -------------------------------------------

def test_the_phone_grid_is_four_across_with_the_name_on_top(world, page, tid):
    """R289: at 375 px each table is a block, its name above its times, the eight times in a
    four-by-two grid."""
    page.set_viewport_size({"width": 375, "height": 900})
    search(page, tid, "r_anker", 2)
    blocks = page.evaluate("""() => { const groups = new Map();
      for (const n of document.querySelectorAll("[data-testid^='slot-']")) {
        const key = n.dataset.testid.replace(/-\\d\\d:\\d\\d$/, '');
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(n.getBoundingClientRect()); }
      return [...groups.entries()].map(([key, rects]) => {
        let row = document.querySelector(`[data-testid^='${key}-']`).parentElement;
        while (row && ![...row.querySelectorAll('*')].some((e) => !e.dataset.testid?.startsWith('slot-')
          && [...e.childNodes].some((c) => c.nodeType === 3 && c.textContent.trim()))) row = row.parentElement;
        const name = [...row.querySelectorAll('*')].find((e) => !e.dataset.testid?.startsWith('slot-')
          && [...e.childNodes].some((c) => c.nodeType === 3 && c.textContent.trim()));
        return { key, columns: new Set(rects.map((r) => Math.round(r.left))).size,
                 lines: new Set(rects.map((r) => Math.round(r.top))).size, count: rects.length,
                 nameAbove: name.getBoundingClientRect().bottom <= Math.min(...rects.map((r) => r.top)) }; }); }""")
    assert blocks and all(b["count"] == 8 for b in blocks), blocks
    wrong = [b for b in blocks if (b["columns"], b["lines"], b["nameAbove"]) != (4, 2, True)]
    assert not wrong, wrong


def states(page, tid, width):
    """Every S2-I4 screen state, with the claret it may show."""
    page.goto("/")
    page.wait_for_selector(tid("search-button"))
    yield "before search", False
    held = []
    page.route("**/availability?*", lambda r: held.append(r))
    submit(page, tid, "r_anker", 2)
    page.wait_for_timeout(400)
    yield "loading", False
    for route in held:
        route.continue_()
    page.unroute("**/availability?*")
    page.wait_for_selector(tid("availability-grid"))
    yield "results party 2", False
    search(page, tid, "r_anker", 5)
    yield "results party 5 with pairs", False
    search(page, tid, "r_linden", 5)
    page.click(tid(first_cell(page, True, pair=True)))
    page.wait_for_selector(tid("auth-error"))
    yield "signed-out click", False
    search(page, tid, "r_closed", 2)
    yield "closed day", False
    search(page, tid, "r_full", 2)
    yield "fully booked", False
    page.goto("/")
    page.wait_for_selector(tid("search-button"))
    page.route("**/availability?*", lambda r: r.abort("connectionreset"))
    submit(page, tid, "r_anker", 2)
    page.wait_for_timeout(1000)
    page.unroute("**/availability?*")
    yield "failed search", True
    log_in(page, tid)
    search(page, tid, "r_linden", 5)
    page.click(tid(first_cell(page, True, pair=True)))
    page.wait_for_selector(tid("booking-form"))
    yield "signed-in pair chosen", False


@pytest.mark.parametrize("width", [375, 1280])
def test_every_state_fits_reads_and_stays_on_the_service(world, page, tid, base_url, width):
    """R224/R289/R225/R280/R296: at 375 and 1280 px no state scrolls sideways or puts text
    outside the viewport, every text has 4.5:1 contrast, claret appears only on a failure,
    and no request leaves the service."""
    page.set_viewport_size({"width": width, "height": 900})
    requests, problems = [], []
    page.on("request", lambda r: requests.append(r.url))
    for state, claret_allowed in states(page, tid, width):
        size = page.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
        if size[0] > size[1]:
            problems.append((state, "scroll", size))
        problems += [(state, "outside", t) for t in page.evaluate(OUTSIDE)]
        problems += [(state, "contrast", r) for r in page.evaluate(CONTRAST)]
        if not claret_allowed:
            problems += [(state, "claret", c) for c in page.evaluate(CLARET_USERS, [CLARET, "body *"])]
    offsite = [url for url in requests if not url.startswith(base_url) and not url.startswith("data:")]
    assert not offsite, offsite
    assert not problems, problems[:8]


# ---- stage-1 shapes (G3, R245-R249 groundwork) -----------------------------------------------------------------

def test_the_grid_works_on_the_stage_1_service(reset, page, tid, previous_api, base_url):
    """G3: with the UI's API calls answered by the stage-1 service (no `available_options`,
    no `combinable`), single cells follow its `available_table_ids` and there are no pair
    cells."""
    single = {k: v for k, v in seed("OLD001", "r_anker", ["t_2"], "19:00").items() if k != "table_ids"}
    fixture = fx.fixture(restaurants=[ANKER], reservations=[{**single, "table_id": "t_2"}])
    assert_status(previous_api.post("/_test/reset", json=fixture), 204)
    reset(fixture)
    previous = previous_api.base_url.rstrip("/")

    def to_stage_1(route):
        answer = route.fetch(url=previous + route.request.url[len(base_url.rstrip("/")):])
        route.fulfill(response=answer)

    for pattern in ("**/availability?*", "**/restaurants", "**/restaurants/*"):
        page.route(pattern, to_stage_1)
    search(page, tid, "r_anker", 2)
    with Api(previous) as old:
        slots = assert_status(old.get("/availability", params={
            "restaurant_id": "r_anker", "date": DATE, "party_size": 2}), 200).json()["slots"]
    assert all("available_options" not in slot for slot in slots), "precondition: a stage-1 answer"
    expected = {f"slot-{t['id']}-{s['starts_at_local'][11:16]}": str(t["id"] in s["available_table_ids"]).lower()
                for s in slots for t in ANKER["tables"]}
    assert page.evaluate(CELLS) == expected
