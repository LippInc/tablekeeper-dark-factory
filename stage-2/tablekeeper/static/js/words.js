// Data turned into the words the diner reads (DESIGN.md section 2).

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
  "September", "October", "November", "December"];

// "2026-10-07" → "Wednesday 7 October"; the year is added only when it is not this year.
export function dateInWords(isoDate) {
  const [year, month, day] = isoDate.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  const words = `${WEEKDAYS[date.getUTCDay()]} ${day} ${MONTHS[month - 1]}`;
  return year === new Date().getFullYear() ? words : `${words} ${year}`;
}

// Today in the diner's calendar, as a date input's YYYY-MM-DD value.
export function today() {
  const now = new Date();
  return [now.getFullYear(), now.getMonth() + 1, now.getDate()]
    .map((part) => String(part).padStart(2, "0")).join("-");
}
