// Book detail: metadata chip editors + audit events.
"use strict";
import { $, state, api, apiJson, err, clearErr, show, isWritable,
         FILTER_BY_EVENT } from "./core.js";
import { groupSuggestions, seriesLabel, suggestValues } from "./format.js";
import { fieldIsHierarchical, loadCats, loadCatItems } from "./picker.js";
import { play } from "./sfx.js";
import { refreshActions, setUpdateAvailable } from "./actions.js";
import { refreshOpenBook } from "./catalog.js";
import { openExternal } from "./storage.js";

// Category display name for a field ("#genre" -> "Genre"), so the chip
// editors reuse the vocabulary the filter picker already loads.
function catNameFor(field) {
  for (const [name, cat] of Object.entries(state.cats || {}))
    if (cat.lookup === field) return name;
  return field;
}

// The size asked for when the cover is opened full-screen. calibre scales
// server-side, so this costs one request rather than shipping the original.
const COVER_LARGE = "1000x1500";

async function showCover(id) {
  const img = $("dCover");
  img.hidden = true;
  img.removeAttribute("src");
  closeCover();
  try {
    // Fetched rather than set as a src, because the cover endpoint needs the
    // auth header that a plain <img src> cannot send.
    const blob = await (await api("/books/" + id + "/cover?sz=160x213")).blob();
    if (state.bookId !== id) return;        // a different book opened meanwhile
    img.src = URL.createObjectURL(blob);
    img.hidden = false;
  } catch (e) { /* no cover is not an error */ }
}

function closeCover() {
  const pop = $("coverPop");
  if (pop.hidden) return false;
  pop.hidden = true;
  const big = $("coverPopImg");
  // Release the object URL rather than leaking one per cover opened.
  if (big.src.startsWith("blob:")) URL.revokeObjectURL(big.src);
  big.removeAttribute("src");
  play("select");
  return true;
}

/** The cover at full size. Fetched at a larger scale rather than stretching
 *  the 160px thumbnail, which on a phone screen is mostly artefacts. */
async function openCover() {
  const id = state.bookId;
  if (!id || $("dCover").hidden) return;
  const pop = $("coverPop");
  const big = $("coverPopImg");
  try {
    const blob = await (await api(
      "/books/" + id + "/cover?sz=" + COVER_LARGE)).blob();
    if (state.bookId !== id) return;
    big.src = URL.createObjectURL(blob);
    pop.hidden = false;
    // Its own history entry, so the phone's back button closes the overlay
    // instead of leaving the book underneath it — and the sound of a move,
    // for the same reason.
    history.pushState({view: "cover"}, "");
    play("select");
  } catch (e) { /* the thumbnail is already on screen; nothing more to say */ }
}

$("dCover").addEventListener("click", openCover);
$("dCover").addEventListener("keydown", e => {
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openCover(); }
});
$("coverPop").addEventListener("click", () => {
  if (closeCover()) history.back();
});
// Escape on a keyboard, and the system back button on the phone, both close
// the overlay rather than leaving the page underneath it.
window.addEventListener("keydown", e => {
  if (e.key === "Escape" && closeCover()) history.back();
});
export { closeCover };

/** A piece of metadata that doubles as a way to find its siblings: tapping it
 *  filters the book list by that value. The label can differ from the value —
 *  a series reads "Beware of Chicken #2" but filters on the series alone. */
function filterLink(field, value, label) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "gofilter";
  b.textContent = label === undefined ? value : label;
  b.title = "show everything with " + field.replace(/^#/, "") + ": " + value;
  b.onclick = () => window.dispatchEvent(new CustomEvent(FILTER_BY_EVENT, {
    detail: {field, value, hierarchical: fieldIsHierarchical(field)},
  }));
  return b;
}

/** The heading block (title, series, authors) — shared by opening a book and
 *  re-rendering after a save, so a title edit shows up everywhere at once. */
function renderHead(m) {
  state.bookMeta = m;          // the epub download names the file from this
  $("dTitle").textContent = m.title || ("book " + state.bookId);
  $("btnEditTitle").hidden = !isWritable("title");

  const series = seriesLabel(m);
  $("dSeries").innerHTML = "";
  $("dSeries").hidden = !series;
  // The index is in the label but not the filter: the point of tapping it is
  // to find the other volumes, not this one again.
  if (series) $("dSeries").append(filterLink("series", m.series, series));

  const authors = $("dAuthors");
  authors.innerHTML = "";
  (m.authors || []).forEach((name, i) => {
    if (i) authors.append(", ");
    authors.append(filterLink("authors", name));
  });
}

/** Pencil beside the title — exists mostly to excise the tag lists Royal
 *  Road authors pack into titles ("Story Name (Progression, LitRPG)"). */
$("btnEditTitle").onclick = () => {
  const cur = (state.bookMeta || {}).title || "";
  const v = prompt("Title:", cur);
  if (v === null) return;
  const t = v.trim();
  if (!t || t === cur) return;
  saveField("title", t)
    .catch(e => err("save failed — " + e.message));
};

export async function openBook(id, push = true) {
  clearErr();
  state.bookId = id;
  setUpdateAvailable(false);   // a Check on the previous book says nothing here
  $("decision").hidden = true;
  $("dFields").innerHTML = ""; $("dEvents").innerHTML = "";
  try {
    const data = await apiJson("/books/" + id);
    const m = data.calibre || {};
    renderHead(m);
    show("detail", push);
    // The entry needs the book id so popstate can reopen this exact book.
    if (push) history.replaceState({view: "detail", bookId: id}, "");
    refreshActions();
    showCover(id);
    await loadCats();          // catNameFor needs the category map
    renderEditors(m);
    renderEvents(data.events || []);
  } catch (e) { err("could not load book — " + e.message); }
}

function renderEvents(events) {
  if (!events.length) return;
  const box = $("dEvents");
  const h = document.createElement("h3"); h.textContent = "recent events";
  box.append(h);
  const ul = document.createElement("ul"); ul.className = "list small";
  for (const ev of events.slice(0, 6)) {
    const li = document.createElement("li");
    li.textContent = ev.ts + "  " + ev.kind;
    ul.append(li);
  }
  box.append(ul);
}

// Editing order, and with calibre.editable_fields set, which columns get an
// editor at all. Built per call rather than once at module load, because both
// it and the genre field arrive from /ui-config after this module is
// evaluated. The built-in list is the fallback for an unconfigured install:
// Fandom (the Fanfiction library's column) leads, and anything writable but
// unlisted keeps its natural order after these.
// calibre's lookup name for the description. It has no editor — it is the
// site's own HTML, shown read-only — but it takes a place in the configured
// order like any other field, so a column can be put below it.
const DESCRIPTION_FIELD = "comments";
const DEFAULT_ORDER = () => ["#fandom", state.genreField, "tags", "#readinglist"];
const fieldOrder = () =>
  (state.editable || []).length ? state.editable : DEFAULT_ORDER();

export function editableColumns(meta) {
  // tags is a builtin multi-value field; custom columns come from
  // user_metadata with their datatype + is_multiple flags.
  const cols = [];
  if (isWritable("tags"))
    cols.push({field: "tags", label: "Tags", multi: true,
               value: meta.tags || [], catName: catNameFor("tags")});
  const um = meta.user_metadata || {};
  for (const [field, info] of Object.entries(um)) {
    if (!isWritable(field)) continue;
    const dt = info.datatype;
    if (dt !== "text" && dt !== "enumeration") continue;  // the actual use cases
    const multi = !!info.is_multiple &&
      (typeof info.is_multiple !== "object" || Object.keys(info.is_multiple).length > 0);
    let value = info["#value#"];
    if (multi) value = Array.isArray(value) ? value : (value ? [value] : []);
    const enumVals = (info.display || {}).enum_values || null;
    cols.push({field, label: info.name || field, multi, value,
               enumVals, catName: catNameFor(field)});
  }
  // Last in this list, so an install that has not configured an order still
  // shows the description after the editors, where it has always been.
  if ((meta.comments || "").trim())
    cols.push({field: DESCRIPTION_FIELD, label: "Description", description: true});
  const order = fieldOrder();
  // Configured explicitly: the list is the whole selection, so a writable
  // column left out of it gets no editor. Unconfigured: the list only ranks,
  // and everything writable is still offered.
  const chosen = (state.editable || []).length
    ? cols.filter(c => order.includes(c.field)) : cols;
  const rank = f => {
    const i = order.indexOf(f);
    return i === -1 ? order.length : i;
  };
  return chosen.sort((a, b) => rank(a.field) - rank(b.field));
}

async function saveField(field, value) {
  const body = {changes: {}};
  body.changes[field] = value;
  await apiJson("/books/" + state.bookId + "/fields", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  });
  // Re-fetch so the page always shows calibre's actual state — including the
  // heading, which a title edit changes.
  const data = await apiJson("/books/" + state.bookId);
  const m = data.calibre || {};
  renderHead(m);
  $("dFields").innerHTML = "";
  // A tag added here is new vocabulary; drop the cache so it autocompletes next time.
  state.catItems = {};
  renderEditors(m);
  // Shell only: keep the offline catalog's copy of this book current too.
  refreshOpenBook(m).catch(() => {});
  play("success");
}

// Enough to browse without becoming a wall on a phone; past this, filtering
// is the faster route anyway and the box says so.
const MAX_SUGGESTIONS = 60;

// Which editors start open before this device has an opinion. Reading list is
// the one changed most often after finishing a book; genre and tags are set
// once and rarely revisited.
const DEFAULT_OPEN = new Set(["#readinglist"]);
const openKey = field => "ratchet_field_open_" + field;

export function fieldIsOpen(field) {
  const stored = localStorage.getItem(openKey(field));
  if (stored === "1") return true;
  if (stored === "0") return false;
  return DEFAULT_OPEN.has(field);
}

/** What the section shows when it is closed, so a collapsed field still tells
 *  you what it is set to. */
function summaryOf(col) {
  const v = col.multi ? (col.value || []).join(" · ") : (col.value || "");
  return v || "—";
}

/** A collapsible section shell shared by every field on the page, wired to
 *  the per-device open-state store. <details> rather than a button:
 *  open/close works without script, and keyboard and screen-reader behaviour
 *  come for free. The toggle listener is attached after the initial state is
 *  set, so opening a book does not record a preference the reader never
 *  expressed. */
function fieldShell(key, label, summaryValue) {
  const fs = document.createElement("details");
  fs.className = "fieldset";
  fs.open = fieldIsOpen(key);
  const head = document.createElement("summary");
  const lab = document.createElement("span");
  lab.className = "flabel";
  lab.textContent = label;
  const current = document.createElement("span");
  current.className = "fvalue muted small";
  current.textContent = summaryValue;
  head.append(lab, current);
  fs.append(head);
  fs.addEventListener("toggle", () =>
    localStorage.setItem(openKey(key), fs.open ? "1" : "0"));
  return fs;
}

/** calibre's comments field is site-authored HTML; keep the formatting but
 *  strip anything active before it goes into the DOM. */
function sanitizedDescription(html) {
  const doc = new DOMParser().parseFromString(html, "text/html");
  for (const el of doc.querySelectorAll(
      "script, style, iframe, object, embed, link, meta"))
    el.remove();
  for (const el of doc.body.querySelectorAll("*")) {
    for (const attr of [...el.attributes]) {
      const n = attr.name.toLowerCase();
      if (n.startsWith("on") ||
          ((n === "href" || n === "src") && /^\s*javascript:/i.test(attr.value)))
        el.removeAttribute(attr.name);
    }
  }
  return doc.body.innerHTML;
}

function renderDescription(host, meta) {
  const html = (meta.comments || "").trim();
  if (!html) return;
  const fs = fieldShell("description", "Description", "");
  const body = document.createElement("div");
  body.className = "desc";
  body.innerHTML = sanitizedDescription(html);
  // Links in a description would navigate the whole app (fatal in the shell,
  // where this page IS the app) — send them to the system browser instead.
  body.addEventListener("click", e => {
    const a = e.target.closest("a");
    if (!a || !a.href) return;
    e.preventDefault();
    play("select");       // leaving for the browser is a move like any other
    openExternal(a.href);
  });
  fs.append(body);
  host.append(fs);
}

function renderEditors(meta) {
  const host = $("dFields");
  for (const col of editableColumns(meta)) {
    if (col.description) { renderDescription(host, meta); continue; }
    const fs = fieldShell(col.field, col.label, summaryOf(col));
    if (col.multi) renderMultiEditor(fs, col);
    else renderSingleEditor(fs, col);
    host.append(fs);
  }
}

function renderMultiEditor(fs, col) {
  const cur = col.value.slice();
  for (const v of cur) {
    const c = document.createElement("span"); c.className = "chip on";
    // Two buttons rather than a clickable chip with a nested ×: each has one
    // job, neither has to cancel the other's event, and both are reachable
    // from a keyboard.
    c.append(filterLink(col.field, v));
    const x = document.createElement("button");
    x.type = "button";
    x.className = "chipx";
    x.textContent = "×";
    x.title = "remove";
    x.onclick = () => saveField(col.field, cur.filter(t => t !== v))
      .catch(e => err("save failed — " + e.message));
    c.append(x); fs.append(c);
  }
  const addValue = v => {
    if (!v || cur.includes(v)) return;
    saveField(col.field, cur.concat([v]))
      .catch(e => err("save failed — " + e.message));
  };

  // One box that both filters and creates. The <datalist> this replaces was
  // the obvious HTML for it, but Android WebViews barely implement it, and
  // where they do it only appears once enough has been typed to narrow the
  // list — no help when the question is "what genres do I already use?".
  // Built from ordinary elements instead, so it behaves the same everywhere.
  const row = document.createElement("div"); row.className = "row";
  const inp = document.createElement("input"); inp.type = "text";
  inp.placeholder = "filter, or type a new one…";
  const add = document.createElement("button"); add.className = "small";
  add.textContent = "add";
  add.onclick = () => addValue(inp.value.trim());
  row.append(inp, add); fs.append(row);

  const box = document.createElement("div");
  box.className = "suggestbox";
  box.hidden = true;
  fs.append(box);

  const chip = (value, label) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip suggestion";
    b.textContent = label;
    b.title = value;             // the full path, when the label is trimmed
    // Keep the press from moving focus out of the filter box, which would
    // hide this list before the click landed on it.
    b.addEventListener("mousedown", e => e.preventDefault());
    b.onclick = () => addValue(value);
    return b;
  };

  let vocabulary = [];
  function renderSuggestions() {
    const q = inp.value.trim().toLowerCase();
    const matches = vocabulary.filter(v => v.toLowerCase().includes(q));
    box.innerHTML = "";
    // Only while the matching box has focus: several of these sections can be
    // open at once, and a page of permanently expanded lists is unreadable.
    box.hidden = !matches.length || document.activeElement !== inp;
    if (box.hidden) return;
    // Unfiltered, the list is grouped by top level so a long vocabulary reads
    // as a few headed families. Once filtering, matches are shown in full:
    // the whole point is then seeing where each one sits.
    if (!q) {
      const {loose, groups} = groupSuggestions(matches.slice(0, MAX_SUGGESTIONS));
      for (const it of loose) box.append(chip(it.value, it.label));
      for (const g of groups) {
        const head = document.createElement("div");
        head.className = "suggesthead small muted";
        head.textContent = g.label;
        box.append(head);
        for (const it of g.items) box.append(chip(it.value, it.label));
      }
    } else {
      for (const v of matches.slice(0, MAX_SUGGESTIONS)) box.append(chip(v, v));
    }
    if (matches.length > MAX_SUGGESTIONS) {
      const more = document.createElement("div");
      more.className = "small muted";
      more.textContent = "+" + (matches.length - MAX_SUGGESTIONS) +
                         " more — keep typing to narrow";
      box.append(more);
    }
  }

  inp.addEventListener("input", renderSuggestions);
  inp.addEventListener("focus", renderSuggestions);
  inp.addEventListener("blur", () => { box.hidden = true; });
  loadCats().then(() => loadCatItems(col.catName)).then(items => {
    vocabulary = suggestValues(items, cur);
    renderSuggestions();     // stays hidden unless this box already has focus
  }).catch(() => { /* no vocabulary: the box still adds new values */ });
}

function renderSingleEditor(fs, col) {
  const cur = col.value || "";
  const addChip = v => {
    const c = document.createElement("span");
    c.className = "chip" + (v === cur ? " on" : "");
    c.textContent = v === "" ? "(none)" : v;
    c.onclick = () => {
      if (v !== cur)
        saveField(col.field, v === "" ? null : v)
          .catch(e => err("save failed — " + e.message));
    };
    fs.append(c);
  };
  const opts = new Set([""]);
  if (cur) opts.add(cur);
  const seed = col.enumVals ? Promise.resolve(col.enumVals)
    : loadCats().then(() => loadCatItems(col.catName));
  seed.then(items => {
    for (const n of items || []) opts.add(n);
    for (const v of opts) addChip(v);
  }).catch(() => { for (const v of opts) addChip(v); });
}
