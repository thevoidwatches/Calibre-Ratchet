// Shared plumbing: DOM helper, app state, API wrapper, view switching.
"use strict";

export const $ = id => document.getElementById(id);
const TOKEN_KEY = "ratchet_token";
const LIB_KEY = "ratchet_library";
const SORT_KEY = "ratchet_sort";
const SORT_DIR_KEY = "ratchet_sort_dir";

export const state = {
  token: localStorage.getItem(TOKEN_KEY) || "",
  library: localStorage.getItem(LIB_KEY),   // null = the server's default
  libraries: [],
  writable: [],            // fnmatch patterns from /ui-config
  editable: [],            // ordered lookup names from /ui-config; [] = all writable
  genreField: "#genre",    // which custom column counts as "genre"
  sortOptions: [],         // [{key, label}] from /ui-config
  sort: localStorage.getItem(SORT_KEY),          // null until /ui-config answers
  sortDir: localStorage.getItem(SORT_DIR_KEY) || "desc",
  updateAvailable: false,  // set by a Check that found new chapters
  cats: null,              // {name: {url}} parsed from /categories (best effort)
  catItems: {},            // name -> [itemName, ...] cache
  // AND of ORs: terms inside a group are ORed, groups are ANDed.
  filterGroups: [],        // [{terms: [{field, value, exclude, hierarchical}]}]
  pickingGroup: null,      // group index the value picker is adding to (null = new)
  savedFilters: [],        // [{name, groups}] from /filters, per library
  offset: 0,
  bookId: null,
  bookMeta: null,          // calibre metadata for the open book
  pickingCol: null,
};

export function setToken(tok) {
  state.token = tok;
  localStorage.setItem(TOKEN_KEY, tok);
}

export function setSort(key, dir) {
  state.sort = key;
  state.sortDir = dir;
  localStorage.setItem(SORT_KEY, key);
  localStorage.setItem(SORT_DIR_KEY, dir);
}

export function setLibrary(id) {
  state.library = id;
  localStorage.setItem(LIB_KEY, id);
  // Vocabularies and column sets are per-library; drop anything cached from
  // the previous one so filters can't leak across.
  state.cats = null;
  state.catItems = {};
  state.filterGroups = [];
  state.savedFilters = [];
}

// calibre book ids are only unique within a library, so every call carries the
// selected one. Static /ui assets and /libraries itself are exempt.
function withLibrary(path) {
  if (state.library === null || path.startsWith("/libraries")) return path;
  // A caller that pinned its own library= (the catalog refresher walking
  // other libraries' books) must not have the current one appended too.
  if (path.includes("library=")) return path;
  return path + (path.includes("?") ? "&" : "?") +
         "library=" + encodeURIComponent(state.library);
}

/** The absolute address of an API path, library appended as api() would.
 *  For the shell's native download, which fetches outside the page and so
 *  cannot use a relative path. */
export function apiUrl(path) {
  return new URL(withLibrary(path), location.href).href;
}

// Fired whenever the server rejects our token. sfx.js imports this module, so
// core.js announces the rejection rather than calling play() and making the
// two circular.
export const UNAUTHORIZED_EVENT = "ratchet:unauthorized";
// Fired by err() with {kind}: "error" normally, "refused" when the message
// is a refusal rather than a failure. sfx.js turns it into the sound, so no
// caller has to remember to — and none may play "error" beside an err()
// call, or a failure sounds twice.
export const ERROR_EVENT = "ratchet:error";

// browse.js renders the filter chips and owns the "+ or" buttons, while
// picker.js owns the column/value screens and already imports browse.js.
// An event keeps that dependency one-directional instead of circular.
export const PICK_FILTER_EVENT = "ratchet:pick-filter";

// Fired by show() whenever the visible view actually changes, so sounds can
// follow navigation without core.js knowing anything about audio.
export const VIEW_CHANGED_EVENT = "ratchet:view-changed";

// "show me everything else like this" — a genre, tag, series or author on the
// book page asking the browse view to filter by it. An event because
// browse.js already imports detail.js for openBook, so detail.js cannot
// import back without making the pair circular.
export const FILTER_BY_EVENT = "ratchet:filter-by";

export function err(msg, kind = "error") {
  const b = $("errBox"); b.textContent = msg; b.hidden = false;
  window.dispatchEvent(new CustomEvent(ERROR_EVENT, {detail: {kind}}));
}
export function clearErr() { $("errBox").hidden = true; }

export async function api(path, opts = {}) {
  opts.headers = Object.assign({"X-Api-Token": state.token}, opts.headers || {});
  const r = await fetch(withLibrary(path), opts);
  if (r.status === 401) {
    show("token", false);   // an auth bounce is not a navigation
    window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
    throw new Error("bad token");
  }
  if (!r.ok) {
    let detail = "";
    try { detail = (await r.json()).detail; }
    catch (e) { detail = await r.text().catch(() => ""); }
    throw new Error(r.status + ": " +
      (typeof detail === "string" ? detail : JSON.stringify(detail)));
  }
  return r;
}
export const apiJson = async (path, opts) => (await api(path, opts)).json();

const VIEWS = {token: "vToken", browse: "vBrowse", pickcol: "vPickCol",
               pickval: "vPickVal", detail: "vDetail"};

// A history entry sitting underneath every view, so that backing out of the
// first one is something this app sees rather than the shell closing.
export const ROOT_ENTRY = "__root";

/** Where the back button goes from a given view, or null to leave the app.
 *
 *  Backing out of a sub-view lands on the book list rather than retracing the
 *  path to it: "back" from a filter screen means "never mind", and the list is
 *  what that returns to. The list is the top of the app, so back leaves from
 *  there, which is what Android users expect of a home screen. */
export function viewBehind(view) {
  return (view === "browse" || view === "token") ? null : "browse";
}

let currentView = null;
export const viewNow = () => currentView;
export function show(name, push = true) {
  for (const v of Object.values(VIEWS)) $(v).hidden = true;
  $(VIEWS[name]).hidden = false;
  window.scrollTo(0, 0);
  // Announced rather than sounded here, for the same reason as the 401 above:
  // sfx.js imports this module, so it listens instead of being called.
  // Skipped for the very first view, which is the app opening rather than a
  // move between pages.
  if (name !== currentView) {
    const from = currentView;
    currentView = name;
    if (from !== null)
      window.dispatchEvent(new CustomEvent(VIEW_CHANGED_EVENT, {detail: {view: name}}));
  }
  // Each view change becomes a history entry so the system back button (vital
  // once this runs inside an Android shell) walks views instead of closing
  // the app. The first recorded view becomes the root entry.
  if (!push) return;
  if (history.state && history.state.view === name) return;
  if (history.state === null) history.replaceState({view: name}, "");
  else history.pushState({view: name}, "");
}

// fnmatch subset: * and ? only — matches the server-side fnmatch use.
export function fnmatch(pat, name) {
  const rx = "^" + pat.split("").map(c =>
    c === "*" ? ".*" : c === "?" ? "." : c.replace(/[.+^${}()|[\]\\]/g, "\\$&")
  ).join("") + "$";
  return new RegExp(rx, "i").test(name);
}
export const isWritable = f => state.writable.some(p => fnmatch(p, f));
