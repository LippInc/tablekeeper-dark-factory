// The header every screen shares: brand, the two destinations, and the diner's account.

import { el } from "./dom.js";
import * as session from "./session.js";
import { button } from "./ui.js";

const NAVIGATION = [["Book a table", "/"], ["Find a booking", "/lookup"]];

function account() {
  const signedIn = session.current();
  if (!signedIn) {
    return el("div", { class: "account" },
      el("a", { class: "text-link", href: "/login" }, "Log in"),
      el("a", { class: "text-link", href: "/signup" }, "Sign up"));
  }
  return el("div", { class: "account" },
    el("span", { class: "account-lead" }, "Signed in as"),
    el("span", { class: "account-name", "data-testid": "current-user", title: signedIn.display_name }, signedIn.display_name),
    button("text", "Log out", { "data-testid": "logout-button", onclick: () => session.end() }));
}

export function header(path) {
  return el("header", { class: "site-header" },
    el("div", { class: "site-header-inner" },
      el("a", { class: "brand", href: "/" }, "Tablekeeper"),
      el("nav", { class: "site-nav", "aria-label": "Main" },
        NAVIGATION.map(([label, href]) => el("a", {
          class: "site-nav-item", href, "aria-current": href === path ? "page" : undefined,
        }, label))),
      account()));
}
