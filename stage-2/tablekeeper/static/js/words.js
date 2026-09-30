// Data turned into the words the diner reads (DESIGN.md section 2).

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
  "September", "October", "November", "December"];
const NUMBERS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
  "ten", "eleven", "twelve"];
const LONGEST_CODE = 4;

// What a refused party size means, wherever the diner typed it.
export const PARTY_SIZE_PROBLEM = "Enter how many are coming as a whole number, one or more.";

const REFUSED = "The restaurant could not accept this. Nothing was changed. Check the details and try again.";
const UNANSWERED = "The restaurant did not answer. Nothing was changed. Try again in a moment.";

// A refusal told in our own words, never in the service's (R218, R226): the screen's sentence
// for the field the service names, otherwise one chosen by the kind of refusal (a service
// error reads as no answer). A screen may give its own `refused` and `unanswered` sentences.
export function refusalWords(status, error, { fields = {}, refused = REFUSED, unanswered = UNANSWERED } = {}) {
  const message = error?.message ?? "";
  const field = Object.keys(fields).find((name) => message.startsWith(`${name} `));
  if (field) return { field, sentence: fields[field] };
  return { sentence: status >= 500 ? unanswered : refused };
}

function parts(isoDate) {
  const [year, month, day] = isoDate.split("-").map(Number);
  return { year, month, day, weekday: WEEKDAYS[new Date(Date.UTC(year, month - 1, day)).getUTCDay()] };
}

// "2026-10-07" → "Wednesday 7 October"; the year is added only when it is not this year.
export function dateInWords(isoDate) {
  const { year, month, day, weekday } = parts(isoDate);
  const words = `${weekday} ${day} ${MONTHS[month - 1]}`;
  return year === new Date().getFullYear() ? words : `${words} ${year}`;
}

// "2026-10-07" → "Wednesday".
export function weekdayOf(isoDate) {
  return parts(isoDate).weekday;
}

// Today in the diner's calendar, as a date input's YYYY-MM-DD value.
export function today() {
  const now = new Date();
  return [now.getFullYear(), now.getMonth() + 1, now.getDate()]
    .map((part) => String(part).padStart(2, "0")).join("-");
}

// 1..12 in words ("four"), digits above ("14").
export function count(number) {
  return NUMBERS[number] ?? String(number);
}

// A label that is a code rather than a name: at most four characters, no space, and either
// a digit in it or a single letter ("1", "12", "A3", "B"; not "Bar").
function isCode(label) {
  return label.length <= LONGEST_CODE && !label.includes(" ") && (/\d/.test(label) || label.length === 1);
}

// A table: "Table 2" for a code, otherwise the label as given ("Bar", "Window").
function tableName(table) {
  return isCode(table.label) ? `Table ${table.label}` : table.label;
}

// A table or a pair, each member read as on its own row: "Table 2", "Bar + Window",
// "Table 3 + Window"; two codes say the prefix once, "Tables 1 + 2". Every label is in it.
export function seatingName(tables) {
  if (tables.length === 1) return tableName(tables[0]);
  const labels = tables.map((table) => table.label);
  return labels.every(isCode) ? `Tables ${labels.join(" + ")}` : tables.map(tableName).join(" + ");
}

function sizeWord(capacity) {
  if (capacity <= 2) return "Small table";
  if (capacity <= 4) return "Medium table";
  if (capacity <= 8) return "Large table";
  return "Banquet table";
}

export function capacityOf(tables) {
  return tables.reduce((sum, table) => sum + table.capacity, 0);
}

// The row's description: "Medium table, seats 4" / "Joined pair, seats 6", with a no-break
// space in "seats N" so a narrow column breaks after the comma, never before the number.
export function rowDescription(tables) {
  return `${tables.length === 1 ? sizeWord(tables[0].capacity) : "Joined pair"}, seats\u00A0${capacityOf(tables)}`;
}

// The booking panel's description: "Medium table, for up to four" /
// "Tables 1 and 2 pushed together, for up to six".
export function panelDescription(tables) {
  const upTo = `for up to ${count(capacityOf(tables))}`;
  if (tables.length === 1) return `${sizeWord(tables[0].capacity)}, ${upTo}`;
  const names = seatingName(tables).replace(" + ", " and ");
  return `${names} pushed together, ${upTo}`;
}
