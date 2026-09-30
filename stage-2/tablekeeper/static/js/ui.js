// Shared pieces of the design system: labelled fields, buttons, notices and cards.

import { el, svg } from "./dom.js";

// The chevron of a select, drawn inline (nothing is fetched).
function chevron() {
  return svg("svg", { class: "chevron", width: 12, height: 8, viewBox: "0 0 12 8", "aria-hidden": "true" },
    svg("path", { d: "M1 1.5 6 6.5 11 1.5", fill: "none", stroke: "currentColor", "stroke-width": 1.5 }));
}

// A labelled control (an input, or a select given `options`); the label is always visible
// above it.
export function field({ label, id, hint, options, ...attrs }) {
  const input = options
    ? el("select", { id, class: "control", ...attrs }, options.map(([value, text]) => el("option", { value }, text)))
    : el("input", { id, class: "control", ...attrs });
  const hintId = hint ? `${id}-hint` : undefined;
  if (hintId) input.setAttribute("aria-describedby", hintId);
  return {
    input,
    element: el("div", { class: "field" },
      el("label", { class: "label", for: id }, label),
      options ? el("div", { class: "select" }, input, chevron()) : input,
      hint && el("p", { class: "hint", id: hintId }, hint)),
  };
}

// kind: "primary" (brass), "secondary" (linen outline) or "text" (underlined link style).
export function button(kind, label, attrs = {}) {
  return el("button", { type: "button", class: `button button-${kind}`, ...attrs }, label);
}

export function link(kind, label, href) {
  return el("a", { class: `button button-${kind}`, href }, label);
}

// A state notice: a 3 px left rule in the tone's colour, a title and an optional body.
// tone: "neutral", "refused", "booked", "uncertain" or "loading".
export function notice({ tone, title, body, testid }, ...extras) {
  return el("div", { class: `notice notice-${tone}`, "data-testid": testid, role: tone === "refused" ? "alert" : undefined },
    el("p", { class: "notice-title" }, title),
    body && el("p", { class: "notice-body" }, body),
    extras);
}

// Asking a signed-out diner to log in: neutral, with the brass action.
export function signInNotice({ title, body, testid }) {
  return notice({ tone: "neutral", title, body, testid },
    link("primary", "Log in", "/login"),
    el("p", { class: "notice-footnote" }, "New here? ", el("a", { class: "text-link", href: "/signup" }, "Create an account")));
}

// Shows a busy label on a button without changing its width.
export function busy(buttonElement, label) {
  buttonElement.dataset.label = buttonElement.textContent;
  buttonElement.textContent = label;
  buttonElement.setAttribute("aria-busy", "true");
}

export function idle(buttonElement) {
  buttonElement.textContent = buttonElement.dataset.label;
  buttonElement.removeAttribute("aria-busy");
}
