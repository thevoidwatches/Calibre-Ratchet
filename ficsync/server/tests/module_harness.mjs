// Loads the UI's module graph under just enough of a browser to evaluate it.
//
// `node --check` only parses; it cannot see a call to a function that was moved
// to another module, or a name that no longer exists. Actually evaluating every
// module catches both, along with any import/export mismatch.
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
globalThis.window = {
  addEventListener: noop,
  dispatchEvent: noop,
  matchMedia: () => ({matches: false, addEventListener: noop}),
  scrollTo: noop,
};
globalThis.matchMedia = globalThis.window.matchMedia;
globalThis.CustomEvent = class { constructor(type) { this.type = type; } };
globalThis.Audio = class { constructor() { this.currentTime = 0; } load() {} play() { return Promise.resolve(); } };
globalThis.URL.createObjectURL = () => "blob:stub";
globalThis.URL.revokeObjectURL = noop;
globalThis.confirm = () => false;
globalThis.prompt = () => null;
// No token stored, so boot() stops before any network call.
globalThis.fetch = () => Promise.reject(new Error("network disabled in harness"));

const failures = [];
process.on("unhandledRejection", e => failures.push("unhandled rejection: " + e.message));

await import("../ficsync/static/app.js");
await new Promise(r => setTimeout(r, 50));   // let boot()'s microtasks settle

if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log("ok");
