"""S2-I3 acceptance checks (verifier seat): the screen routes, the header, signup and login,
assets, layout and colour, from the stage-2 specification (routes, "Signup and login",
"Product and visual direction") and the task's design direction (R280-R296).

Browser checks run in the harness's headless Chromium (`page`, `tid`). Colour values are the
R284 tokens; which element carries which token follows the design system (DESIGN.md 1.1:
labels are secondary text; cards are raised surfaces; the primary action is brass).
R.., E.. and G.. name the room plan's requirement lines and decisions.
"""
from __future__ import annotations

import pytest

import fixtures as fx
from harness.http import assert_status

pytestmark = pytest.mark.stage(2)

ROUTES = ["/", "/signup", "/login", "/lookup"]
WIDTHS = [375, 1280]
BRAND = "Tablekeeper"
TOKENS = {"page": "rgb(28, 20, 24)", "raised": "rgb(40, 29, 35)", "text": "rgb(242, 232, 216)",
          "text-2": "rgb(189, 175, 169)", "brass": "rgb(210, 166, 90)"}
CLARET = "rgb(236, 148, 132)"
LONG_NAME = "Maximiliane-Alexandrina-Konstantinopolitanische"

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
  const texts = [...document.body.querySelectorAll('*')].filter((n) => shown(n) && (
    ['INPUT', 'SELECT', 'TEXTAREA'].includes(n.tagName) ||
    [...n.childNodes].some((c) => c.nodeType === 3 && c.textContent.trim())));
  return texts.map((n) => { const bg = backdrop(n); const fg = over(parse(getComputedStyle(n).color), bg);
    const [hi, lo] = [lum(fg), lum(bg)].sort((a, b) => b - a);
    return { text: (n.innerText || n.value || '').trim().slice(0, 40), tag: n.tagName,
             color: getComputedStyle(n).color, ratio: Math.round(((hi + 0.05) / (lo + 0.05)) * 100) / 100 }; })
    .filter((r) => r.ratio < 4.5);
}"""

LABELS = """() => [...document.querySelectorAll('input, select, textarea')]
  .filter((c) => c.type !== 'hidden' && c.checkVisibility())
  .map((c) => ({ control: c.dataset.testid || c.id || c.name,
                 labels: [...(c.labels || [])].filter((l) => l.checkVisibility()
                   && l.getBoundingClientRect().width > 0 && l.innerText.trim()).map((l) => l.innerText.trim()) }))
  .filter((c) => c.labels.length === 0)"""

CLARET_USERS = """(claret) => [...document.body.querySelectorAll('*')].filter((n) => n.checkVisibility()).filter((n) => {
  const s = getComputedStyle(n);
  const side = (k) => s[`border${k}Color`] === claret && parseFloat(s[`border${k}Width`]) > 0;
  return s.color === claret || s.backgroundColor === claret || ['Top', 'Right', 'Bottom', 'Left'].some(side)
    || (s.outlineStyle !== 'none' && s.outlineColor === claret);
}).map((n) => (n.dataset.testid || n.getAttribute('class') || n.tagName) + ': ' + (n.innerText || '').slice(0, 30))"""


def settle(page) -> None:
    page.wait_for_load_state("networkidle")


def log_in(page, tid, email=fx.ADA["email"], password=fx.ADA["password"]) -> None:
    page.goto("/login")
    page.fill(tid("login-email"), email)
    page.fill(tid("login-password"), password)
    page.click(tid("login-submit"))
    page.wait_for_selector(tid("current-user"))
    settle(page)


def sign_up(page, tid, name: str, email: str, password: str) -> None:
    page.goto("/signup")
    page.fill(tid("signup-display-name"), name)
    page.fill(tid("signup-email"), email)
    page.fill(tid("signup-password"), password)
    page.click(tid("signup-submit"))


@pytest.fixture
def seeded(reset):
    reset(fx.fixture())


# ---- routes and header (R203, R206, R204, R290, R229, R230, G1, G3) ---------------------------------

@pytest.mark.parametrize("route", ROUTES)
def test_a_screen_route_returns_html(seeded, anon, route):
    """R203/R206/G1: each screen route answers 200 with an HTML page; the API and its JSON
    404 for unknown paths are unchanged."""
    resp = assert_status(anon.get(route), 200)
    assert resp.headers["content-type"].startswith("text/html"), resp.headers["content-type"]
    assert "<html" in resp.text.lower()
    assert assert_status(anon.get("/restaurants"), 200).headers["content-type"].startswith("application/json")
    missing = anon.get(f"{route.rstrip('/')}/nope")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"


def header_state(page) -> dict:
    return page.evaluate("""(brand) => {
      const header = document.querySelector('header');
      const links = header ? [...header.querySelectorAll('a')].filter((a) => a.checkVisibility())
        .map((a) => [a.innerText.trim(), new URL(a.href).pathname]) : [];
      const user = document.querySelector("[data-testid='current-user']");
      return { brand: links.some(([text, path]) => text === brand && path === '/'), links,
               user: user && user.checkVisibility() ? user.innerText : null,
               logout: !!document.querySelector("[data-testid='logout-button']") };
    }""", BRAND)


@pytest.mark.parametrize("width", WIDTHS)
def test_every_route_has_the_header_signed_out(seeded, page, width):
    """R290/R204: every screen shows the brand (to /) and "Book a table" (/) and "Find a
    booking" (/lookup); signed out, no `current-user` and no `logout-button`."""
    page.set_viewport_size({"width": width, "height": 900})
    for route in ROUTES:
        page.goto(route)
        settle(page)
        state = header_state(page)
        assert state["brand"], (route, state)
        assert ["Book a table", "/"] in state["links"] and ["Find a booking", "/lookup"] in state["links"], (route, state)
        assert state["user"] is None and not state["logout"], (route, state)


def test_the_header_reaches_the_other_screens(seeded, page):
    """R204/R290: the header's links lead to the search and the lookup screens."""
    page.goto("/login")
    page.get_by_role("link", name="Find a booking").click()
    page.wait_for_url("**/lookup")
    page.get_by_role("link", name="Book a table").click()
    page.wait_for_url(lambda url: url.endswith("/"))


@pytest.mark.parametrize("width", WIDTHS)
def test_every_route_shows_the_signed_in_diner(seeded, page, tid, width):
    """R229/R230/G3: signed in, every screen (reached by URL, so from the stored session)
    shows `current-user` containing the display name and a `logout-button`."""
    page.set_viewport_size({"width": width, "height": 900})
    log_in(page, tid)
    for route in ROUTES:
        page.goto(route)
        page.wait_for_selector(tid("current-user"))
        state = header_state(page)
        assert state["user"] and fx.ADA["display_name"] in state["user"], (route, state)
        assert state["logout"], (route, state)


def test_logging_out_removes_the_diner_from_every_route(seeded, page, tid):
    """R230/R229/G3: logging out removes `current-user` at once, and on every screen after."""
    log_in(page, tid)
    page.goto("/lookup")
    page.click(tid("logout-button"))
    page.wait_for_selector(tid("current-user"), state="detached", timeout=3000)
    for route in ROUTES:
        page.goto(route)
        settle(page)
        state = header_state(page)
        assert state["user"] is None and not state["logout"], (route, state)


# ---- auth-error (R227, R228) ---------------------------------------------------------------------------

def refusal(page, tid) -> str:
    page.wait_for_selector(tid("auth-error"))
    text = page.inner_text(tid("auth-error")).strip()
    assert text, "auth-error must say what went wrong"
    assert page.query_selector(tid("current-user")) is None
    return text


@pytest.mark.parametrize("email,password", [(fx.ADA["email"], "wrong password"),
                                            ("nobody@example.com", fx.ADA["password"])],
                         ids=["wrong_password", "unknown_email"])
def test_a_refused_login_shows_auth_error_only_then(seeded, page, tid, email, password):
    """R228/R227: `auth-error` is absent until a login is refused, then present with text;
    after a successful login it is gone."""
    page.goto("/login")
    settle(page)
    assert page.query_selector(tid("auth-error")) is None
    page.fill(tid("login-email"), email)
    page.fill(tid("login-password"), password)
    page.click(tid("login-submit"))
    refusal(page, tid)
    page.fill(tid("login-email"), fx.ADA["email"])
    page.fill(tid("login-password"), fx.ADA["password"])
    page.click(tid("login-submit"))
    page.wait_for_selector(tid("current-user"))
    settle(page)
    assert page.query_selector(tid("auth-error")) is None


@pytest.mark.parametrize("email,password", [(fx.ADA["email"], "a long enough secret"),
                                            ("cy@example.com", "short"),
                                            ("not-an-email", "a long enough secret")],
                         ids=["email_taken", "short_password", "bad_email"])
def test_a_refused_signup_shows_auth_error_only_then(seeded, page, tid, email, password):
    """R228/R227: signup refusals (email taken, short password, bad email) show
    `auth-error` and sign nobody in; it is absent before, and a valid signup signs in
    without it."""
    page.goto("/signup")
    settle(page)
    assert page.query_selector(tid("auth-error")) is None
    sign_up(page, tid, "Cy", email, password)
    refusal(page, tid)
    sign_up(page, tid, "Cy", "cy@example.com", "a long enough secret")
    page.wait_for_selector(tid("current-user"))
    settle(page)
    assert "Cy" in page.inner_text(tid("current-user"))
    assert page.query_selector(tid("auth-error")) is None


# ---- assets (R280, R285) ---------------------------------------------------------------------------------

def test_every_request_stays_on_the_service_and_every_asset_loads(seeded, page, tid, base_url):
    """R280: on every screen, signed out, signed in and refused, every request the browser
    makes goes to the service, none fails, and the page raises no error."""
    requests, failed, errors = [], [], []
    page.on("request", lambda r: requests.append(r.url))
    page.on("requestfailed", lambda r: failed.append(r.url))
    page.on("response", lambda r: r.status >= 400 and r.request.method == "GET" and failed.append(f"{r.status} {r.url}"))
    page.on("pageerror", lambda e: errors.append(str(e)))
    for route in ROUTES:
        page.goto(route)
        settle(page)
    page.goto("/login")
    page.fill(tid("login-email"), fx.ADA["email"])
    page.fill(tid("login-password"), "wrong password")
    page.click(tid("login-submit"))
    page.wait_for_selector(tid("auth-error"))
    log_in(page, tid)
    for route in ROUTES:
        page.goto(route)
        settle(page)
    offsite = [url for url in requests if not url.startswith(base_url) and not url.startswith("data:")]
    assert not offsite, offsite
    assert not failed, failed
    assert not errors, errors
    assert any("/assets/" in url and url.endswith(".css") for url in requests)
    assert any("/assets/" in url and url.endswith(".woff2") for url in requests)


def test_the_fonts_in_use_are_served_with_their_licence(seeded, page, anon, base_url):
    """R285/R280: both families are loaded from the service; every font file the styles
    name is served as a woff2 font, with the family's OFL LICENSE beside it."""
    page.goto("/login")
    settle(page)
    page.evaluate("() => document.fonts.ready")
    info = page.evaluate("""() => ({
      loaded: [...document.fonts].filter((f) => f.status === 'loaded').map((f) => f.family.replace(/"/g, '')),
      urls: [...document.styleSheets].flatMap((sheet) => [...sheet.cssRules])
        .filter((rule) => rule instanceof CSSFontFaceRule)
        .flatMap((rule) => [...rule.style.getPropertyValue('src').matchAll(/url\\("?([^")]+)"?\\)/g)].map((m) => m[1])),
    })""")
    assert {"Cormorant", "Hanken Grotesk"} <= set(info["loaded"]), info["loaded"]
    assert info["urls"], "no @font-face sources"
    for url in info["urls"]:
        path = url.replace(base_url, "")
        font = assert_status(anon.get(path), 200)
        assert font.headers["content-type"].startswith("font/woff2") and font.content[:4] == b"wOF2", path
        licence = assert_status(anon.get(path.rsplit("/", 1)[0] + "/LICENSE"), 200)
        assert "SIL OPEN FONT LICENSE" in licence.text.upper(), path


def test_display_type_is_cormorant_with_lining_tabular_numerals(seeded, page):
    """R285: the brand and page titles are Cormorant with lining, tabular numerals; the
    rest is Hanken Grotesk."""
    for route in ("/login", "/signup", "/lookup"):
        page.goto(route)
        settle(page)
        styles = page.evaluate("""(brand) => {
          const style = (n) => n && { family: getComputedStyle(n).fontFamily, numerals: getComputedStyle(n).fontVariantNumeric };
          const brandNode = [...document.querySelectorAll('header a')].find((a) => a.innerText.trim() === brand);
          const titleNode = [...document.querySelectorAll('main h1')].find((h) => h.checkVisibility());
          return { brand: style(brandNode), title: style(titleNode), body: style(document.body) };
        }""", BRAND)
        for name in ("brand", "title"):
            assert styles[name]["family"].strip('"').startswith("Cormorant"), (route, styles)
            assert {"lining-nums", "tabular-nums"} <= set(styles[name]["numerals"].split()), (route, styles)
        assert styles["body"]["family"].strip('"').startswith("Hanken Grotesk"), (route, styles)


# ---- layout, labels, focus, colour (R224, R225, R284, R294, R296) -------------------------------------------

def states(page, tid):
    """Every S2-I3 screen state: each route signed out, the refused login and signup, and
    each route signed in with a long display name."""
    for route in ROUTES:
        page.goto(route)
        settle(page)
        yield f"{route} signed out"
    page.goto("/login")
    page.fill(tid("login-email"), fx.ADA["email"])
    page.fill(tid("login-password"), "wrong password")
    page.click(tid("login-submit"))
    page.wait_for_selector(tid("auth-error"))
    yield "/login refused"
    sign_up(page, tid, LONG_NAME, fx.ADA["email"], "a long enough secret")
    page.wait_for_selector(tid("auth-error"))
    yield "/signup refused"
    sign_up(page, tid, LONG_NAME, "long@example.com", "a long enough secret")
    page.wait_for_selector(tid("current-user"))
    for route in ROUTES:
        page.goto(route)
        page.wait_for_selector(tid("current-user"))
        settle(page)
        yield f"{route} signed in"
    page.evaluate("() => localStorage.clear()")


OUTSIDE = """() => [...document.body.querySelectorAll('*')].filter((n) => n.checkVisibility()
    && [...n.childNodes].some((c) => c.nodeType === 3 && c.textContent.trim()))
  .map((n) => [n.innerText.trim().slice(0, 30), Math.round(n.getBoundingClientRect().left), Math.round(n.getBoundingClientRect().right)])
  .filter(([, left, right]) => left < 0 || right > window.innerWidth)"""


@pytest.mark.parametrize("width", WIDTHS)
def test_no_state_scrolls_sideways_or_cuts_text_off(seeded, page, tid, width):
    """R224: at 375 and 1280 px, no screen state is wider than the viewport and no text
    lies outside it, including a long display name in the header."""
    page.set_viewport_size({"width": width, "height": 900})
    wide = []
    for state in states(page, tid):
        size = page.evaluate("() => [document.documentElement.scrollWidth, document.body.scrollWidth, window.innerWidth]")
        if max(size[:2]) > size[2]:
            wide.append((state, size))
        wide += [(state, text) for text in page.evaluate(OUTSIDE)]
    assert not wide, wide[:8]


def test_every_input_has_a_visible_label(seeded, page, tid):
    """R225: every visible input and select has a visible label with text."""
    unlabelled = []
    for state in states(page, tid):
        unlabelled += [(state, c) for c in page.evaluate(LABELS)]
    assert not unlabelled, unlabelled


@pytest.mark.parametrize("width", WIDTHS)
def test_every_text_has_at_least_4_5_to_1_contrast(seeded, page, tid, width):
    """R225/R284: every visible text, measured against the background it sits on, has a
    contrast ratio of at least 4.5:1, in every state and at both widths."""
    page.set_viewport_size({"width": width, "height": 900})
    low = []
    for state in states(page, tid):
        low += [(state, r) for r in page.evaluate(CONTRAST)]
    assert not low, low[:8]


def test_keyboard_focus_is_apparent(seeded, page, tid):
    """R225: on each screen, every control reached with Tab shows a focus indicator (an
    outline or a shadow) it does not have unfocused."""
    missing = []
    for route in ROUTES:
        page.goto(route)
        settle(page)
        page.evaluate("""() => document.querySelectorAll('a[href], button, input, select, textarea')
          .forEach((n, i) => { n.dataset.kbIndex = i; })""")
        rest = page.evaluate("""() => Object.fromEntries([...document.querySelectorAll('[data-kb-index]')]
          .map((n) => { const s = getComputedStyle(n); return [n.dataset.kbIndex, [s.outlineStyle, s.outlineWidth, s.outlineColor, s.boxShadow]]; }))""")
        seen = set()
        for _ in range(12):
            page.keyboard.press("Tab")
            focus = page.evaluate("""() => { const n = document.activeElement; const s = getComputedStyle(n);
              return { index: n.dataset.kbIndex, name: n.dataset.testid || n.innerText || n.id,
                       style: [s.outlineStyle, s.outlineWidth, s.outlineColor, s.boxShadow] }; }""")
            if focus["index"] is None or focus["index"] in seen:
                continue
            seen.add(focus["index"])
            style = focus["style"]
            ring = style[0] != "none" and float(style[1].rstrip("px") or 0) >= 1 and not style[2].endswith(", 0)")
            if style == rest[focus["index"]] or not (ring or style[3] != "none"):
                missing.append((route, focus["name"], style))
        assert seen, f"nothing on {route} takes keyboard focus"
    assert not missing, missing


def test_the_colours_are_the_design_tokens(seeded, page, tid):
    """R284 (S2N-4): the page background, a raised surface (the card), main text, secondary
    text (a label) and the brass primary action are the tokens; text on brass is the page
    colour; a refusal is claret."""
    page.goto("/login")
    settle(page)
    colours = page.evaluate("""() => {
      const email = document.querySelector("[data-testid='login-email']");
      const submit = document.querySelector("[data-testid='login-submit']");
      let card = email.parentElement;
      while (card && ['rgba(0, 0, 0, 0)', getComputedStyle(document.body).backgroundColor]
             .includes(getComputedStyle(card).backgroundColor)) card = card.parentElement;
      return { page: getComputedStyle(document.body).backgroundColor, text: getComputedStyle(document.body).color,
               raised: card && getComputedStyle(card).backgroundColor, 'text-2': getComputedStyle(email.labels[0]).color,
               brass: getComputedStyle(submit).backgroundColor, onBrass: getComputedStyle(submit).color };
    }""")
    assert {k: colours[k] for k in TOKENS} == TOKENS, colours
    assert colours["onBrass"] == TOKENS["page"], colours
    page.fill(tid("login-email"), fx.ADA["email"])
    page.fill(tid("login-password"), "wrong password")
    page.click(tid("login-submit"))
    page.wait_for_selector(tid("auth-error"))
    assert page.evaluate(CLARET_USERS.replace("document.body.querySelectorAll('*')",
                                              "document.querySelectorAll(\"[data-testid='auth-error'], [data-testid='auth-error'] *\")"),
                         CLARET), "a refusal is shown in claret"


def test_claret_appears_only_for_refusals(seeded, page, tid):
    """R296/R284: without a refusal no screen shows claret; asking a signed-out diner to
    log in (on /lookup) is a neutral surface whose action is a brass "Log in"."""
    for route in ROUTES:
        page.goto(route)
        settle(page)
        assert page.evaluate(CLARET_USERS, CLARET) == [], route
    page.goto("/lookup")
    settle(page)
    actions = page.evaluate("""() => [...document.querySelectorAll('main a[href="/login"], main button')]
      .filter((n) => n.checkVisibility() && n.innerText.trim() === 'Log in')
      .map((n) => getComputedStyle(n).backgroundColor)""")
    assert TOKENS["brass"] in actions, actions
    log_in(page, tid)
    for route in ROUTES:
        page.goto(route)
        settle(page)
        assert page.evaluate(CLARET_USERS, CLARET) == [], route


@pytest.mark.parametrize("screen,submit,fill", [
    ("/login", "login-submit", {"login-email": fx.ADA["email"], "login-password": "wrong password"}),
    ("/signup", "signup-submit", {"signup-display-name": "Cy", "signup-email": fx.ADA["email"],
                                  "signup-password": "a long enough secret"}),
], ids=["login", "signup"])
@pytest.mark.parametrize("width", WIDTHS)
def test_a_submit_button_keeps_its_width_in_every_state(seeded, page, tid, screen, submit, fill, width):
    """R294: the submit keeps its width while busy (its request held) and after a refusal."""
    page.set_viewport_size({"width": width, "height": 900})
    held = []
    page.route("**/auth/*", lambda route: held.append(route))
    page.goto(screen)
    settle(page)
    width_of = lambda: page.evaluate(f"() => document.querySelector(\"[data-testid='{submit}']\").getBoundingClientRect().width")
    idle = width_of()
    for name, value in fill.items():
        page.fill(tid(name), value)
    page.click(tid(submit))
    for _ in range(50):
        if held:
            break
        page.wait_for_timeout(100)
    assert held, "the submit sent no request"
    busy = width_of()
    held[0].continue_()
    page.wait_for_selector(tid("auth-error"))
    refused = width_of()
    assert idle == busy == refused, {"idle": idle, "busy": busy, "refused": refused}
