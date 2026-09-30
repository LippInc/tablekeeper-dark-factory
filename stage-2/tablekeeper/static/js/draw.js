// The floor-plan drawings (DESIGN.md section 4): a table is a rectangle with its seats as
// dots along the top and bottom edges, drawn from one unit u. A joined pair is both tables
// edge to edge with a brass seam where they meet.

import { el, svg } from "./dom.js";

const UNITS = { small: 12, large: 32, quiet: 24 };
const SMALL_BOX = { width: 72, height: 40 };
const ROOM_WHEN_UNKNOWN = [2, 4, 6];
const MOST_TABLES_IN_A_ROOM = 12;
const MOST_SEATS_PER_EDGE = 12;

function seatRow(count, x, width, y, radius) {
  return Array.from({ length: count }, (_, index) =>
    svg("circle", { cx: x + (width * (index + 0.5)) / count, cy: y, r: radius }));
}

function bodyWidth(capacity, u) {
  return Math.max(Math.ceil(capacity / 2), 1.5) * u;
}

// The drawing of one table, or of a pair side by side, from their capacities.
function plan(capacities, u) {
  const radius = 0.22 * u;
  const stroke = u / 8;
  const bodyTop = 2 * radius + u / 4;
  const height = bodyTop + u + u / 4 + 2 * radius;
  const widths = capacities.map((capacity) => bodyWidth(capacity, u));
  const width = widths.reduce((sum, w) => sum + w, 0);
  const parts = [];
  let x = 0;
  capacities.forEach((capacity, index) => {
    const w = widths[index];
    parts.push(
      svg("rect", { x, y: bodyTop, width: w, height: u, fill: "none", stroke: "currentColor", "stroke-width": stroke }),
      svg("g", { fill: "currentColor" },
        seatRow(Math.min(Math.ceil(capacity / 2), MOST_SEATS_PER_EDGE), x, w, radius, radius),
        seatRow(Math.min(Math.floor(capacity / 2), MOST_SEATS_PER_EDGE), x, w, bodyTop + u + u / 4 + radius, radius)));
    x += w;
  });
  if (capacities.length === 2) {
    parts.push(svg("rect", {
      class: "seam", x: widths[0] - u / 8, y: bodyTop - u / 6, width: u / 4, height: u + u / 3,
    }));
  }
  return { parts, width: width + stroke, height, left: -stroke / 2 };
}

// size: "small" (fitted into the 72 x 40 box of a table row), "large" (booking panel) or
// "quiet" (the room drawing of the results notices).
export function drawing(capacities, size) {
  const { parts, width, height, left } = plan(capacities, UNITS[size]);
  const scale = size === "small" ? Math.min(1, SMALL_BOX.width / width, SMALL_BOX.height / height) : 1;
  return svg("svg", {
    class: `drawing drawing-${size}`, width: width * scale, height: height * scale,
    viewBox: `${left} 0 ${width} ${height}`, "aria-hidden": "true",
  }, parts);
}

// The quiet drawing of a room's single tables (three tables of 2, 4 and 6 seats while the
// tables are not known), side by side and wrapping.
export function quietRoom(capacities = ROOM_WHEN_UNKNOWN) {
  return el("div", { class: "room-drawing", "aria-hidden": "true" },
    capacities.slice(0, MOST_TABLES_IN_A_ROOM).map((capacity) => drawing([capacity], "quiet")));
}
