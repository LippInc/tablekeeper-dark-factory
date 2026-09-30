# Tablekeeper design system

Owner: designer seat (the only writer of this file). Applies from stage 2 on, to every screen the service serves.
Sources: the stage-2 specification ("Product and visual direction", which wins on any difference) and the task's fixed design direction "Dinner service". Reference pictures `tk-look-desktop.png` and `tk-look-phone.png` set the direction, not a pixel spec.

**Character, in one sentence:** the booking screen feels like the dining room at 8 pm: dark, warm, calm and a little luxurious, with warmth that comes from colour and type, never from glow.

Unbreakable: every `data-testid` stays exactly as the specification names it, on the element the specification describes. No look rule here may rename, hide, delay, disable or restyle away a required element, attribute or behaviour. Where a rule below seems to conflict with a check or the specification, the specification wins and the designer is told.

---

## 1. Tokens

Write them once as CSS custom properties on `:root` and use nothing else. The page sets `color-scheme: dark` so native date pickers, selects and scrollbars render light-on-dark.

### 1.1 Colour

| Token | Value | Meaning and where it is used |
|---|---|---|
| `--tk-page` | `#1C1418` | Page background (warm near-black). Also the text colour on brass. |
| `--tk-raised` | `#281D23` | Raised surfaces: the search band, booking panel, auth and detail cards, **open** slot fill. |
| `--tk-raised-hover` | `#33262D` | Hover fill of an open slot and of a secondary button on a raised surface. |
| `--tk-recess` | `#120C0F` | **Taken** slot fill (recessed, recedes into the page). |
| `--tk-text` | `#F2E8D8` | Linen. Main text, open slot times, drawing strokes and seat dots, secondary-button outline, neutral notice rule. |
| `--tk-text-2` | `#BDAFA9` | Secondary text: labels, descriptions, ledes, notice bodies, inactive navigation, the loading notice rule. |
| `--tk-text-taken` | `#8F8084` | The struck-through time of a taken slot. Only on `--tk-recess` or `--tk-page`, never on `--tk-raised`. |
| `--tk-control` | `#8F8084` | Control boundaries: input underline, the 2 px base rule of an open slot, the lookup card rule when cancelled. |
| `--tk-rule` | `#3A2D33` | Hairline dividers between rows and bands, the loading track. Decorative only, never a control boundary. |
| `--tk-quiet` | `#6E5F64` | Strokes of the quiet room drawing and of a cancelled booking's drawing. Decorative only, never text. |
| `--tk-brass` | `#D2A65A` | **The one accent, four uses only:** primary action buttons, the selected slot, joined-table seams, keyboard focus. |
| `--tk-brass-hover` | `#DDB672` | Primary button hover. |
| `--tk-brass-press` | `#C4974D` | Primary button pressed. |
| `--tk-booked` | `#A9C79C` | Sage. Booked / confirmed: the booked notice's rule and title, the `confirmed` status. |
| `--tk-refused` | `#EC9484` | Claret. **Only** refusals and errors: refused notice, failed search, auth errors, lookup errors, invalid field underline. |
| `--tk-uncertain` | `#AFB8C8` | Pewter. Uncertain outcome only, always with a **dashed** rule. |

Brass never marks anything else: not the active navigation item, not panel edges, not the words "Joined pair". Claret never asks a signed-out diner to log in (that uses the neutral treatment in 3.10).

Contrast (VERIFIED by computation, WCAG relative luminance; minimum 4.5 for text, 3 for control boundaries):

| Foreground | on page | on raised | on recess | other |
|---|---|---|---|---|
| text `#F2E8D8` | 14.89 | 13.42 | 15.95 | 11.89 on raised-hover |
| text-2 `#BDAFA9` | 8.49 | 7.65 | 9.09 | 6.78 on raised-hover |
| text-taken `#8F8084` | 4.81 | *4.33, not allowed* | 5.15 | |
| brass `#D2A65A` (focus ring) | 8.04 | 7.24 | 8.61 | |
| page `#1C1418` as text on brass | | | | 8.04 on brass, 9.47 on brass-hover, 6.78 on brass-press |
| booked / refused / uncertain | 9.75 / 7.86 / 9.04 | 8.79 / 7.08 / 8.15 | | |
| control `#8F8084` (boundary) | 4.81 | 4.33 | | 3.84 on raised-hover |

### 1.2 Type

Two families, both shipped inside the image (section 1.8). Nothing is fetched from outside.

- **Display: Cormorant.** Used for the brand name, page titles, the headings of results notices, table names in the booking panel and lookup detail, slot times, and the booking reference. Every Cormorant element sets `font-variant-numeric: lining-nums tabular-nums` (OpenType `lnum`, `tnum`) with no exceptions: Cormorant's default old-style figures make "Table 1" and "7 October" look broken. Stack: `Cormorant, Georgia, "Times New Roman", serif`.
- **Text: Hanken Grotesk.** Everything else. Stack: `"Hanken Grotesk", "Segoe UI", Arial, sans-serif`.

| Role | Family | Size / line height | Weight | Notes |
|---|---|---|---|---|
| Page title (results heading, lookup title) | Cormorant | 52 / 1.05 at ≥ 720 px; 40 / 1.1 below | 500 | |
| Card title (log in, sign up) | Cormorant | 40 / 1.1 | 500 | |
| Panel title, notice heading, booking reference | Cormorant | 36 / 1.1 | 500 (reference 600, letter-spacing 0.04em) | |
| Brand | Cormorant | 28 / 1 | 600 | |
| Slot time | Cormorant **italic** | 22 / 1 | 600 | The one italic use; reads like a hand-written reservation book, tabular lining figures keep columns aligned. |
| Lede, row name, input value | Hanken | 17 / 1.5 (row name 17 / 1.3, 600) | 400 | |
| Body, button, notice title | Hanken | 16 / 1.5 (button 16 / 1, 600; notice title 600) | 400 | |
| Label, description, legend, notice body | Hanken | 14 / 1.5 (label 14 / 1.3, 500) | 400 | |
| Caption, footnote, group caption | Hanken | 13 / 1.4 | 400 (group caption letter-spacing 0.02em) | Smallest size anywhere. |

Sentence case everywhere; no all-caps text.

### 1.3 Spacing

One scale, in px: **4, 8, 12, 16, 24, 32, 48, 64.** Every margin, padding and gap uses one of these (exceptions stated inline: the 6 px label-to-input gap and the 6 px phone slot gap).

### 1.4 Radius, rules, elevation

- Radius: **2 px** for slots, buttons, legend swatches; **4 px** for surfaces (booking panel, cards). Inputs have no radius (underline style).
- Rules: hairline 1 px `--tk-rule` (dividers); control 1 px `--tk-control` (input underline) and 2 px (open slot base rule); **state rule 3 px** (left edge of notices, top edge of the booking panel and the lookup detail card); uncertain = 3 px **dashed**.
- Elevation: **none.** No shadows, glows or gradients. Depth comes only from the three fills: recess < page < raised.

### 1.5 Focus

Every interactive element, on `:focus-visible`: `outline: 2px solid var(--tk-brass); outline-offset: 2px`. Never remove an outline without this replacement. On the brass selected slot the 2 px offset shows page colour between fill and ring, so focus stays visible. Inputs also turn their underline linen while focused.

### 1.6 Motion

- Hover changes of fill and rule colour: `transition: background-color 120ms, border-color 120ms`. No other transitions.
- One animation: the **loading track** (a 3 px `--tk-rule` bar with a linen segment 35% wide sliding left to right, 1.2 s linear, repeating), used only in the search-loading and booking-loading states. Under `prefers-reduced-motion: reduce` the segment stands still.
- Nothing fades, slides in or waits to appear. An element a check waits for is in the DOM and visible the moment its state is reached.

### 1.7 Layout grid and breakpoints

- Content column: `max-width: 1120px`, centred. Side margins: **16 px** below 720 px, **32 px** from 720 to 1023 px, **40 px** from 1024 px.
- **Phone, < 720 px** (designed at 375): one column. The booking panel sits below the results.
- **Middle, 720–1023 px** (reviewed at 900): one column. The booking panel sits below the results and uses two inner columns (3.8).
- **Desktop, ≥ 1024 px** (reviewed at 1280): results `minmax(0, 1fr)`, gap 48, booking panel **320 px** on the right, top-aligned.
- Table rows are **inline** (name block on the left, times across on the right) only at **≥ 1200 px**, where the results column is at least 744 px. Below 1200 px rows are **stacked** (name block on top, times underneath) so no time cell drops below 60 px.
- No width may scroll sideways: nothing has a fixed width wider than its column; every grid and flex child that holds an input or a long name sets `min-width: 0`; long names wrap or truncate with an ellipsis (display name only); `overflow-x` is never used to hide overflow.

### 1.8 Fonts shipped

Copy these files from `tasks\look\fonts\` into the stage folder together with each family's `LICENSE` (SIL OFL 1.1), and serve them from the service's own origin (for example under `/static/fonts/`):

- `cormorant-latin-wght-normal.woff2`, `cormorant-latin-ext-wght-normal.woff2` (weights 300–700)
- `cormorant-latin-wght-italic.woff2` (slot times are digits and a colon, so the Latin italic subset is enough; no Latin Extended italic)
- `hanken-grotesk-latin-wght-normal.woff2`, `hanken-grotesk-latin-ext-wght-normal.woff2` (weights 100–900)

Each `@font-face` sets `font-display: swap`, the variable weight range, and the subset's `unicode-range` so the browser loads Latin Extended only when a name needs it:

- Latin: `U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD`
- Latin Extended: `U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF`

Icons are not used. The only pictures are the floor-plan drawings (section 4) and the select chevron, all inline SVG in the product.

---

## 2. Words: how data becomes human text

The fixture holds only ids, a restaurant name and time zone, table labels and capacities, combinable pairs, slot times and reservation fields. Every visible phrase below is derived from those; no other data is invented.

- **Table name:** a label that is a code gets the prefix "Table"; any other label is a name and is shown as given. A code is at most 4 characters with no space that either contains a digit or is a single letter: `"1"` → **Table 1**, `"12"` → **Table 12**, `"A3"` → **Table A3**, `"B"` → **Table B**; `"Bar"` → **Bar**, `"Window"` → **Window**, `"Terrace 2"` → **Terrace 2**.
- **Pair name:** each member reads exactly as on its own row, joined by " + ", in `combinable` order; the one contraction is that when both members are codes the prefix is said once: **Tables 1 + 2**. Otherwise: **Bar + Window**, **Table 3 + Window**. The name always contains every member's label (so `booking-summary`, `confirmation-tables` and `reservation-tables` name every table).
- **Row description:** `{size word}, seats {N}`. Size word from capacity: 1–2 **Small table**, 3–4 **Medium table**, 5–8 **Large table**, 9 or more **Banquet table**. A pair: **Joined pair, seats {sum}**.
- **Panel description:** a single table: `{Size word}, for up to {N in words}` ("Medium table, for up to four"). A pair: the pair name with " + " read as " and ", then `pushed together, for up to {N in words}` ("Tables 1 and 2 pushed together, for up to six", "Bar and Window pushed together, for up to eight").
- **Dates:** in words, `Weekday D Month`, for example **Wednesday 7 October**; add the year only when it is not the current year (**Friday 8 January 2027**). The date input keeps its `YYYY-MM-DD` value; only text we write is in words.
- **Times:** 24-hour `HH:MM` with a leading zero (**09:00**, **18:30**), exactly as in the slot grid, always the restaurant's local time.
- **Party size:** in words from one to twelve ("for four"), digits above ("for 14").
- **Line breaks:** "seats N" never splits: write it with a no-break space (U+00A0) between "seats" and the number, so a narrow name column breaks after the comma ("Medium table, / seats 4"). Every text block that can wrap (row and panel descriptions, ledes, notice titles and bodies, results-notice sentences) sets `text-wrap: pretty` so no line ends with a single orphaned word ("…for up / to six", not "…for up to / six").
- **Dated policies (from stage 3):** a search reads every capacity from the policy the service selects for the searched date: "seats N", the size word, the seat dots, the "Too small for …" grouping, which pairs get a row, and the panel's "for up to …" and "seats … at most". A booking already made reads its own `accepted_terms`, even when a newer policy says otherwise. That covers the booked notice, the lookup detail and its drawing, and the cutoff sentence. Nothing announces a policy: the diner never sees the word "policy", a version number or an effective date, and the rows simply read as that date's room.
- **Cutoff sentence:** stated per booking from its accepted cutoff, never as a rule for all bookings: "This booking can be cancelled until two hours before it starts." The duration is given in its largest whole unit, in words ("45 minutes", "two hours", "one day", "14 days"). A cutoff of 0 reads "until it starts".
- **Never shown:** table ids (`t_1`), restaurant ids (`r_anker`), user or reservation ids, raw API codes, ISO timestamps. The booking **reference** is shown, because the diner needs it; it is written exactly as the service returns it, with no separators or spaces added (the hyphen in the reference picture is a placeholder).

---

## 3. Components

### 3.1 Header (every screen)

- Full-width, `--tk-page`, 1 px `--tk-rule` bottom hairline. Desktop and middle: one row, 72 px tall: brand, then the navigation 40 px to its right, then the account block pushed right.
- **Brand** "Tablekeeper": Cormorant 28/600 linen, links to `/`.
- **Navigation:** "Book a table" (`/`) and "Find a booking" (`/lookup`), Hanken 16/500 `--tk-text-2`, 28 px apart, each at least 44 px tall. Current page: linen text with a 2 px **linen** underline sitting on the header's bottom edge. Hover: linen text. On `/login` and `/signup` no item is current.
- **Signed in:** "Signed in as" (`--tk-text-2`, hidden below 720 px) then the display name in linen 16/600 (`current-user`; the element's text contains the display name; long names end in an ellipsis at 20ch, 12ch on phone) and "Log out" (`logout-button`), a real button styled as a text link: `--tk-text-2`, underline offset 4 px, linen on hover, 44 px tall.
- **Signed out:** "Log in" and "Sign up" text links in the same style.
- **Phone:** row 1 = brand left, account block right; row 2 = the two navigation items, 48 px tall, underline on the current one. Padding-top 12 px.

### 3.2 Inputs (select, date, number, text, email, password)

- Label always visible, above the control: Hanken 14/500 `--tk-text-2`, 6 px gap. Every control has a real `<label>`.
- Control: transparent background, no side or top border, **1 px `--tk-control` underline**, Hanken 17 linen, `min-height: 44px`, padding 8 px 0, `width: 100%`, `min-width: 0`.
- Hover: underline linen. Focus: the brass ring (1.5) and a linen underline.
- Invalid (only after a submit was answered with a field problem): underline 2 px `--tk-refused`; the message sits directly under the field, Hanken 14 `--tk-refused`.
- Select: `appearance: none`, a chevron drawn as inline SVG in `--tk-text-2` at the right, options on `--tk-raised`.
- Date: native `type="date"`; the native picker icon is light thanks to `color-scheme: dark`.
- Number (party size): `min="1"`, 120 px wide in the booking panel.
- Hints (for example "At least 8 characters" under the sign-up password): Hanken 13 `--tk-text-2`, 4 px under the control.

### 3.3 Buttons

| Kind | Look | Used for |
|---|---|---|
| Primary | Fill `--tk-brass`, text `--tk-page` 16/600, radius 2, `min-height: 48px`, padding 0 24. Hover `--tk-brass-hover`, pressed `--tk-brass-press`. | "Find tables", the booking submit, "Log in" and "Create account", "Find booking", the brass "Log in" of the neutral sign-in notice. At most one primary per region (search band, booking panel, card). |
| Secondary | Transparent, 1 px linen outline, linen 16/600, same metrics. Hover fill `--tk-raised` (on page) or `--tk-raised-hover` (on raised). | "Cancel booking", "Choose another date", "Search again", and "Find booking" while signed out. |
| Text | `--tk-text-2`, underlined, offset 4 px, linen on hover, at least 44 px tall. | "Log out", "Create an account", "Log in instead". |

- **A button never changes width.** Its width comes from its container or a fixed width that fits its longest label: search button **160 px** at ≥ 720 px and full width on phone; the booking submit, card submits and the cancel button are **100 %** of their column. Label changes (for example "Booking…") never move anything around them.
- Busy: the label changes and `aria-busy="true"` is set; no spinner, no dimming. The search button is never disabled (a diner may start a second search while the first is loading).

### 3.4 Slot cell (`slot-{table_id}-{HH:MM}`, `slot-{t_a}+{t_b}-{HH:MM}`)

A `<button>` holding the time. Height **52 px**, minimum width 60 px (it fills its grid track), radius 2, Cormorant italic 22/600, lining tabular figures, centred. `data-available` is set exactly as the specification says, whatever the look.

| State | Fill | Time | Edge | Behaviour |
|---|---|---|---|---|
| Open (`data-available="true"`) | `--tk-raised` (lighter than the row) | linen | 2 px `--tk-control` base rule | Pointer cursor. Hover: fill `--tk-raised-hover`, base rule linen. |
| Taken (`data-available="false"`) | `--tk-recess` | `--tk-text-taken`, `line-through` | none | Default cursor, no hover change; not in the tab order. The element stays in the DOM, visible, with its test id. |
| Selected (the open cell whose form is open) | `--tk-brass` | `--tk-page` | none | At most one on the page. Returns to open when the form closes or a new search starts. |
| Focused | as its state | as its state | brass ring (1.5) | |

After a refusal refreshes availability, a cell that is now taken shows the taken look even if it was the selection: the grid always tells the server's truth, the panel tells what happened. The accessible name of each cell includes the table name, time and state (for example `aria-label="Table 2, 18:30, open"`); its text stays the bare time.

### 3.5 Legend

Shown directly above the rows whenever the grid is shown. Three items, Hanken 14 `--tk-text-2`, 24 px apart (16 on phone), each a **28 × 18 px swatch** (radius 2) and its word, 8 px gap:
- **Open:** `--tk-raised` fill with the 2 px `--tk-control` base rule.
- **Taken:** `--tk-recess` fill crossed by a 1 px `--tk-text-taken` horizontal line (inset 5 px), the same strike the taken time carries, so it stays visible against the page.
- **Your choice:** `--tk-brass` fill.

### 3.6 Table row (the hero)

- Rows are separated by a 1 px `--tk-rule` top hairline; padding 14 px 0.
- **Name block:** the small floor-plan drawing in a **72 × 40 px** box (drawing scaled to fit, left-aligned, vertically centred), then 12 px, then the table or pair name (Hanken 17/600 linen) over its description (Hanken 14 `--tk-text-2`, "Medium table, seats 4" / "Joined pair, seats 6"; "seats N" kept on one line, section 2).
- **Times:** one cell per slot of the day, in time order.
  - Inline rows (≥ 1200 px): name block column 220 px, gap 16, times `repeat(auto-fill, minmax(60px, 1fr))`, gap 4. With the usual eight slots that is one line of eight.
  - Stacked rows (720–1199 px): name block on top, 12 px, then times in `repeat(auto-fill, minmax(60px, 1fr))`, gap 4 (eight across at every width in this band).
  - Phone (< 720 px): name block on top, 12 px, then times in **`repeat(4, 1fr)`**, gap 6 px: eight slots make the four-by-two grid (a day with more slots adds lines of four).
- **Row order:** (1) single tables that can seat the searched party, in fixture order; (2) joined pairs, in `combinable` order; (3) a group caption "Too small for {party in words}" (Hanken 13 `--tk-text-2`, 24 px above, 8 px below, top hairline) followed by the single tables whose capacity is below the party. Their name, description and drawing use `--tk-text-2`, and every cell is taken. They stay visible because the grid has one cell per table per slot; grouping them last keeps the tables that can seat the party on top. A group with no members is not shown.

### 3.7 Booking panel: the form (`booking-form`)

Surface `--tk-raised`, radius 4, **3 px linen top rule**, padding 28 (20 on phone). From top to bottom:

1. Eyebrow "Your table" or "Your tables" (Hanken 14/500 `--tk-text-2`), 16 px.
2. The **large floor-plan drawing** of the selection (section 4, unit 32 px, max width 100 %), 24 px.
3. **`booking-summary`**, a block holding: the name in Cormorant 36/500 ("Table 2" / "Tables 1 + 2"); the panel description (Hanken 14 `--tk-text-2`); and a two-column list with "When" / "Where" terms in `--tk-text-2` (64 px column) and values in linen 16/500: **When** "Wednesday 7 October, 18:30", **Where** "Zum Anker". It therefore names every table and the local start time. 20 px below.
4. **Party size** (`booking-party-size`), labelled "Party size", pre-filled from the search, 120 px wide. 24 px below.
5. **Submit** (`booking-submit`), primary, 100 % wide. Label: "Book this table" / "Book these tables"; "Booking…" while sending; "Book again" in the uncertain moment. It stays a primary brass button after success (submitting the unchanged form again must return the same reference).
6. The **moment region** directly under the button (3.8); empty in the plain form.
7. Footnote "Change or cancel any time from Find a booking." (Hanken 13 `--tk-text-2`, 12 px above), always last.

- **Desktop:** always in the right column of `/`, so the results never reflow when a slot is chosen. Until a slot is chosen it shows a **placeholder**: eyebrow "Your table", a quiet drawing of one four-seat table (`--tk-quiet`), and "Choose an open time to see your table here." (Hanken 14 `--tk-text-2`). There is no `booking-form` in the placeholder. Choosing another open cell replaces the selection in place. A new search returns the panel to the placeholder.
- **Middle (720–1023):** below the results, full width, with two inner columns (gap 32): left = eyebrow, drawing, summary; right = party size, submit, moment region, footnote.
- **Phone:** below the results, full width, one column. It appears only once a slot is chosen (no placeholder). When it appears off-screen, it is scrolled into view (`block: "nearest"`, instant under reduced motion).

### 3.8 Booking panel: its moments (these replace each other in the moment region)

Every moment is a **notice**: a 3 px left rule, 16 px left padding, 16 px above; title Hanken 16/600; body Hanken 14/1.5 `--tk-text-2`. Notices are never boxes or cards. Only one is present at a time. Nothing above the button moves when one appears.

| Moment | Element | Rule | Title (colour) | Body and extras | Button |
|---|---|---|---|---|---|
| **Loading** | (none required) | 3 px `--tk-text-2` | "Booking Table 2" / "Booking Tables 1 + 2" (linen) | The loading track, then "Sending your booking to Zum Anker." | "Booking…" |
| **Uncertain** | `booking-uncertain` (the notice; nonempty text) | 3 px **dashed** `--tk-uncertain` | "No reply from the restaurant yet" (pewter) | "Your booking may already be in. Press Book again: the same details never book twice." No `booking-error`, no confirmation. | "Book again" (same button, same request) |
| **Refused** | `booking-error` (the notice) | 3 px `--tk-refused` | What happened, naming the choice: "Table 2 at 19:00 was just taken" / "Tables 1 + 2 at 18:30 were just taken" (claret) | "Another guest booked it a moment ago. The times are refreshed and your details are kept: choose another time or table." Other refusals say the rule in words ("Table 2 seats four at most" / "Choose a larger table or a smaller party."). No confirmation. The form and its inputs stay as they were. | "Book this table" / "Book these tables" |
| **Booked** | `confirmation` (the notice) holding `confirmation-reference`, `confirmation-details`, `confirmation-tables` | 3 px `--tk-booked` | "Booked. See you on Wednesday." (sage) | `confirmation-reference`: the reference alone, Cormorant 36/600 linen, letter-spacing 0.04em, 4 px above and below. `confirmation-details` (14 `--tk-text-2`): "Zum Anker, **Tables 1 + 2**, Wednesday 7 October at 18:30, for four.", where the table name is the `confirmation-tables` element. The form stays on screen above. | "Book this table" / "Book these tables" |

A field problem from the server (for example party size 0) is shown as the refused notice **and** on the party-size field (3.2).

### 3.9 Results notice (composed results-area states)

One component for every state of the results area that is not the grid. It replaces the results heading, lede, legend and rows; its outer box keeps the results column's width.

- 1 px `--tk-rule` top hairline, padding 40 px 0.
- Eyebrow: the restaurant name (Hanken 14/500 `--tk-text-2`).
- Heading: Cormorant 36/500 linen, carrying the date in words.
- The **quiet room drawing** (section 4), 24 px above and below.
- One sentence (Hanken 16 `--tk-text-2`, max 52ch) stating the next step, then at most one secondary button.

| State | Element | Heading | Sentence | Action |
|---|---|---|---|---|
| Before a search | none required | the date in the date input, in words ("Wednesday 30 September") | "Choose how many are coming, then press Find tables to see every open time." | none (the next step is the search button just above) |
| Loading | none required | "Finding tables for four" | the loading track, then "Checking every table on Wednesday 7 October." | none |
| No slots that day | `no-slots` (the notice itself) | "No seatings on Wednesday 7 October" | "Zum Anker has no tables to book that day. Try another date." | secondary "Choose another date": moves focus to the date input |
| Slots, but none free for the party | none extra | "Fully booked for four on Wednesday 7 October" | "Every table is taken for a party of four. Try a smaller party or another date." | secondary "Choose another date". **The legend and rows still follow below** (all cells taken). |
| Search failed | none required | "We could not load the tables" | What happened and what to do: "The restaurant did not answer. Nothing was booked. Search again in a moment." (a refused request states its reason in words instead) | secondary "Search again" (repeats the same search) |

- The failed-search notice has a 3 px `--tk-refused` **left** rule (24 px padding) instead of the top hairline, and its eyebrow reads "Zum Anker, Wednesday 7 October".
- While a search is loading, **no `availability-grid` and no `no-slots` element is present** (so no earlier result can be mistaken for the new one), and the results area keeps its previous height as `min-height` (at least 360 px) so the page does not jump.
- If there are no restaurants at all, the heading reads "No restaurants are taking bookings yet" and the search is not offered.

### 3.10 Neutral sign-in notice (signed-out diner)

The same notice form as 3.8 with a **linen** 3 px rule (neutral, never claret). Title linen, body `--tk-text-2`, then a **primary brass "Log in"** button (100 % of its column, to `/login`) and under it the text link "New here? Create an account" (`/signup`).

- **Clicking an open slot while signed out** shows this notice as **`auth-error`**, in the booking panel's place (desktop: the right column; phone: below the results), under the eyebrow, drawing and name of the chosen table and time. Title "Log in to book Table 2 at 19:00"; body "Bookings are made in your name. Your choice is not held until you book." There is no `booking-form` in this state. The cell shows as selected. DECIDED: `auth-error` in place, not navigation, because the diner keeps the table, time and date they chose in view.
- **The lookup screen while signed out:** the notice sits above the lookup form (title "Log in to find your booking", body "Bookings are shown only to the person who made them."). It carries no test id there. The form stays usable; its "Find booking" button is secondary while signed out so the one brass action is "Log in".

### 3.11 Cards (log in, sign up, lookup detail)

Surface `--tk-raised`, radius 4, padding 32 (24 on phone). Cards never contain cards. Notices inside them are rules and text, not boxes.

---

## 4. The floor-plan drawing (signature element)

Inline SVG, `aria-hidden="true"` (the name beside it carries the meaning). Built from one unit **u**:

| Size | u | Where |
|---|---|---|
| Small | 12 px, then scaled to fit a 72 × 40 px box | table rows |
| Large | 32 px, max width 100 % of its column | booking panel; lookup detail |
| Quiet | 24 px | results notices (the quiet room drawing) and the desktop panel placeholder |

- **One table of capacity c:** a rectangle body, **width `max(ceil(c/2), 1.5) × u`**, **height `u`**, no fill, stroke `u/8` (1.5 px at the small size). Seats are **dots** of radius `0.22 u`: `ceil(c/2)` along the top edge and `floor(c/2)` along the bottom edge, each row spread evenly (dot centres at the middles of equal divisions of the body width), with a gap of `u/4` between dot and edge. Capacity 1 = one dot on top. At most 12 dots per edge; a larger table draws 12 and its text still says "seats N".
- **Joined pair:** both bodies drawn **edge to edge** (first in `combinable` order on the left), each with its own seats by the rule above, so the dots add up to the combined capacity. At the shared edge a **brass seam**: a bar `u/4` wide, reaching `u/6` beyond the body's top and bottom. The seam is the only brass in any drawing.
- **Colours:** body stroke and dots linen, seam brass. In a "too small" row the drawing is `--tk-text-2`. In the quiet room drawing and a cancelled booking, strokes and dots are `--tk-quiet` and there is no seam.
- **Quiet room drawing:** the searched (or selected) restaurant's single tables in fixture order, drawn quiet, side by side with a 24 px gap, wrapping inside the column, at most 12 tables. Pairs are not drawn there. If the tables are not known yet, draw three tables of 2, 4 and 6 seats.

---

## 5. Screens and layout notes

### 5.1 `/`: search, availability and booking

**First seen:** the results heading ("Wednesday at Zum Anker") and the rows of times under it. **Order of importance:** open times, then the chosen table in the panel, then the search band. **Primary action:** the booking submit in the panel once a slot is chosen; before that, "Find tables".

- **Header** (3.1), then the **search band**: full-bleed `--tk-raised` with top and bottom hairlines, padding 24 px (20 on phone). Fields: Restaurant (`restaurant-select`, option text is the restaurant name, value its id), Date (`date-input`), Party size (`party-size-input`), and "Find tables" (`search-button`, primary).
  - ≥ 1024 px: one row, columns `2fr 1.3fr 1fr 160px`, gap 32, bottoms aligned. 720–1023 px: one row, `1.4fr 1.4fr 1fr 160px`, gap 24 (keeps the date field wide enough for its value and picker icon).
  - Phone: Restaurant on its own line; Date and Party size side by side (`1.4fr 1fr`, gap 16); "Find tables" full width below. Row gap 20.
- **Results area** (`availability-grid` wraps the legend and rows), padding-top 48 (32 on phone):
  - Heading: Cormorant page title "{Weekday} at {Restaurant}" ("Wednesday at Zum Anker"), 12 px, then the lede (Hanken 17 `--tk-text-2`, max 58ch): "Tables for four on Wednesday 7 October, from 18:00 until the last seating at 21:30. Choose a time to reserve it." (first and last slot times of the day).
  - Legend (3.5), 24 px above and 16 below, then the rows (3.6).
  - Non-grid states: the results notice (3.9).
- **Booking panel** (3.7 to 3.10): beside the results on desktop, below them in the middle band and on phone (32 px above).
- **States at 375 px:** before a search: the before-search notice under the search band. Loading: the loading notice at the previous results height. Results: blocks, each with its name on top and times four by two. Selected: a brass cell and the panel below the last row. Booking moments in the panel. Refused: claret notice under the button, cells refreshed. Signed out: the neutral notice with the brass "Log in" in the panel's place. No slots / fully booked / failed: the results notice with its single action.
- **States at desktop width (1280):** the same, with inline rows, the panel in the right column (placeholder until a slot is chosen) and results notices in the left column.

### 5.2 `/login` and `/signup`

**First seen:** the card title. **Primary action:** the brass submit at the bottom of the card.

- Header, then one card (3.11), `max-width: 440px`, centred, 48 px below the header (24 on phone; 16 px side margins).
- Card title (Cormorant 40): "Log in" / "Create an account"; lede (Hanken 16 `--tk-text-2`, 8 px below): "Welcome back. Log in to book and manage your tables." / "Create an account to book a table."; 24 px.
- Fields, 20 px apart. Log in: Email (`login-email`, `autocomplete="email"`), Password (`login-password`, `current-password`). Sign up, in this visual order: Your name (`signup-display-name`), Email (`signup-email`), Password (`signup-password`, `new-password`, hint "At least 8 characters").
- **`auth-error`**, only when there is an error: a refused notice (3.8 form, claret rule) **directly above the submit**, 16 px below the last field, 16 px above the button. Titles: "Email or password is wrong" (log in), "That email already has an account" (with the text link "Log in instead"), "Password needs at least 8 characters", "Enter an email like name@example.com", or the server's reason in words. The related field also gets the invalid underline.
- Submit (`login-submit` / `signup-submit`), primary, 100 % wide: "Log in" / "Create account"; busy "Logging in…" / "Creating account…".
- Under the card, centred, Hanken 14 `--tk-text-2`: "New here? Create an account" / "Already have an account? Log in" (text links).
- Phone and desktop are the same column; only margins and card padding change.

### 5.3 `/lookup`: find a booking

**First seen:** the title and the reference field. **Primary action:** "Find booking", then (when found and confirmed) the secondary "Cancel booking".

- Header, then one column `max-width: 560px`, centred, 48 px below the header (24 on phone).
- Title (Cormorant page title) "Find a booking"; lede "Enter the reference from your confirmation to see or cancel your booking."; 24 px.
- Form: "Booking reference" (`lookup-reference-input`, Hanken 17, letter-spacing 0.06em, `autocomplete="off"`, `autocapitalize="characters"`; the field shows exactly what was typed) and "Find booking" (`lookup-submit`, primary). ≥ 720 px: side by side (`1fr 160px`, gap 16, bottoms aligned). Phone: stacked, button full width.
- **Not found** (`reservation-error`): a refused notice 16 px under the form: title "No booking with reference {REF} under your name"; body "Check the reference in your confirmation. A booking is shown only to the person who made it." No detail card.
- **Found** (`reservation-detail`): a card (3.11) 32 px under the form, with a **3 px sage top rule** when confirmed and a `--tk-control` one when cancelled:
  1. Eyebrow "Booking", then the reference in Cormorant 36/600 (letter-spacing 0.04em).
  2. "Status" (14 `--tk-text-2`) and **`reservation-status`**, Hanken 16/600, text exactly `confirmed` (sage) or `cancelled` (`--tk-text-2`), no other words inside the element.
  3. The large drawing of the booked table or pair (seam for a pair; quiet when cancelled), 24 px around.
  4. **`reservation-tables`**: the table or pair name, Cormorant 36/500 ("Tables 1 + 2").
  5. List: When "Wednesday 7 October, 18:30", Where "Zum Anker", Party "Four guests".
  6. Confirmed: **`reservation-cancel-button`**, secondary, 100 % wide, "Cancel booking" (busy "Cancelling…"), a single click with no confirm dialog. Cancelled: the button is absent and the sentence "Cancelled. The table is free for other guests." (14 `--tk-text-2`) takes its place.
  7. **Cancel refused** (`reservation-error`): a refused notice directly under the cancel button. For the cutoff: "It is too close to the booking to cancel online" / the cutoff sentence (§2). For any other refusal: the reason in our own words.
- **Signed out:** the neutral sign-in notice above the form (3.10).

---

## 6. Always-rules as they apply here (the review checklist)

- One brass per region, and brass only for its four uses. Claret only for refusals and errors. Sage only for booked and confirmed. Pewter only for uncertain, always dashed.
- Every state named above is designed. No default browser error text, no empty white or blank boxes, no bare "Loading…".
- Names, dates in words and `HH:MM` times before any identifier. Identifiers only as listed in section 2.
- 375 px, 900 px and 1280 px: no horizontal page scroll, touch targets at least 44 px tall (slots 52 px), visible labels, visible brass focus.
- No gradients, glows, shadows, emoji, nested cards, decorative badges or three-column feature grids. No webfont, icon or style fetched from outside.

---

## 7. Directions explored and why they lost

Three directions were drawn inside "Dinner service" as mockups of the search screen at 375 and 1280 px (scratch only). **A "Candlelit rows"** was chosen. It keeps each time inside its own filled tile (open = lighter fill with a control-grey base rule; taken = recessed and struck), uses italic lining Cormorant for times, and places the floor-plan drawing at the head of every row. It scans fastest, holds the four-by-two phone grid naturally, and leaves brass as the only strong colour. **B "Menu card"** used linen-outlined slots, centred headings and double hairline frames around the results and the panel. It lost because eight outlined boxes per row compete with the brass selection, the frames read as nested cards, centring slows left-to-right scanning, and the time cells overflowed their frame at 1280 px. **C "Service ledger"** put the times in a header row over compact ring marks with hatched taken cells. It lost because the eye must cross-reference a header to read a time, the header cannot survive the 375 px block layout, 13 px marks read as data rather than choices, and the hatch needs a gradient pattern. Within A, three things in the reference pictures were deliberately not taken: the brass active-navigation underline, the brass panel top edge and brass "Joined pair" text all became linen or secondary, because the task allows brass for four uses only. Tables too small for the party were first kept in fixture order; they are now grouped last so the tables that can seat the party lead.
