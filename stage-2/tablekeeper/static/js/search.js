// `/`: the search band and the results area. Until the diner searches, the results area is
// the composed before-search notice: the restaurant, the date in words and the next step.

import { call } from "./api.js";
import { el } from "./dom.js";
import { quietRoom } from "./draw.js";
import { button, field } from "./ui.js";
import { dateInWords, today } from "./words.js";

function resultsNotice({ eyebrow, heading, sentence }) {
  return el("section", { class: "results-notice", "aria-live": "polite" },
    eyebrow && el("p", { class: "eyebrow" }, eyebrow),
    el("h1", { class: "results-notice-heading" }, heading),
    quietRoom(),
    el("p", { class: "results-notice-sentence" }, sentence));
}

function searchBand(restaurants) {
  const restaurant = field({
    label: "Restaurant", id: "search-restaurant", "data-testid": "restaurant-select",
    options: restaurants.map(({ id, name }) => [id, name]),
  });
  const date = field({ label: "Date", id: "search-date", type: "date", value: today(), required: true, "data-testid": "date-input" });
  const party = field({ label: "Party size", id: "search-party", type: "number", min: 1, value: 2, inputmode: "numeric", "data-testid": "party-size-input" });
  const submit = button("primary", "Find tables", { type: "submit", class: "button button-primary search-submit", "data-testid": "search-button" });
  const form = el("form", { class: "search-band-form", novalidate: true, onsubmit: (event) => event.preventDefault() },
    restaurant.element, date.element, party.element, submit);
  return { form, restaurant: restaurant.input, date: date.input };
}

export async function renderSearch(main) {
  const results = el("div", { class: "results" });
  const { data } = await call("GET", "/restaurants");
  const restaurants = data.restaurants;
  if (restaurants.length === 0) {
    results.append(resultsNotice({ heading: "No restaurants are taking bookings yet", sentence: "Please come back soon." }));
    main.append(el("div", { class: "search-layout" }, results));
    return;
  }
  const band = searchBand(restaurants);
  const beforeSearch = () => resultsNotice({
    eyebrow: restaurants.find(({ id }) => id === band.restaurant.value).name,
    heading: dateInWords(band.date.value || today()),
    sentence: "Choose how many are coming, then press Find tables to see every open time.",
  });
  const showBeforeSearch = () => results.replaceChildren(beforeSearch());
  band.restaurant.addEventListener("change", showBeforeSearch);
  band.date.addEventListener("change", showBeforeSearch);
  showBeforeSearch();
  main.append(
    el("section", { class: "search-band", "aria-label": "Find a table" }, el("div", { class: "band-inner" }, band.form)),
    el("div", { class: "search-layout" }, results));
}
