// The shell's router: the header and the screen for the path the page was loaded on.
// A change of session (log in, log out, a refused token) draws the page again.

import { renderLogin, renderSignup } from "./auth.js";
import { el } from "./dom.js";
import { header } from "./header.js";
import { renderLookup } from "./lookup.js";
import { renderSearch } from "./search.js";
import { SESSION_CHANGED } from "./session.js";

const SCREENS = {
  "/": { title: "Book a table", render: renderSearch },
  "/signup": { title: "Create an account", render: renderSignup },
  "/login": { title: "Log in", render: renderLogin },
  "/lookup": { title: "Find a booking", render: renderLookup },
};

function render() {
  const path = location.pathname;
  const screen = SCREENS[path];
  const main = el("main", { class: "page", id: "main" });
  document.title = `${screen.title} · Tablekeeper`;
  document.getElementById("app").replaceChildren(header(path), main);
  screen.render(main);
}

window.addEventListener(SESSION_CHANGED, render);
render();
