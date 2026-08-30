// Just enough of a browser for the UI modules to evaluate under node.
// Shared by the harnesses that load the module graph and that exercise
// individual behaviours.
const store = new Map();
const noop = () => {};

function stubElement(id) {
  const el = {
    id, textContent: "", innerHTML: "", value: "", hidden: false, disabled: false,
    style: {}, dataset: {}, children: [], type: "", placeholder: "", href: "", src: "",
    classList: {add: noop, remove: noop, toggle: noop, contains: () => false},
    setAttribute: noop, removeAttribute: noop, getAttribute: () => null,
    addEventListener: noop, removeEventListener: noop, append: noop, remove: noop,
    click: noop, focus: noop, querySelector: () => stubElement("q"),
    querySelectorAll: () => [], closest: () => null,
  };
  return el;
}

globalThis.localStorage = {
  getItem: k => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: k => store.delete(k),
};
globalThis.document = {
  documentElement: stubElement("html"),
  getElementById: stubElement,
  createElement: stubElement,
  querySelector: () => stubElement("q"),
  querySelectorAll: () => [],
  addEventListener: noop,
  body: stubElement("body"),
};
globalThis.history = {
  state: null,
  pushState(st) { this.state = st; },
  replaceState(st) { this.state = st; },
  back: noop,
};
globalThis.window = {
  addEventListener: noop,
  dispatchEvent: noop,
  matchMedia: () => ({matches: false, addEventListener: noop}),
  // Enough of a scroll position to test that views restore or reset it.
  scrollY: 0,
  scrollTo(x, y) { this.scrollY = y; },
};
globalThis.matchMedia = globalThis.window.matchMedia;
// Run straight away: the harness asserts the settled position, and there are
// no frames here to wait for.
globalThis.requestAnimationFrame = fn => { fn(); return 0; };
globalThis.CustomEvent = class { constructor(type) { this.type = type; } };
globalThis.Audio = class { constructor() { this.currentTime = 0; } load() {} play() { return Promise.resolve(); } };
globalThis.URL.createObjectURL = () => "blob:stub";
globalThis.URL.revokeObjectURL = noop;
globalThis.confirm = () => false;
globalThis.prompt = () => null;
// No token stored, so boot() stops before any network call.
globalThis.fetch = () => Promise.reject(new Error("network disabled in harness"));

export const localStorageStore = store;
