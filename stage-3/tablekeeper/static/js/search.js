// `/`: the search band, the results area and the booking panel.
//
// Every search takes a sequence number. Its answers (the availability and the restaurant's
// tables) are applied only while it is still the latest search, so a slow earlier search can
// never replace a later one's grid, labels or booking panel (competing clients).

import { call } from "./api.js";
import { bookingPanel } from "./booking.js";
import { el } from "./dom.js";
import { quietRoom } from "./draw.js";
import { anyOpen, gridRows, timeOf } from "./grid.js";
import { button, field, loadingTrack } from "./ui.js";
import { count, dateInWords, PARTY_SIZE_PROBLEM, refusalWords, today, weekdayOf } from "./words.js";

const LEAST_RESULTS_HEIGHT = 360;

// What a refused search means, keyed by the query parameter the service names.
const SEARCH_PROBLEMS = {
  party_size: PARTY_SIZE_PROBLEM,
  date: "Choose a date to search.",
  restaurant_id: "Choose a restaurant to search.",
};
const SEARCH_UNKNOWN_RESTAURANT = "This restaurant is not taking bookings any more. Choose another restaurant.";
const SEARCH_REFUSED = "Check the restaurant, date and party size, then search again.";
const SEARCH_UNANSWERED = "The restaurant did not answer. Nothing was booked. Search again in a moment.";

// The sentence for a refused search: an unknown restaurant, the field at fault, or the kind of
// refusal, in the search's own words.
function searchProblem({ status, data }) {
  if (status === 404) return SEARCH_UNKNOWN_RESTAURANT;
  return refusalWords(status, data?.error, { fields: SEARCH_PROBLEMS, refused: SEARCH_REFUSED, unanswered: SEARCH_UNANSWERED }).sentence;
}

// A composed state of the results area (DESIGN.md 3.9): the restaurant, a heading with the
// date in words, the quiet room drawing, one sentence and at most one action.
function resultsNotice({ eyebrow, heading, sentence, room, tone, testid, loading }, action) {
  return el("section", { class: `results-notice${tone ? ` results-notice-${tone}` : ""}`, "data-testid": testid },
    eyebrow && el("p", { class: "eyebrow" }, eyebrow),
    el("h1", { class: "results-notice-heading" }, heading),
    quietRoom(room),
    loading && loadingTrack(),
    el("p", { class: "results-notice-sentence" }, sentence),
    action);
}

function searchBand(restaurants) {
  const restaurant = field({
    label: "Restaurant", id: "search-restaurant", "data-testid": "restaurant-select",
    options: restaurants.map(({ id, name }) => [id, name]),
  });
  const date = field({ label: "Date", id: "search-date", type: "date", value: today(), required: true, "data-testid": "date-input" });
  const party = field({ label: "Party size", id: "search-party", type: "number", min: 1, value: 2, inputmode: "numeric", "data-testid": "party-size-input" });
  const submit = button("primary", "Find tables", { type: "submit", class: "button button-primary search-submit", "data-testid": "search-button" });
  const form = el("form", { class: "search-band-form", novalidate: true },
    restaurant.element, date.element, party.element, submit);
  return { form, restaurant: restaurant.input, date: date.input, party: party.input };
}

// The restaurants to search, or null when the service did not give them.
async function listRestaurants() {
  try {
    const { status, data } = await call("GET", "/restaurants");
    return status === 200 ? data.restaurants : null;
  } catch {
    return null;
  }
}

export async function renderSearch(main) {
  const results = el("div", { class: "results", "aria-live": "polite" });
  const layout = el("div", { class: "search-layout" }, results);
  main.append(layout);
  results.append(resultsNotice({
    eyebrow: dateInWords(today()), loading: true,
    heading: "Finding restaurants", sentence: "Opening the book of tables.",
  }));
  const restaurants = await listRestaurants();
  if (!restaurants) {
    results.replaceChildren(resultsNotice({
      tone: "failed", eyebrow: dateInWords(today()), heading: "We could not load the restaurants",
      sentence: "The restaurants did not answer. Nothing was booked. Try again in a moment.",
    }, button("secondary", "Try again", {
      onclick: () => {
        main.replaceChildren();
        renderSearch(main);
      },
    })));
    return;
  }
  if (restaurants.length === 0) {
    results.replaceChildren(resultsNotice({ heading: "No restaurants are taking bookings yet", sentence: "Please come back soon." }));
    return;
  }
  const band = searchBand(restaurants);
  const nameOf = (id) => restaurants.find((restaurant) => restaurant.id === id).name;
  let latest = 0;
  let lastSearch = null;
  let inFlight = null;
  let selected = null;
  // A table taken under an open form reruns the search it came from, keeping the form (R208).
  const panel = bookingPanel({ onTaken: () => run(lastSearch, { refresh: true }) });

  const chooseAnotherDate = () => button("secondary", "Choose another date", { onclick: () => band.date.focus() });

  function showBeforeSearch() {
    if (latest) return;
    results.replaceChildren(resultsNotice({
      eyebrow: nameOf(band.restaurant.value),
      heading: dateInWords(band.date.value || today()),
      sentence: "Choose how many are coming, then press Find tables to see every open time.",
    }));
  }

  function select({ cell, ...choice }) {
    selected?.classList.replace("slot-selected", "slot-open");
    cell.classList.replace("slot-open", "slot-selected");
    selected = cell;
    panel.choose(choice);
  }

  function showAnswer(search, restaurant, slots) {
    const room = restaurant.tables.map((table) => table.capacity);
    const dateWords = dateInWords(search.date);
    if (slots.length === 0) {
      results.replaceChildren(resultsNotice({
        testid: "no-slots", eyebrow: restaurant.name, room,
        heading: `No seatings on ${dateWords}`,
        sentence: `${restaurant.name} has no tables to book that day. Try another date.`,
      }, chooseAnotherDate()));
      return;
    }
    selected = null;
    const answer = { restaurant, slots, party: search.party };
    const onChoose = (choice) => select({ ...choice, restaurant, date: search.date, party: search.party });
    const intro = anyOpen(answer)
      ? [el("h1", { class: "page-title" }, `${weekdayOf(search.date)} at ${restaurant.name}`),
        el("p", { class: "lede" }, `Tables for ${count(search.party)} on ${dateWords}, from ${timeOf(slots[0])} until the last seating at ${timeOf(slots.at(-1))}. Choose a time to reserve it.`)]
      : [resultsNotice({
        eyebrow: restaurant.name, room,
        heading: `Fully booked for ${count(search.party)} on ${dateWords}`,
        sentence: `Every table is taken for a party of ${count(search.party)}. Try a smaller party or another date.`,
      }, chooseAnotherDate())];
    results.replaceChildren(el("div", { class: "availability", "data-testid": "availability-grid" },
      intro, gridRows(answer, onChoose)));
  }

  function showFailure(search, reason) {
    results.replaceChildren(resultsNotice({
      tone: "failed", eyebrow: `${nameOf(search.restaurantId)}, ${dateInWords(search.date || today())}`,
      heading: "We could not load the tables", sentence: reason,
    }, button("secondary", "Search again", { onclick: () => run(search) })));
  }

  // A new search closes the booking panel and shows the loading notice; a refresh keeps the
  // panel and the current grid until the fresh answer replaces it. Both obey the sequence check.
  async function run(search, { refresh = false } = {}) {
    const mine = ++latest;
    lastSearch = search;
    inFlight?.abort();
    inFlight = new AbortController();
    if (!refresh) {
      panel.reset();
      results.style.minHeight = `${Math.max(results.offsetHeight, LEAST_RESULTS_HEIGHT)}px`;
      results.replaceChildren(resultsNotice({
        eyebrow: nameOf(search.restaurantId), loading: true,
        heading: search.party > 0 ? `Finding tables for ${count(search.party)}` : "Finding tables",
        sentence: `Checking every table on ${dateInWords(search.date || today())}.`,
      }));
    }
    const query = new URLSearchParams({ restaurant_id: search.restaurantId, date: search.date, party_size: search.partyText });
    const { signal } = inFlight;
    try {
      const [availability, detail] = await Promise.all([
        call("GET", `/availability?${query}`, { signal }),
        call("GET", `/restaurants/${encodeURIComponent(search.restaurantId)}`, { signal }),
      ]);
      if (mine !== latest) return;  // a later search owns the results area now
      results.style.minHeight = "";
      if (availability.status !== 200) {
        showFailure(search, searchProblem(availability));
        return;
      }
      showAnswer(search, detail.data, availability.data.slots);
    } catch {
      if (mine !== latest) return;
      results.style.minHeight = "";
      showFailure(search, SEARCH_UNANSWERED);
    }
  }

  band.form.addEventListener("submit", (event) => {
    event.preventDefault();
    run({
      restaurantId: band.restaurant.value, date: band.date.value,
      partyText: band.party.value, party: Number(band.party.value),
    });
  });
  band.restaurant.addEventListener("change", showBeforeSearch);
  band.date.addEventListener("change", showBeforeSearch);
  showBeforeSearch();
  layout.before(el("section", { class: "search-band", "aria-label": "Find a table" }, el("div", { class: "band-inner" }, band.form)));
  layout.append(panel.element);
}
