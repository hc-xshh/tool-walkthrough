// Replay a driver matcher against a DOM scene recorded from the real app.
//
// The drivers build their selectors as JS strings; nothing else in the test
// suite executes them. This shim implements the few DOM APIs they use
// (querySelectorAll/querySelector, offsetParent, innerText, class, rect,
// click) so a recorded scene from Qoder 1.37 can catch a matcher that only
// breaks in the real UI.
//
// usage: node dom_replay.mjs <matcher.js> <fixture.json> <scene>
// output: {"result": <whatever the matcher returned>, "clicked": [labels]}
import fs from "node:fs";

const [matcherPath, fixturePath, sceneName] = process.argv.slice(2);
const source = fs.readFileSync(matcherPath, "utf8");
const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
const scene = (fixture.scenes || {})[sceneName];
if (!scene) {
  console.error(`no scene ${sceneName} in ${fixturePath}`);
  process.exit(2);
}

const elements = (scene.nodes || []).map((node) => {
  const attrs = node.attrs || {};
  const classList = String(attrs.class || "").split(/\s+/).filter(Boolean);
  return {
    tagName: String(node.tag || "div").toUpperCase(),
    innerText: node.text || "",
    offsetParent: node.visible ? {} : null,
    disabled: !!node.disabled,
    clicked: false,
    classList,
    getAttribute(name) {
      if (name === "class") return classList.join(" ");
      return Object.prototype.hasOwnProperty.call(attrs, name) ? attrs[name] : null;
    },
    getBoundingClientRect() {
      const r = node.rect || { x: 0, y: 0, w: 0, h: 0 };
      return { x: r.x, y: r.y, width: r.w, height: r.h, top: r.y, left: r.x };
    },
    click() { this.clicked = true; },
  };
});

// Supports the selector subset the drivers use: tag, .class, [attr], [attr="v"].
function simpleMatch(el, part) {
  const token = /(^[a-zA-Z][a-zA-Z0-9-]*)|\.([A-Za-z0-9_-]+)|\[([A-Za-z0-9_:-]+)(?:="([^"]*)")?\]/g;
  let match;
  let any = false;
  while ((match = token.exec(part))) {
    any = true;
    if (match[1]) {
      if (el.tagName !== match[1].toUpperCase()) return false;
    } else if (match[2]) {
      if (!el.classList.includes(match[2])) return false;
    } else if (match[3]) {
      const value = el.getAttribute(match[3]);
      if (value === null || value === undefined) return false;
      if (match[4] !== undefined && value !== match[4]) return false;
    }
  }
  return any;
}

function matches(el, selector) {
  return selector.split(",").some((part) => simpleMatch(el, part.trim()));
}

const document = {
  querySelectorAll: (selector) => elements.filter((el) => matches(el, selector)),
  querySelector: (selector) => elements.find((el) => matches(el, selector)) || null,
};

const result = new Function("document", `return (${source});`)(document);
const clicked = elements
  .filter((el) => el.clicked)
  .map((el) => (el.innerText || "").trim() || el.getAttribute("aria-label") || "(unlabeled)");
process.stdout.write(JSON.stringify({ result, clicked }));
