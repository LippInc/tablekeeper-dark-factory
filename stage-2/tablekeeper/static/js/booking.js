// The booking panel (DESIGN.md 3.7-3.10): a quiet placeholder until a time is chosen, then
// the chosen table and time with the booking form when the diner is signed in, or the
// neutral sign-in notice as `auth-error` when not.

import { el } from "./dom.js";
import { drawing, quietRoom } from "./draw.js";
import { timeOf } from "./grid.js";
import * as session from "./session.js";
import { button, field, signInNotice } from "./ui.js";
import { dateInWords, panelDescription, seatingName } from "./words.js";

function chosen(tables) {
  return [
    el("p", { class: "eyebrow" }, tables.length === 1 ? "Your table" : "Your tables"),
    el("div", { class: "panel-drawing" }, drawing(tables.map((table) => table.capacity), "large")),
  ];
}

function summary({ tables, slot, restaurant, date }) {
  return el("div", { class: "booking-summary", "data-testid": "booking-summary" },
    el("p", { class: "panel-title" }, seatingName(tables)),
    el("p", { class: "panel-description" }, panelDescription(tables)),
    el("dl", { class: "facts" },
      el("dt", {}, "When"), el("dd", {}, `${dateInWords(date)}, ${timeOf(slot)}`),
      el("dt", {}, "Where"), el("dd", {}, restaurant.name)));
}

function bookingForm(choice) {
  const party = field({
    label: "Party size", id: "booking-party", type: "number", min: 1, inputmode: "numeric",
    value: choice.party, class: "control control-party", "data-testid": "booking-party-size",
  });
  const submit = button("primary", choice.tables.length === 1 ? "Book this table" : "Book these tables",
    { type: "submit", class: "button button-primary booking-submit", "data-testid": "booking-submit" });
  return el("form", {
    class: "booking-form", "data-testid": "booking-form", novalidate: true,
    onsubmit: (event) => event.preventDefault(),
  },
  el("div", { class: "booking-form-about" }, chosen(choice.tables), summary(choice)),
  el("div", { class: "booking-form-act" },
    party.element, submit,
    el("div", { class: "moment" }),
    el("p", { class: "footnote" }, "Change or cancel any time from Find a booking.")));
}

export function bookingPanel() {
  const element = el("aside", { class: "booking-panel", "aria-label": "Your table" });

  function show(state, ...children) {
    element.className = `booking-panel booking-panel-${state}`;
    element.replaceChildren(...children);
  }

  function reset() {
    show("empty",
      el("p", { class: "eyebrow" }, "Your table"),
      quietRoom([4]),
      el("p", { class: "panel-note" }, "Choose an open time to see your table here."));
  }

  // choice: { tables, slot, restaurant, date, party } for an open cell.
  function choose(choice) {
    if (session.current()) {
      show("form", bookingForm(choice));
    } else {
      const name = seatingName(choice.tables);
      show("signed-out", ...chosen(choice.tables), el("p", { class: "panel-title" }, name),
        signInNotice({
          title: `Log in to book ${name} at ${timeOf(choice.slot)}`,
          body: "Bookings are made in your name. Your choice is not held until you book.",
          testid: "auth-error",
        }));
    }
    element.scrollIntoView({ block: "nearest" });
  }

  reset();
  return { element, reset, choose };
}
