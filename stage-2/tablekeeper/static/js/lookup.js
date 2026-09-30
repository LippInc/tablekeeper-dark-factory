// `/lookup`: find a booking by its reference.

import { el } from "./dom.js";
import * as session from "./session.js";
import { button, field, signInNotice } from "./ui.js";

export function renderLookup(main) {
  const signedIn = session.current();
  const reference = field({
    label: "Booking reference", id: "lookup-reference", type: "text", autocomplete: "off",
    autocapitalize: "characters", spellcheck: "false", class: "control control-reference",
    "data-testid": "lookup-reference-input",
  });
  const submit = button(signedIn ? "primary" : "secondary", "Find booking", { type: "submit", "data-testid": "lookup-submit" });
  main.append(el("div", { class: "lookup-page" },
    el("h1", { class: "page-title" }, "Find a booking"),
    el("p", { class: "lede" }, "Enter the reference from your confirmation to see or cancel your booking."),
    !signedIn && signInNotice({
      title: "Log in to find your booking",
      body: "Bookings are shown only to the person who made them.",
    }),
    el("form", { class: "lookup-form", novalidate: true, onsubmit: (event) => event.preventDefault() },
      reference.element, submit)));
}
