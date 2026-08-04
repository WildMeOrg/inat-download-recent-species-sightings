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

// Minimal selector engine: `.class` (checked against both a plain-string
// className and anything added via classList.add) and bare tag names. It
// walks every element this stub has ever created -- there is no real DOM
// tree here, so this is *not* scoped to descendants of the element it is
// called on, unlike a real querySelectorAll.
function matchesSelector(el, selector) {
  selector = selector.trim();
  if (selector.startsWith('.')) {
    const cls = selector.slice(1);
    const inClassList = Boolean(el.classList && el.classList._set && el.classList._set.has(cls));
    const inClassName = typeof el.className === 'string' && el.className.includes(cls);
    return inClassList || inClassName;
  }
  return typeof el.tagName === 'string' && el.tagName.toLowerCase() === selector.toLowerCase();
}

function queryAll(selector) {
  return created.filter(el => matchesSelector(el, selector));
}

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

    _listeners: {},
    addEventListener(type, handler) {
      (el._listeners[type] = el._listeners[type] || []).push(handler);
    },
    removeEventListener(type, handler) {
      if (!el._listeners[type]) return;
      el._listeners[type] = el._listeners[type].filter(h => h !== handler);
    },
    // Test hook, not a real DOM API: fire every handler registered for
    // `type`, e.g. `checkbox.checked = true; checkbox.dispatch('change');`.
    dispatch(type, event) {
      (el._listeners[type] || []).forEach(h => h.call(el, event || { target: el }));
    },

    _attrs: {},
    setAttribute(name, value) { el._attrs[name] = String(value); },
    removeAttribute(name) { delete el._attrs[name]; },
    getAttribute(name) {
      return Object.prototype.hasOwnProperty.call(el._attrs, name) ? el._attrs[name] : null;
    },

    querySelectorAll: selector => queryAll(selector),

    get textContent() { return el._text; },
    set textContent(v) { el._text = String(v); },
    set innerHTML(v) {
      if (v === '') { el.children = []; return; }
      // The real page only ever clears containers this way. If future code
      // tries to build markup through innerHTML, fail loudly here instead of
      // the stub silently swallowing it and looking fine in a test.
      throw new Error(
        'DOM stub: innerHTML only supports clearing with "" -- got ' +
        JSON.stringify(String(v).slice(0, 80))
      );
    },
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
    querySelectorAll: selector => queryAll(selector),
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
