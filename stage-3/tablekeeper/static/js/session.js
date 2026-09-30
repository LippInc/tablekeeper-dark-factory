// The signed-in diner, kept in localStorage so it survives moving between the screens.
// Signing in stores what the service returned; logging out or a refused token ends it.

const STORAGE_KEY = "tablekeeper.session";
export const SESSION_CHANGED = "tablekeeper:session";

// { token, user_id, display_name } while signed in, otherwise null.
export function current() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY));
  } catch {
    return null;
  }
}

export function start({ token, user_id, display_name }) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ token, user_id, display_name }));
  window.dispatchEvent(new Event(SESSION_CHANGED));
}

export function end() {
  localStorage.removeItem(STORAGE_KEY);
  window.dispatchEvent(new Event(SESSION_CHANGED));
}
