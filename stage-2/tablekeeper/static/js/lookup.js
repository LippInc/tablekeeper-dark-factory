// `/lookup`: find a booking by its reference, see it and cancel it (DESIGN.md 5.3).
//
// A booking is shown only to the person who made it (E5): a signed-out visitor who asks is
// shown the neutral log-in notice as `reservation-error`. Each answer replaces the one before;
// the detail is always drawn from the service's latest answer, so a cancel updates it in place.

import { call } from "./api.js";
import { el } from "./dom.js";
import { drawing } from "./draw.js";
import { timeOf } from "./grid.js";
import { dateOf, reservedTables } from "./reservation.js";
import * as session from "./session.js";
import { busy, button, field, idle, notice, signInNotice } from "./ui.js";
import { count, dateInWords, refusalWords, seatingName } from "./words.js";

// Past this an answer counts as lost; the service answers well within it.
const ANSWER_TIMEOUT_MS = 10000;
const UNITS_OF_TIME = [["day", 24 * 60], ["hour", 60], ["minute", 1]];

const SIGN_IN_BODY = "Bookings are shown only to the person who made them.";

function capitalised(text) {
  return `${text[0].toUpperCase()}${text.slice(1)}`;
}

// "Four guests", "One guest".
function guests(party) {
  return `${capitalised(count(party))} ${party === 1 ? "guest" : "guests"}`;
}

// A positive number of minutes in the largest whole unit: "two hours", "14 days", "45 minutes".
function duration(minutes) {
  const [unit, size] = UNITS_OF_TIME.find(([, length]) => minutes % length === 0);
  const amount = minutes / size;
  return `${count(amount)} ${unit}${amount === 1 ? "" : "s"}`;
}

function notFound(reference) {
  return notice({
    tone: "refused", testid: "reservation-error",
    title: reference ? `No booking with reference ${reference} under your name` : "Enter the reference from your confirmation",
    body: "Check the reference in your confirmation. A booking is shown only to the person who made it.",
  });
}

function noAnswer() {
  return notice({ tone: "refused", title: "We could not look up the booking", body: "The restaurant did not answer. Try again in a moment." });
}

function cancelRefusal({ status, data: { error } }, restaurant) {
  if (error.code === "cutoff_passed") {
    const minutes = restaurant.cancellation_cutoff_minutes;
    return {
      title: "It is too close to the booking to cancel online",
      body: `Bookings can be cancelled until ${minutes ? `${duration(minutes)} before they start` : "they start"}.`,
    };
  }
  return { title: "We could not cancel this booking", body: refusalWords(status, error).sentence };
}

// The found booking (`reservation-detail`); `show` replaces it with the service's next answer.
function detail(reservation, restaurant, show) {
  const tables = reservedTables(restaurant, reservation);
  const confirmed = reservation.status === "confirmed";
  return el("section", { class: `card lookup-detail lookup-detail-${reservation.status}`, "data-testid": "reservation-detail" },
    el("p", { class: "eyebrow" }, "Booking"),
    el("p", { class: "reference" }, reservation.reference),
    el("p", { class: "status-line" }, "Status ",
      el("span", { class: `status status-${reservation.status}`, "data-testid": "reservation-status" }, reservation.status)),
    el("div", { class: "panel-drawing" }, drawing(tables.map((table) => table.capacity), "large", { seam: confirmed })),
    el("p", { class: "panel-title", "data-testid": "reservation-tables" }, seatingName(tables)),
    el("dl", { class: "facts" },
      el("dt", {}, "When"), el("dd", {}, `${dateInWords(dateOf(reservation))}, ${timeOf(reservation)}`),
      el("dt", {}, "Where"), el("dd", {}, restaurant.name),
      el("dt", {}, "Party"), el("dd", {}, guests(reservation.party_size))),
    confirmed
      ? cancelling(reservation, restaurant, show)
      : el("p", { class: "panel-note lookup-cancelled" },
        `Cancelled. ${tables.length === 1 ? "The table is" : "The tables are"} free for other guests.`));
}

// The cancel button and, under it, what a refused or unanswered cancel means.
function cancelling(reservation, restaurant, show) {
  const moment = el("div", { class: "moment", "aria-live": "polite" });
  const cancel = button("secondary", "Cancel booking", { "data-testid": "reservation-cancel-button" });
  cancel.addEventListener("click", async () => {
    if (cancel.getAttribute("aria-busy")) return;
    moment.replaceChildren();
    busy(cancel, "Cancelling…");
    let answer = null;
    try {
      answer = await call("POST", `/reservations/${encodeURIComponent(reservation.reference)}/cancel`,
        { signal: AbortSignal.timeout(ANSWER_TIMEOUT_MS) });
    } catch {
      // no answer: shown as uncertain below
    }
    if (answer?.status === 200) {
      show(detail(answer.data, restaurant, show));
      return;
    }
    // Cancelling twice is not an error, so an unanswered cancel is simply pressed again.
    moment.replaceChildren(answer?.data?.error
      ? notice({ tone: "refused", testid: "reservation-error", ...cancelRefusal(answer, restaurant) })
      : notice({
        tone: "uncertain", title: "No reply from the restaurant yet",
        body: "The booking may already be cancelled. Press Cancel booking again to make sure.",
      }));
    idle(cancel);
  });
  return [cancel, moment];
}

// The answer for a reference: the detail, not found, or no answer.
async function lookUp(reference, show) {
  const signal = AbortSignal.timeout(ANSWER_TIMEOUT_MS);
  const found = await call("GET", `/reservations/${encodeURIComponent(reference)}`, { signal });
  if (found.status >= 400 && found.status < 500) return notFound(reference);
  if (found.status !== 200) return noAnswer();
  const restaurant = await call("GET", `/restaurants/${encodeURIComponent(found.data.restaurant_id)}`, { signal });
  return restaurant.status === 200 ? detail(found.data, restaurant.data, show) : noAnswer();
}

export function renderLookup(main) {
  const signedIn = session.current();
  const reference = field({
    label: "Booking reference", id: "lookup-reference", type: "text", autocomplete: "off",
    autocapitalize: "characters", spellcheck: "false", class: "control control-reference",
    "data-testid": "lookup-reference-input",
  });
  const submit = button(signedIn ? "primary" : "secondary", "Find booking", { type: "submit", "data-testid": "lookup-submit" });
  const answer = el("div", { class: "lookup-answer", "aria-live": "polite" });
  const show = (node) => answer.replaceChildren(node);
  let signIn = !signedIn && signInNotice({ title: "Log in to find your booking", body: SIGN_IN_BODY });

  async function find() {
    const typed = reference.input.value.trim().toUpperCase();
    if (!signedIn) {
      const prompt = signInNotice({
        title: typed ? `Log in to see booking ${typed}` : "Log in to find your booking", body: SIGN_IN_BODY, testid: "reservation-error",
      });
      signIn.replaceWith(prompt);
      signIn = prompt;
      return;
    }
    answer.replaceChildren();
    if (!typed) {
      show(notFound(typed));
      return;
    }
    busy(submit, "Finding…");
    try {
      show(await lookUp(typed, show));
    } catch {
      show(noAnswer());
    }
    idle(submit);
  }

  main.append(el("div", { class: "lookup-page" },
    el("h1", { class: "page-title" }, "Find a booking"),
    el("p", { class: "lede" }, "Enter the reference from your confirmation to see or cancel your booking."),
    signIn,
    el("form", {
      class: "lookup-form", novalidate: true,
      onsubmit: (event) => {
        event.preventDefault();
        if (!submit.getAttribute("aria-busy")) find();
      },
    }, reference.element, submit),
    answer));
}
