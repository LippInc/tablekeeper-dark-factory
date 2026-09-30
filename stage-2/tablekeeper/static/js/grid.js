// The availability grid (DESIGN.md 3.4-3.6): one row per table or declared pair, one cell
// per slot. A cell is open exactly when the service lists it for the searched party:
// `available_table_ids` for a table, `available_options` for a pair (absent on a service
// without combined tables, which then has no pair rows).

import { el } from "./dom.js";
import { drawing } from "./draw.js";
import { capacityOf, count, rowDescription, seatingName } from "./words.js";

// The HH:MM of a slot, from its local start (never from an instant).
export function timeOf(slot) {
  return slot.starts_at_local.slice(11, 16);
}

// Every seating the grid shows, in DESIGN.md's order: the tables that seat the party (fixture
// order), the declared pairs that seat it (declared order), then the tables too small for it.
function seatingsFor(restaurant, party) {
  const table = (id) => restaurant.tables.find((candidate) => candidate.id === id);
  const singles = restaurant.tables.map((one) => [one]);
  const pairs = (restaurant.combinable ?? []).map((ids) => ids.map(table));
  const seats = (tables) => capacityOf(tables) >= party;
  return {
    fitting: [...singles.filter(seats), ...pairs.filter(seats)],
    tooSmall: singles.filter((tables) => !seats(tables)),
  };
}

function isOpen(tables, slot) {
  if (tables.length === 1) return slot.available_table_ids.includes(tables[0].id);
  const ids = tables.map((table) => table.id).join("+");
  return (slot.available_options ?? []).some((option) => option.table_ids.join("+") === ids);
}

function cell(tables, slot, onChoose) {
  const time = timeOf(slot);
  const open = isOpen(tables, slot);
  const name = seatingName(tables);
  const button = el("button", {
    type: "button",
    class: open ? "slot slot-open" : "slot slot-taken",
    "data-testid": `slot-${tables.map((table) => table.id).join("+")}-${time}`,
    "data-available": String(open),
    "aria-label": `${name}, ${time}, ${open ? "open" : "taken"}`,
    "aria-disabled": open ? undefined : "true",
    tabindex: open ? undefined : "-1",
  }, time);
  if (open) button.addEventListener("click", () => onChoose({ tables, slot, cell: button }));
  return button;
}

function row(tables, slots, onChoose, tooSmall) {
  return el("div", { class: tooSmall ? "table-row table-row-small" : "table-row" },
    el("div", { class: "row-name" },
      el("div", { class: "drawing-box" }, drawing(tables.map((table) => table.capacity), "small")),
      el("div", { class: "row-words" },
        el("p", { class: "row-title" }, seatingName(tables)),
        el("p", { class: "row-description" }, rowDescription(tables)))),
    el("div", { class: "row-times" }, slots.map((slot) => cell(tables, slot, onChoose))));
}

function legend() {
  const item = (kind, word) => el("span", { class: "legend-item" }, el("span", { class: `swatch swatch-${kind}` }), word);
  return el("div", { class: "legend", "aria-hidden": "true" },
    item("open", "Open"), item("taken", "Taken"), item("selected", "Your choice"));
}

// The rows for a search's answer; `onChoose` receives the seating, slot and cell of an open cell.
export function gridRows({ restaurant, slots, party }, onChoose) {
  const { fitting, tooSmall } = seatingsFor(restaurant, party);
  const rows = fitting.map((tables) => row(tables, slots, onChoose, false));
  if (tooSmall.length) {
    rows.push(el("p", { class: "group-caption" }, `Too small for ${count(party)}`),
      ...tooSmall.map((tables) => row(tables, slots, onChoose, true)));
  }
  return [legend(), el("div", { class: "rows" }, rows)];
}

// Whether any seating has an open cell in the day.
export function anyOpen({ restaurant, slots, party }) {
  return seatingsFor(restaurant, party).fitting.some((tables) => slots.some((slot) => isOpen(tables, slot)));
}
