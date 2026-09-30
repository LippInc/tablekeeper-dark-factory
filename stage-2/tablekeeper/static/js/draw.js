// The floor-plan drawings (DESIGN.md section 4): a table is a rectangle with its seats as
// dots along the top and bottom edges, drawn from one unit u.

import { el, svg } from "./dom.js";

const QUIET_UNIT = 24;
const ROOM_WHEN_UNKNOWN = [2, 4, 6];
const MOST_TABLES_IN_A_ROOM = 12;
const MOST_SEATS_PER_EDGE = 12;

function seatRow(count, width, y, radius) {
  return Array.from({ length: count }, (_, index) =>
    svg("circle", { cx: (width * (index + 0.5)) / count, cy: y, r: radius }));
}

// One table of `capacity` seats: an SVG sized to the drawing, in currentColor.
function tableDrawing(capacity, u) {
  const top = Math.min(Math.ceil(capacity / 2), MOST_SEATS_PER_EDGE);
  const bottom = Math.min(Math.floor(capacity / 2), MOST_SEATS_PER_EDGE);
  const radius = 0.22 * u;
  const stroke = u / 8;
  const width = Math.max(Math.ceil(capacity / 2), 1.5) * u;
  const bodyTop = 2 * radius + u / 4;
  const height = bodyTop + u + u / 4 + 2 * radius;
  return svg("svg", {
    class: "drawing", width: width + stroke, height, "aria-hidden": "true",
    viewBox: `${-stroke / 2} 0 ${width + stroke} ${height}`,
  },
  svg("rect", { x: 0, y: bodyTop, width, height: u, fill: "none", stroke: "currentColor", "stroke-width": stroke }),
  svg("g", { fill: "currentColor" },
    seatRow(top, width, radius, radius),
    seatRow(bottom, width, bodyTop + u + u / 4 + radius, radius)));
}

// The quiet drawing of a room's single tables (three tables of 2, 4 and 6 seats while the
// tables are not known), side by side and wrapping.
export function quietRoom(capacities = ROOM_WHEN_UNKNOWN) {
  return el("div", { class: "room-drawing", "aria-hidden": "true" },
    capacities.slice(0, MOST_TABLES_IN_A_ROOM).map((capacity) => tableDrawing(capacity, QUIET_UNIT)));
}
