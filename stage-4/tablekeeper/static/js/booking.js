// The booking panel (DESIGN.md 3.7-3.10): a quiet placeholder until a time is chosen, then
// the chosen table and time with the booking form when the diner is signed in, or the
// neutral sign-in notice as `auth-error` when not.
//
// A booking attempt shows its moment under the submit, one at a time: loading while it is in
// flight, then booked, refused or uncertain (E7). Only the service's answer makes a booking:
// a 2xx that carries the reservation is booked, a 4xx with an error is refused, and anything
// else (no answer, a timeout, a 5xx, a body that does not parse) may or may not have booked,
// so it is uncertain. The idempotency key belongs to the form's content: an unchanged form
// sends the same body with the same key again, so pressing again after a lost answer or after
// success returns the original booking; a changed field makes a new key (§7). A booked notice
// shows the booking as it stands now, read back from the service: a replayed answer is the
// original one, from before any seating repair moved the booking.

import { call } from "./api.js";
import { el } from "./dom.js";
import { drawing, quietRoom } from "./draw.js";
import { timeOf } from "./grid.js";
import { dateOf, reservedTables } from "./reservation.js";
import * as session from "./session.js";
import { busy, button, field, idle, loadingTrack, notice, signInNotice } from "./ui.js";
import {
  capacityOf, count, dateInWords, panelDescription, PARTY_SIZE_PROBLEM, refusalWords, seatingName, weekdayOf,
} from "./words.js";

// Past this the answer counts as lost; the service answers well within it.
const BOOKING_TIMEOUT_MS = 10000;

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

// An idempotency key: 32 random hex digits.
function newKey() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

// A single table is sent as `table_id`, the shape every stage of the service accepts (and the
// body a stage-1 receipt holds); a pair as `table_ids` in the restaurant's combinable order.
function requestBody({ tables, slot, restaurant }, partyText) {
  const ids = tables.map((table) => table.id);
  return {
    restaurant_id: restaurant.id,
    ...(ids.length === 1 ? { table_id: ids[0] } : { table_ids: ids }),
    starts_at_local: slot.starts_at_local,
    party_size: Number(partyText),
  };
}

function outcomeOf({ status, data }) {
  if (status >= 200 && status < 300 && typeof data?.reference === "string") return { kind: "booked", reservation: data };
  if (status >= 400 && status < 500 && data?.error) return { kind: "refused", status, error: data.error };
  return { kind: "uncertain" };
}

// A refusal in words, naming the choice; `party` marks the party size as the field at fault.
function refusal({ tables, slot }, { status, error }) {
  const name = seatingName(tables);
  const one = tables.length === 1;
  if (error.code === "table_unavailable") {
    return {
      title: `${name} at ${timeOf(slot)} ${one ? "was" : "were"} just taken`,
      body: "It was booked or closed a moment ago. The times are refreshed and your details are kept: choose another time or table.",
    };
  }
  if (error.code === "party_exceeds_capacity") {
    return { title: `${name} ${one ? "seats" : "seat"} ${count(capacityOf(tables))} at most`, body: "Choose a larger table or a smaller party.", party: true };
  }
  const { field, sentence } = refusalWords(status, error, { fields: { party_size: PARTY_SIZE_PROBLEM } });
  return field ? { title: sentence, party: true } : { title: `We could not book ${name} at ${timeOf(slot)}`, body: sentence };
}

// The booked reservation as it stands now (Q25), or the answer itself when it cannot be read.
async function current(reservation) {
  try {
    const { status, data } = await call("GET", `/reservations/${encodeURIComponent(reservation.reference)}`,
      { signal: AbortSignal.timeout(BOOKING_TIMEOUT_MS) });
    return status === 200 && data?.reference === reservation.reference ? data : reservation;
  } catch {
    return reservation;
  }
}

// The confirmation, built only from the service's reservation.
function confirmation({ restaurant }, reservation) {
  const tables = reservedTables(restaurant, reservation);
  const date = dateOf(reservation);
  return notice({ tone: "booked", title: `Booked. See you on ${weekdayOf(date)}.`, testid: "confirmation" },
    el("p", { class: "reference", "data-testid": "confirmation-reference" }, reservation.reference),
    el("p", { class: "notice-body", "data-testid": "confirmation-details" },
      `${restaurant.name}, `,
      el("span", { class: "confirmation-tables", "data-testid": "confirmation-tables" }, seatingName(tables)),
      `, ${dateInWords(date)} at ${timeOf(reservation)}, for ${count(reservation.party_size)}.`));
}

function bookingForm(choice, onTaken) {
  const bookLabel = choice.tables.length === 1 ? "Book this table" : "Book these tables";
  const party = field({
    label: "Party size", id: "booking-party", type: "number", min: 1, inputmode: "numeric",
    value: choice.party, class: "control control-party", "data-testid": "booking-party-size",
  });
  const submit = button("primary", bookLabel,
    { type: "submit", class: "button button-primary booking-submit", "data-testid": "booking-submit" });
  const moment = el("div", { class: "moment", "aria-live": "polite" });
  let sent = null;  // { text, key }: the body last sent, as JSON, and its idempotency key
  let sending = false;

  function show(outcome) {
    if (outcome.kind === "booked") return confirmation(choice, outcome.reservation);
    if (outcome.kind === "uncertain") {
      return notice({
        tone: "uncertain", testid: "booking-uncertain", title: "No reply from the restaurant yet",
        body: "Your booking may already be in. Press Book again: the same details never book twice.",
      });
    }
    const { party: partyAtFault, ...words } = refusal(choice, outcome);
    if (partyAtFault) party.input.setAttribute("aria-invalid", "true");
    return notice({ tone: "refused", testid: "booking-error", ...words });
  }

  async function book() {
    const body = requestBody(choice, party.input.value);
    const text = JSON.stringify(body);
    if (text !== sent?.text) sent = { text, key: newKey() };
    sending = true;
    party.input.removeAttribute("aria-invalid");
    moment.replaceChildren(notice({ tone: "loading", title: `Booking ${seatingName(choice.tables)}` },
      loadingTrack(), el("p", { class: "notice-body" }, `Sending your booking to ${choice.restaurant.name}.`)));
    busy(submit, "Booking…");
    let outcome;
    try {
      outcome = outcomeOf(await call("POST", "/reservations", {
        body, headers: { "Idempotency-Key": sent.key }, signal: AbortSignal.timeout(BOOKING_TIMEOUT_MS),
      }));
    } catch {
      outcome = { kind: "uncertain" };
    }
    if (outcome.kind === "booked") outcome = { ...outcome, reservation: await current(outcome.reservation) };
    // The refreshed times are in place before the refusal is shown; a closed form refreshes nothing.
    if (outcome.error?.code === "table_unavailable" && form.isConnected) await onTaken();
    sending = false;
    idle(submit);
    submit.textContent = outcome.kind === "uncertain" ? "Book again" : bookLabel;
    moment.replaceChildren(show(outcome));
  }

  const form = el("form", {
    class: "booking-form", "data-testid": "booking-form", novalidate: true,
    onsubmit: (event) => {
      event.preventDefault();
      if (!sending) book();
    },
  },
  el("div", { class: "booking-form-about" }, chosen(choice.tables), summary(choice)),
  el("div", { class: "booking-form-act" },
    party.element, submit, moment,
    el("p", { class: "footnote" }, "Change or cancel any time from Find a booking.")));
  return form;
}

// onTaken: reruns the current search when the chosen table was taken; resolves once done.
export function bookingPanel({ onTaken }) {
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
      show("form", bookingForm(choice, onTaken));
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
