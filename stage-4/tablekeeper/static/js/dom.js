// Building the page. Text always goes in as text nodes, never as markup, so no data from
// the service can become HTML.

const SVG_NS = "http://www.w3.org/2000/svg";

function build(node, attrs, children) {
  for (const [name, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
    else node.setAttribute(name, value === true ? "" : String(value));
  }
  node.append(...children.flat().filter((child) => child !== null && child !== undefined && child !== false));
  return node;
}

// An HTML element: el("p", { class: "lede" }, "Some text", otherElement).
export function el(tag, attrs = {}, ...children) {
  return build(document.createElement(tag), attrs, children);
}

// An SVG element, for the floor-plan drawings.
export function svg(tag, attrs = {}, ...children) {
  return build(document.createElementNS(SVG_NS, tag), attrs, children);
}
