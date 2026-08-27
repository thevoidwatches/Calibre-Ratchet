// The shell's offline library: renders Ratchet/.catalog.json — written by the
// served UI while online — when the server is unreachable, so downloaded
// books stay browsable, filterable, and openable in Moon+.
//
// Bundled into the APK (changes here need a rebuild), so logic is kept
// minimal and stable; anything that can live in served JS does. The pure
// helpers up top run under plain node for tests — everything DOM-touching is
// behind the `document` guard at the bottom.
"use strict";

export const SERVER = "http://desktop-2mmhpaf.tail77896d.ts.net:8484";

// ---------------- pure helpers (node-tested) ----------------

/** "The Abyss #2" — same shape the served UI shows next to a title. */
export function seriesText(b) {
  if (!b || !b.series) return "";
  const n = Number(b.series_index);
  return Number.isFinite(n) && b.series_index !== null && b.series_index !== ""
    ? b.series + " #" + +n.toFixed(2) : b.series;
}

/** Hierarchical chip match: "Fantasy" hits "Fantasy" and "Fantasy.Epic". */
export function hierHit(values, sel) {
  return (values || []).some(v => v === sel || (v && v.startsWith(sel + ".")));
}

/** sel: {library, genres:[], tags:[], readinglist:[]} — chips within a
 *  section OR together, sections AND together, mirroring the main UI's
 *  filter groups. q is a plain substring over title/authors/series. */
export function matches(b, sel, q) {
  if (sel.library && b.library !== sel.library) return false;
  if (sel.genres.length && !sel.genres.some(g => hierHit(b.genres, g)))
    return false;
  if (sel.tags.length && !sel.tags.some(t => hierHit(b.tags, t)))
    return false;
  if (sel.readinglist.length && !sel.readinglist.includes(b.readinglist || ""))
    return false;
  if (q) {
    const hay = [b.title, (b.authors || []).join(" "), b.series || ""]
      .join(" ").toLowerCase();
    if (!hay.includes(q.toLowerCase())) return false;
  }
  return true;
}

const cmp = (a, b) => (a > b) - (a < b);
const lower = s => (s || "").toLowerCase();

export function sortBooks(books, key) {
  const by = {
    recent: (a, b) => cmp(b.last_modified || "", a.last_modified || ""),
    title: (a, b) => cmp(lower(a.title), lower(b.title)),
    author: (a, b) =>
      cmp(lower((a.authors || [])[0]), lower((b.authors || [])[0])) ||
      cmp(lower(a.series), lower(b.series)) ||
      cmp(a.series_index || 0, b.series_index || 0) ||
      cmp(lower(a.title), lower(b.title)),
    series: (a, b) =>
      cmp(lower(a.series), lower(b.series)) ||
      cmp(a.series_index || 0, b.series_index || 0) ||
      cmp(lower(a.title), lower(b.title)),
  };
  return books.slice().sort(by[key] || by.recent);
}

/** Distinct chip values per section, sorted. Genres and tags offer every
 *  hierarchy level, so a book tagged "Fantasy.Epic" is findable via a plain
 *  "Fantasy" chip too. */
export function chipValues(books) {
  const genres = new Set(), tags = new Set(), lists = new Set(),
        libs = new Set();
  const addLevels = (set, v) => {
    const parts = String(v).split(".");
    for (let i = 1; i <= parts.length; i++) set.add(parts.slice(0, i).join("."));
  };
  for (const b of books || []) {
    libs.add(b.library);
    for (const g of b.genres || []) addLevels(genres, g);
    for (const t of b.tags || []) addLevels(tags, t);
    if (b.readinglist) lists.add(b.readinglist);
  }
  const sorted = set => [...set].sort((a, b) => a.localeCompare(b));
  return {libraries: sorted(libs), genres: sorted(genres),
          tags: sorted(tags), readinglists: sorted(lists)};
}

// ---------------- DOM (absent under node) ----------------

function $(id) { return document.getElementById(id); }
function plugins() {
  return (window.Capacitor && window.Capacitor.Plugins) || null;
}

// Same preference order as the served UI's storage.js.
const READER_PACKAGES = ["com.flyersoft.moonreaderp", "com.flyersoft.moonreader"];

let books = [];
const sel = {library: "", genres: [], tags: [], readinglist: []};

function parseCatalog(raw) {
  let cat;
  try { cat = JSON.parse(raw); }
  catch (e) { return {error: "catalog file is malformed"}; }
  if (!Array.isArray(cat.books)) return {error: "catalog file is malformed"};
  if (!cat.books.length)
    return {error: "the catalog is empty — open the app online once"};
  return {books: cat.books};
}

/** {books} on success, {error} with a human-readable reason otherwise, so
 *  the page can say WHY the offline library is unavailable.
 *
 *  RatchetOffline (the shell's addJavascriptInterface object) is the normal
 *  path: Capacitor's injected runtime never reaches this page — with an
 *  external server.url its bridge script is origin-restricted to the server,
 *  and this page is served from http://localhost. The Capacitor branch stays
 *  as a fallback for any build where injection does happen. */
async function loadCatalog() {
  if (window.RatchetOffline) {
    let raw;
    try { raw = window.RatchetOffline.readCatalog(); }
    catch (e) { return {error: "catalog read failed: " + ((e && e.message) || e)}; }
    if (!raw) return {error: "no catalog yet — open the app online once"};
    return parseCatalog(raw);
  }
  const p = plugins();
  if (!p || !p.Filesystem)
    return {error: "the app's native bridge is unavailable on this page"};
  try {
    const res = await p.Filesystem.readFile({path: "Ratchet/.catalog.json",
      directory: "EXTERNAL_STORAGE", encoding: "utf8"});
    return parseCatalog(res.data);
  } catch (e) {
    return {error: "no catalog yet — open the app online once (" +
                   ((e && e.message) || e) + ")"};
  }
}

async function openBook(b) {
  if (window.RatchetOffline) {
    let msg;
    try {
      msg = window.RatchetOffline.openBook(
        b.library, b.file, JSON.stringify(READER_PACKAGES));
    } catch (e) { msg = (e && e.message) || String(e); }
    if (msg) alert("Could not open — " + msg);
    return;
  }
  const p = plugins();
  if (!p || !p.RatchetNative) return;
  try {
    const res = await p.Filesystem.getUri(
      {path: "Ratchet/" + b.library + "/" + b.file,
       directory: "EXTERNAL_STORAGE"});
    await p.RatchetNative.openFile({
      path: decodeURIComponent(res.uri.replace(/^file:\/\//, "")),
      contentType: "application/epub+zip",
      packages: READER_PACKAGES,
    });
  } catch (e) {
    alert("Could not open — the file may have been deleted from the device.");
  }
}

/** Reachable at all is the question, so an opaque no-cors probe is enough —
 *  it resolves only when something answered at that address. */
async function serverUp() {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 4000);
  try {
    await fetch(SERVER + "/health", {mode: "no-cors", signal: ctl.signal,
                                     cache: "no-store"});
    return true;
  } catch (e) { return false; }
  finally { clearTimeout(timer); }
}

function chipRow(host, label, values, picked, onToggle) {
  if (!values.length) return;
  const row = document.createElement("div");
  row.className = "chiprow";
  const lab = document.createElement("span");
  lab.className = "chiplabel";
  lab.textContent = label;
  row.append(lab);
  for (const v of values) {
    const c = document.createElement("button");
    c.className = "chip" + (picked.includes(v) ? " on" : "");
    c.textContent = v;
    c.onclick = () => { onToggle(v); render(); };
    row.append(c);
  }
  host.append(row);
}

const toggle = (arr, v) => {
  const i = arr.indexOf(v);
  if (i === -1) arr.push(v); else arr.splice(i, 1);
};

function renderChips() {
  const host = $("chips");
  host.innerHTML = "";
  const vals = chipValues(books);
  if (vals.libraries.length > 1)
    chipRow(host, "Library", vals.libraries, sel.library ? [sel.library] : [],
            v => { sel.library = sel.library === v ? "" : v; });
  chipRow(host, "Genre", vals.genres, sel.genres, v => toggle(sel.genres, v));
  chipRow(host, "Tags", vals.tags, sel.tags, v => toggle(sel.tags, v));
  chipRow(host, "Reading list", vals.readinglists, sel.readinglist,
          v => toggle(sel.readinglist, v));
}

function renderList() {
  const list = $("list");
  list.innerHTML = "";
  const q = $("q").value.trim();
  const shown = sortBooks(books.filter(b => matches(b, sel, q)),
                          $("sortSel").value);
  for (const b of shown) {
    const li = document.createElement("li");
    const tr = document.createElement("div");
    tr.className = "titlerow";
    const t = document.createElement("span");
    t.className = "t"; t.textContent = b.title || b.file;
    const ser = document.createElement("span");
    ser.className = "ser"; ser.textContent = seriesText(b);
    tr.append(t, ser);
    const au = document.createElement("div");
    au.className = "authors"; au.textContent = (b.authors || []).join(", ");
    const meta = document.createElement("div");
    meta.className = "meta";
    const g = document.createElement("span");
    g.className = "genres"; g.textContent = (b.genres || []).join(" · ");
    const tg = document.createElement("span");
    tg.className = "tags"; tg.textContent = (b.tags || []).join(" · ");
    meta.append(g, tg);
    li.append(tr, au, meta);
    li.onclick = () => openBook(b);
    list.append(li);
  }
  $("count").textContent = shown.length + " of " + books.length + " downloaded";
}

function render() { renderChips(); renderList(); }

const retry = () => location.replace(SERVER + "/ui/");

async function init() {
  $("btnRetry").onclick = retry;

  const cat = await loadCatalog();
  if (cat.books) {
    books = cat.books;
    $("statusText").textContent =
      "Server unreachable — showing the books on this device. " +
      "Check that the PC is on and Tailscale is connected.";
    $("main").classList.remove("plain");   // top-flow layout for the list
    $("library").hidden = false;
    $("q").oninput = renderList;
    $("sortSel").onchange = renderList;
    render();
  } else {
    $("statusText").textContent += " Offline library: " + cat.error + ".";
  }

  // When the server comes back, walk straight back into the real UI.
  setInterval(async () => { if (await serverUp()) retry(); }, 20000);
}

// Last, so every const above it is initialised. Node (the tests) has no
// document and only imports the pure helpers.
if (typeof document !== "undefined") init();
