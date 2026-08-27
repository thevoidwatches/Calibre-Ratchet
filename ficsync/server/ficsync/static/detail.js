// Book detail: metadata chip editors + audit events.
"use strict";
import { $, state, api, apiJson, err, clearErr, show, isWritable } from "./core.js";
import { seriesLabel } from "./format.js";
import { loadCats, loadCatItems } from "./picker.js";
import { play } from "./sfx.js";
import { setUpdateAvailable } from "./actions.js";

// Category display name for a field ("#genre" -> "Genre"), so the chip
// editors reuse the vocabulary the filter picker already loads.
function catNameFor(field) {
  for (const [name, cat] of Object.entries(state.cats || {}))
    if (cat.lookup === field) return name;
  return field;
}

async function showCover(id) {
  const img = $("dCover");
  img.hidden = true;
  img.removeAttribute("src");
  try {
    // Fetched rather than set as a src, because the cover endpoint needs the
    // auth header that a plain <img src> cannot send.
    const blob = await (await api("/books/" + id + "/cover?sz=160x213")).blob();
    if (state.bookId !== id) return;        // a different book opened meanwhile
    img.src = URL.createObjectURL(blob);
    img.hidden = false;
  } catch (e) { /* no cover is not an error */ }
}

export async function openBook(id, push = true) {
  clearErr();
  state.bookId = id;
  setUpdateAvailable(false);   // a Check on the previous book says nothing here
  $("decision").hidden = true;
  $("dFields").innerHTML = ""; $("dEvents").innerHTML = "";
  try {
    const data = await apiJson("/books/" + id);
    const m = data.calibre || {};
    state.bookMeta = m;          // the epub download names the file from this
    $("dTitle").textContent = m.title || ("book " + id);
    const series = seriesLabel(m);
    $("dSeries").textContent = series;
    $("dSeries").hidden = !series;
    $("dAuthors").textContent = (m.authors || []).join(", ");
    show("detail", push);
    // The entry needs the book id so popstate can reopen this exact book.
    if (push) history.replaceState({view: "detail", bookId: id}, "");
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

// Editing order, most-used first. Anything writable but unlisted keeps its
// natural order after these. Built per call, not once at module load, because
// the genre field arrives from /ui-config after this module is evaluated.
const fieldOrder = () => [state.genreField, "tags", "#readinglist"];

function editableColumns(meta) {
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
  const order = fieldOrder();
  const rank = f => {
    const i = order.indexOf(f);
    return i === -1 ? order.length : i;
  };
  return cols.sort((a, b) => rank(a.field) - rank(b.field));
}

async function saveField(field, value) {
  const body = {changes: {}};
  body.changes[field] = value;
  await apiJson("/books/" + state.bookId + "/fields", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  });
  // Re-fetch so the chips always show calibre's actual state.
  const data = await apiJson("/books/" + state.bookId);
  $("dFields").innerHTML = "";
  // A tag added here is new vocabulary; drop the cache so it autocompletes next time.
  state.catItems = {};
  renderEditors(data.calibre || {});
  play("success");
}

// Which editors start open before this device has an opinion. Reading list is
// the one changed most often after finishing a book; genre and tags are set
// once and rarely revisited.
const DEFAULT_OPEN = new Set(["#readinglist"]);
const openKey = field => "ficsync_field_open_" + field;

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

function renderEditors(meta) {
  const host = $("dFields");
  for (const col of editableColumns(meta)) {
    // <details> rather than a button: open/close works without script, and
    // keyboard and screen-reader behaviour come for free.
    const fs = document.createElement("details");
    fs.className = "fieldset";
    fs.open = fieldIsOpen(col.field);

    const head = document.createElement("summary");
    const label = document.createElement("span");
    label.className = "flabel";
    label.textContent = col.label;
    const current = document.createElement("span");
    current.className = "fvalue muted small";
    current.textContent = summaryOf(col);
    head.append(label, current);
    fs.append(head);

    if (col.multi) renderMultiEditor(fs, col);
    else renderSingleEditor(fs, col);
    host.append(fs);

    // Attached after the initial state is set, so opening this book does not
    // record a preference the reader never expressed.
    fs.addEventListener("toggle", () =>
      localStorage.setItem(openKey(col.field), fs.open ? "1" : "0"));
  }
}

function renderMultiEditor(fs, col) {
  const cur = col.value.slice();
  for (const v of cur) {
    const c = document.createElement("span"); c.className = "chip on";
    c.append(v);
    const x = document.createElement("button"); x.textContent = "×";
    x.onclick = () => saveField(col.field, cur.filter(t => t !== v))
      .catch(e => { err("save failed — " + e.message); play("error"); });
    c.append(x); fs.append(c);
  }
  const row = document.createElement("div"); row.className = "row";
  const inp = document.createElement("input"); inp.type = "text";
  inp.placeholder = "add…";
  const dlId = "dl-" + col.field.replace(/\W/g, "_");
  inp.setAttribute("list", dlId);
  const dl = document.createElement("datalist"); dl.id = dlId;
  loadCats().then(() => loadCatItems(col.catName)).then(items => {
    for (const n of items) {
      const o = document.createElement("option"); o.value = n; dl.append(o);
    }
  });
  const add = document.createElement("button"); add.className = "small";
  add.textContent = "add";
  add.onclick = () => {
    const v = inp.value.trim();
    if (v && !cur.includes(v))
      saveField(col.field, cur.concat([v]))
        .catch(e => { err("save failed — " + e.message); play("error"); });
  };
  row.append(inp, dl, add); fs.append(row);
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
          .catch(e => { err("save failed — " + e.message); play("error"); });
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
