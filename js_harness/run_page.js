// Runs a generated review page's inline <script> in a stubbed DOM, then runs an
// assertion snippet in the same context. Test-only: the page itself never needs
// node, and must stay self-contained vanilla JS opened over file://.
const fs = require('fs');
const vm = require('vm');

const [pagePath, assertionsPath] = process.argv.slice(2);

const html = fs.readFileSync(pagePath, 'utf8');
const match = html.match(/<script>\n([\s\S]*)\n    <\/script>/);
if (!match) {
  console.error('could not find the inline script block');
  process.exit(1);
}

const created = [];
function makeElement(tag) {
  const el = {
    tagName: tag, style: {}, dataset: {}, children: [], _text: '',
    classList: {
      _set: new Set(),
      add(...c) { c.forEach(x => el.classList._set.add(x)); },
      remove(...c) { c.forEach(x => el.classList._set.delete(x)); },
      contains(c) { return el.classList._set.has(c); },
    },
    appendChild(child) { el.children.push(child); return child; },
    addEventListener() {}, removeAttribute() {}, setAttribute() {},
    querySelectorAll: () => [],
    get textContent() { return el._text; },
    set textContent(v) { el._text = String(v); },
    set innerHTML(v) { if (v === '') el.children = []; },
    checked: false, type: '', className: '', id: '',
  };
  created.push(el);
  return el;
}

const byId = {};
const sandbox = {
  console,
  document: {
    getElementById: id => (byId[id] = byId[id] || makeElement('div')),
    createElement: makeElement,
    addEventListener() {},
    querySelectorAll: () => [],
  },
  navigator: { clipboard: { writeText: () => Promise.resolve() } },
  alert: () => {},
  // Exposed so assertions can inspect what was rendered.
  __created: created,
  __byId: byId,
};
vm.createContext(sandbox);

vm.runInContext(match[1], sandbox);
vm.runInContext(fs.readFileSync(assertionsPath, 'utf8'), sandbox);
