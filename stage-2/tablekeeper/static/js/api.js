// The one way the screens talk to the service: JSON in and out, the bearer token of the
// signed-in diner attached. A token the service no longer accepts ends the session.

import * as session from "./session.js";

// Resolves to { status, data } where data is the parsed JSON body (null when there is none).
// A request that never gets an answer rejects, so callers can tell "no answer" from "refused".
// Logging in and signing up go without the session (`asGuest`), so their 401 is about the
// credentials typed, never about the token. `signal` lets a caller abandon a request.
export async function call(method, path, { body, asGuest = false, signal } = {}) {
  const signedIn = asGuest ? null : session.current();
  const headers = {};
  if (signedIn) headers.Authorization = `Bearer ${signedIn.token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  const text = await response.text();
  if (response.status === 401 && signedIn) session.end();
  return { status: response.status, data: text ? JSON.parse(text) : null };
}
