// Data turned into the words the diner reads (DESIGN.md section 2).

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
  "September", "October", "November", "December"];
const NUMBERS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
  "ten", "eleven", "twelve"];
const SHORT_LABEL = 4;

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

function isShort(label) {
  return label.length <= SHORT_LABEL && !label.includes(" ");
}

// A table: "Table 2" for a short label, otherwise the label as given ("Window").
function tableName(table) {
  return isShort(table.label) ? `Table ${table.label}` : table.label;
}

// A table or a pair: "Table 2", "Tables 1 + 2", "Window + Bar"; every member's label is in it.
export function seatingName(tables) {
  if (tables.length === 1) return tableName(tables[0]);
  const labels = tables.map((table) => table.label);
  return labels.every(isShort) ? `Tables ${labels.join(" + ")}` : labels.join(" + ");
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

// The row's description: "Medium table, seats 4" / "Joined pair, seats 6".
export function rowDescription(tables) {
  return `${tables.length === 1 ? sizeWord(tables[0].capacity) : "Joined pair"}, seats ${capacityOf(tables)}`;
}

// The booking panel's description: "Medium table, for up to four" /
// "Tables 1 and 2 pushed together, for up to six".
export function panelDescription(tables) {
  const upTo = `for up to ${count(capacityOf(tables))}`;
  if (tables.length === 1) return `${sizeWord(tables[0].capacity)}, ${upTo}`;
  const names = seatingName(tables).replace(" + ", " and ");
  return `${names} pushed together, ${upTo}`;
}
