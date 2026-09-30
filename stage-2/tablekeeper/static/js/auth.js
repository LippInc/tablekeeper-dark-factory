// The log in and sign up screens. The service decides every rule; a refusal is shown as
// `auth-error` directly above the submit, and only while there is one.

import { call } from "./api.js";
import { el } from "./dom.js";
import * as session from "./session.js";
import { busy, button, field, idle, notice } from "./ui.js";

// What a refused field means, keyed by the field the service names.
const FIELD_PROBLEMS = {
  email: "Enter an email like name@example.com",
  password: "Password needs at least 8 characters",
  display_name: "Enter your name",
};

function problemOf(status, error, screen) {
  if (status === 401) return { title: "Email or password is wrong" };
  if (status === 409 && error.code === "email_taken") {
    return { title: "That email already has an account", field: "email", withLogIn: true };
  }
  const fieldName = Object.keys(FIELD_PROBLEMS).find((name) => error.message.startsWith(`${name} `));
  if (fieldName) return { title: FIELD_PROBLEMS[fieldName], field: fieldName };
  return { title: screen.refusedTitle, body: error.message };
}

function authScreen(main, screen) {
  const inputs = {};
  const form = el("form", { class: "card auth-card", novalidate: true });
  const submit = button("primary", screen.submitLabel, { type: "submit", "data-testid": screen.submitTestid });
  const fields = screen.fields.map(({ name, ...spec }) => {
    const built = field({ id: `${screen.name}-${name}`, name, ...spec });
    inputs[name] = built.input;
    return built.element;
  });

  function clearProblem() {
    form.querySelector("[data-testid='auth-error']")?.remove();
    Object.values(inputs).forEach((input) => input.removeAttribute("aria-invalid"));
  }

  function showProblem({ title, body, field: fieldName, withLogIn }) {
    const extra = withLogIn && el("a", { class: "text-link", href: "/login" }, "Log in instead");
    submit.before(notice({ tone: "refused", title, body, testid: "auth-error" }, extra));
    if (fieldName && inputs[fieldName]) inputs[fieldName].setAttribute("aria-invalid", "true");
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearProblem();
    busy(submit, screen.busyLabel);
    const body = Object.fromEntries(Object.entries(inputs).map(([name, input]) => [name, input.value]));
    try {
      const { status, data } = await call("POST", screen.path, { body, asGuest: true });
      if (status >= 200 && status < 300) {
        session.start(data);
        location.assign("/");
        return;
      }
      showProblem(problemOf(status, data.error, screen));
    } catch {
      showProblem({ title: "The restaurant did not answer", body: "Nothing was changed. Try again in a moment." });
    }
    idle(submit);
  });

  form.append(
    el("h1", { class: "card-title" }, screen.title),
    el("p", { class: "card-lede" }, screen.lede),
    el("div", { class: "fields" }, fields),
    submit);
  main.append(el("div", { class: "auth-page" }, form,
    el("p", { class: "auth-switch" }, screen.switchText, " ",
      el("a", { class: "text-link", href: screen.switchHref }, screen.switchLink))));
}

export function renderLogin(main) {
  authScreen(main, {
    name: "login", path: "/auth/login", title: "Log in",
    lede: "Welcome back. Log in to book and manage your tables.",
    fields: [
      { name: "email", label: "Email", type: "email", autocomplete: "email", "data-testid": "login-email" },
      { name: "password", label: "Password", type: "password", autocomplete: "current-password", "data-testid": "login-password" },
    ],
    submitLabel: "Log in", busyLabel: "Logging in…", submitTestid: "login-submit",
    refusedTitle: "We could not log you in",
    switchText: "New here?", switchLink: "Create an account", switchHref: "/signup",
  });
}

export function renderSignup(main) {
  authScreen(main, {
    name: "signup", path: "/auth/signup", title: "Create an account",
    lede: "Create an account to book a table.",
    fields: [
      { name: "display_name", label: "Your name", type: "text", autocomplete: "name", "data-testid": "signup-display-name" },
      { name: "email", label: "Email", type: "email", autocomplete: "email", "data-testid": "signup-email" },
      { name: "password", label: "Password", type: "password", autocomplete: "new-password", hint: "At least 8 characters", "data-testid": "signup-password" },
    ],
    submitLabel: "Create account", busyLabel: "Creating account…", submitTestid: "signup-submit",
    refusedTitle: "We could not create your account",
    switchText: "Already have an account?", switchLink: "Log in", switchHref: "/login",
  });
}
