// Shared plumbing: DOM helper, app state, API wrapper, view switching.
"use strict";

export const $ = id => document.getElementById(id);
const TOKEN_KEY = "ficsync_token";
const LIB_KEY = "ficsync_library";

export const state = {
  token: localStorage.getItem(TOKEN_KEY) || "",
  library: localStorage.getItem(LIB_KEY),   // null = the server's default
  libraries: [],
  writable: [],            // fnmatch patterns from /ui-config
  genreField: "#genre",    // which custom column counts as "genre"
  updateAvailable: false,  // set by a Check that found new chapters
  cats: null,              // {name: {url}} parsed from /categories (best effort)
  catItems: {},            // name -> [itemName, ...] cache
  filters: [],             // {field, value, exclude}
  offset: 0,
  bookId: null,
  pickingCol: null,
};

export function setToken(tok) {
  state.token = tok;
  localStorage.setItem(TOKEN_KEY, tok);
}

export function setLibrary(id) {
  state.library = id;
  localStorage.setItem(LIB_KEY, id);
  // Vocabularies and column sets are per-library; drop anything cached from
  // the previous one so filters can't leak across.
  state.cats = null;
  state.catItems = {};
  state.filters = [];
}

// calibre book ids are only unique within a library, so every call carries the
// selected one. Static /ui assets and /libraries itself are exempt.
function withLibrary(path) {
  if (state.library === null || path.startsWith("/libraries")) return path;
  return path + (path.includes("?") ? "&" : "?") +
         "library=" + encodeURIComponent(state.library);
}

export function err(msg) { const b = $("errBox"); b.textContent = msg; b.hidden = false; }
export function clearErr() { $("errBox").hidden = true; }

export async function api(path, opts = {}) {
  opts.headers = Object.assign({"X-Api-Token": state.token}, opts.headers || {});
  const r = await fetch(withLibrary(path), opts);
  if (r.status === 401) { show("token"); throw new Error("bad token"); }
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
export function show(name) {
  for (const v of Object.values(VIEWS)) $(v).hidden = true;
  $(VIEWS[name]).hidden = false;
  window.scrollTo(0, 0);
}

// fnmatch subset: * and ? only — matches the server-side fnmatch use.
export function fnmatch(pat, name) {
  const rx = "^" + pat.split("").map(c =>
    c === "*" ? ".*" : c === "?" ? "." : c.replace(/[.+^${}()|[\]\\]/g, "\\$&")
  ).join("") + "$";
  return new RegExp(rx, "i").test(name);
}
export const isWritable = f => state.writable.some(p => fnmatch(p, f));
