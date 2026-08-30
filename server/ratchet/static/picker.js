// Filter pickers: column list, per-column value tree, category vocab loading.
//
// Shapes below were verified against calibre 9.13's /ajax/categories and
// /ajax/category/<hex>/<library>:
//
//   categories -> [{name, url, icon, is_category}, ...]
//        `is_category: false` rows ("Newest", "All books") are browse buckets,
//        not filterable columns, and are dropped.
//        The url's hex segment decodes to the real calibre lookup name, so
//        "Genre" resolves to "#genre" rather than being guessed from the label.
//
//   category  -> {items: [{name, count, has_children}], subcategories: [{url}]}
//        `items` are only the values AT THIS NODE, named relative to it, and
//        `subcategories` are child nodes whose url hex-decodes to the full
//        dotted path. A hierarchical column therefore has to be walked, not
//        read in one request: node "#genre.Science Fiction" holding item
//        "Space Opera" is the stored value "Science Fiction.Space Opera".
"use strict";
import { $, state, apiJson, err, clearErr, show, PICK_FILTER_EVENT } from "./core.js";
import { renderFilterChips, search, fullQuery } from "./browse.js";
import { wouldCycle } from "./query.js";
import { inShell } from "./storage.js";
import { visibleValues } from "./format.js";

// Pseudo-column in the picker listing the saved sets themselves.
const PRESET_COL = "Saved sets";
// Pseudo-column for the device-copy filter (shell only — a plain browser has
// no device catalog to check against).
const DOWNLOADED_COL = "Downloaded";

// Columns where "." in a value is punctuation, not hierarchy (author names
// like "R.A. Scott", series with dotted titles).
const NO_HIERARCHY = new Set(["authors", "series", "publisher", "formats",
                              "identifiers", "languages", "news", "rating"]);

const MAX_NODES = 300;    // request cap for one column's walk

function lookupFromUrl(url) {
  // /ajax/category/<hex-of-lookup>/<library>
  const hex = (url || "").split("/")[3] || "";
  try {
    const bytes = hex.match(/../g) || [];
    return new TextDecoder().decode(
      new Uint8Array(bytes.map(b => parseInt(b, 16))));
  } catch (e) { return ""; }
}

function parseCategories(resp) {
  const out = {};
  const rows = Array.isArray(resp) ? resp
    : Array.isArray(resp && resp.categories) ? resp.categories : [];
  for (const row of rows) {
    if (!row || !row.name || !row.url) continue;
    if (row.is_category === false) continue;   // "Newest", "All books"
    const lookup = lookupFromUrl(row.url) || row.name.toLowerCase();
    out[row.name] = {url: row.url, lookup};
  }
  return out;
}

export async function loadCats() {
  if (state.cats) return state.cats;
  try { state.cats = parseCategories(await apiJson("/categories")); }
  catch (e) { state.cats = {}; }
  return state.cats;
}

async function fetchNode(url) {
  const resp = await apiJson("/category-items?url=" + encodeURIComponent(url) +
                             "&num=500");
  return {
    items: Array.isArray(resp) ? resp : (resp.items || []),
    subcategories: (resp && resp.subcategories) || [],
  };
}

/** Node path relative to its column: "#genre.Science Fiction" -> "Science Fiction". */
function pathOfNode(url, lookup) {
  const full = lookupFromUrl(url);
  if (full === lookup) return "";
  return full.startsWith(lookup + ".") ? full.slice(lookup.length + 1) : "";
}

/** Every stored value of a column, as full dotted paths. */
export async function loadCatItems(name) {
  if (state.catItems[name]) return state.catItems[name];
  const cat = (state.cats || {})[name];
  const values = [];
  if (cat && cat.url) {
    const queue = [cat.url];
    const seen = new Set(queue);
    try {
      while (queue.length && seen.size <= MAX_NODES) {
        const url = queue.shift();
        const node = await fetchNode(url);
        const path = pathOfNode(url, cat.lookup);
        for (const it of node.items) {
          if (it && typeof it.name === "string")
            values.push(path ? path + "." + it.name : it.name);
        }
        for (const sub of node.subcategories) {
          if (sub && sub.url && !seen.has(sub.url)) {
            seen.add(sub.url);
            queue.push(sub.url);
          }
        }
      }
    } catch (e) { /* picker degrades to the free-type input */ }
  }
  state.catItems[name] = values;
  return values;
}

async function openColumnPicker() {
  clearErr();
  await loadCats();
  const ul = $("colList"); ul.innerHTML = "";
  const names = Object.keys(state.cats);
  if (!names.length) {
    err("could not read filterable columns from calibre (/categories parse) — use the search box with calibre syntax instead");
    return;
  }
  for (const name of names.sort()) {
    const li = document.createElement("li");
    li.textContent = name;
    li.onclick = () => pickValue(name);
    ul.append(li);
  }
  if (inShell()) {
    const li = document.createElement("li");
    li.textContent = DOWNLOADED_COL;
    li.onclick = () => pickDownloaded();
    ul.append(li);
  }
  if ((state.savedFilters || []).length) {
    const li = document.createElement("li");
    li.textContent = PRESET_COL;
    li.onclick = () => pickPreset();
    ul.append(li);
  }
  show("pickcol");
}

// The toolbar button starts a fresh AND group; the "+ or" buttons on existing
// groups come through the event with a group index already set.
$("btnAddFilter").onclick = () => { state.pickingGroup = null; openColumnPicker(); };
window.addEventListener(PICK_FILTER_EVENT, openColumnPicker);

export function lookupOf(colName) {
  const cat = (state.cats || {})[colName];
  return (cat && cat.lookup) || colName.toLowerCase();
}

export const isHierarchical = colName => !NO_HIERARCHY.has(lookupOf(colName));

/** The same question asked with a calibre lookup name ("#genre", "authors")
 *  rather than a display name, for callers that already hold the field. */
export const fieldIsHierarchical = field => !NO_HIERARCHY.has(field);

// The values of the column being picked, and whether the box above them is
// filtering them. The saved-sets and Downloaded screens reuse this view with
// their own content, so they turn filtering off.
let valItems = [];
let valHierarchical = true;
let valFiltering = false;
// The subset of those values that occurs in the books the current filters
// match, or null when the list is not narrowed: no filters are set, the
// request failed, or the reader asked for the whole vocabulary. Narrowing is
// a convenience — every value stays reachable through the free-text box.
let valPresent = null;
let valShowAll = false;

/** Which of this column's values occur in the books the current filters match.
 *  Returns null when the list should not be narrowed at all — nothing is
 *  filtered, a value is being added as an OR alternative, or calibre could
 *  not answer — in which case the full vocabulary is shown.
 *
 *  The OR case is deliberate: another alternative in an existing group is
 *  meant to bring back books the current filters exclude, so the values worth
 *  choosing are exactly the ones narrowing would hide. */
async function presentValues(colName) {
  const gi = state.pickingGroup;
  if (gi !== null && gi !== undefined) return null;
  const q = (await fullQuery()).trim();
  if (!q) return null;            // nothing filtered: the results are the library
  try {
    const resp = await apiJson("/field-values?field=" +
      encodeURIComponent(lookupOf(colName)) + "&q=" + encodeURIComponent(q));
    return new Set(resp.values || []);
  } catch (e) { return null; }
}

/** How much of the vocabulary is on screen, and the switch to the rest. */
function renderScope() {
  const line = $("valScope");
  line.innerHTML = "";
  if (!valPresent || !valFiltering) { line.hidden = true; return; }
  line.hidden = false;
  const here = valItems.filter(v => valPresent.has(v)).length;
  const msg = document.createElement("span");
  msg.textContent = valShowAll
    ? `all ${valItems.length} values`
    : `${here} of ${valItems.length} values are in these results`;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "small";
  btn.textContent = valShowAll ? "narrow to results" : "show all";
  btn.onclick = () => { valShowAll = !valShowAll; renderValTree(); };
  line.append(msg, btn);
}

async function pickValue(colName) {
  state.pickingCol = colName;
  $("pickValTitle").textContent = colName;
  $("freeValue").value = "";
  setMode(false);
  $("valTree").innerHTML = "loading…";
  show("pickval");
  const items = await loadCatItems(colName);
  if (state.pickingCol !== colName) return;   // another column opened meanwhile
  // The vocabulary arrives in the order the category tree was walked, which
  // is arbitrary to read; alphabetical is what anyone hunting a value wants.
  valItems = items.slice().sort((a, b) => a.localeCompare(b));
  valHierarchical = isHierarchical(colName);
  valFiltering = true;
  valPresent = null;
  valShowAll = false;
  renderValTree();          // the whole vocabulary, without waiting
  // Narrowing needs a sweep of the matching books' metadata, so it lands
  // after the tree is already usable rather than holding it back.
  const present = await presentValues(colName);
  if (state.pickingCol !== colName) return;
  valPresent = present;
  renderValTree();
}

/** Downloaded is device knowledge, not a calibre column: the query builder
 *  expands the atom into an id list from the offline catalog. One value,
 *  offered through the normal value screen so the Is/Not tabs apply. */
function pickDownloaded() {
  state.pickingCol = DOWNLOADED_COL;
  valFiltering = false;
  valPresent = null;
  $("valScope").hidden = true;
  $("pickValTitle").textContent = DOWNLOADED_COL;
  $("freeValue").value = "";
  setMode(false);
  const box = $("valTree");
  box.innerHTML = "";
  const ul = document.createElement("ul"); ul.className = "tree";
  const li = document.createElement("li");
  const a = document.createElement("span");
  a.className = "node chip";
  a.textContent = "on this device";
  a.onclick = () => addAtom({downloaded: true, exclude: currentMode()});
  li.append(a); ul.append(li);
  box.append(ul);
  show("pickval");
}

/** Choose a saved set to drop in as a single atom. */
function pickPreset() {
  state.pickingCol = PRESET_COL;
  valFiltering = false;
  valPresent = null;
  $("valScope").hidden = true;
  $("pickValTitle").textContent = PRESET_COL;
  $("freeValue").value = "";
  setMode(false);
  const box = $("valTree");
  box.innerHTML = "";
  const ul = document.createElement("ul"); ul.className = "tree";
  const sets = (state.savedFilters || []).slice()
    .sort((a, b) => a.name.localeCompare(b.name));
  for (const f of sets) {
    const li = document.createElement("li");
    const a = document.createElement("span");
    a.className = "node chip preset";
    a.textContent = f.name;
    a.onclick = () => addPresetAtom(f.name);
    li.append(a); ul.append(li);
  }
  box.append(ul);
  show("pickval");
}

function addPresetAtom(name) {
  // Editing a set that already contains this one would make the pair expand
  // into each other; the query builder stops it, but refusing up front is
  // clearer than a filter that silently matches nothing.
  const editing = $("savedFilters").value;
  if (editing) {
    const presets = Object.fromEntries(
      (state.savedFilters || []).map(f => [f.name, f.groups]));
    if (wouldCycle(presets, editing, name)) {
      err(`"${name}" already refers to "${editing}", so adding it here would ` +
          "make the two refer to each other.", "refused");
      show("browse");
      return;
    }
  }
  addAtom({preset: name, exclude: currentMode()});
}

// Which tab is active. Held in the DOM rather than a variable so the button
// state and the value used can never disagree.
function currentMode() {
  return $("tabExclude").classList.contains("on");
}

function setMode(exclude) {
  for (const [btn, isOn] of [[$("tabInclude"), !exclude], [$("tabExclude"), exclude]]) {
    btn.classList.toggle("on", isOn);
    btn.setAttribute("aria-selected", String(isOn));
  }
}

for (const id of ["tabInclude", "tabExclude"])
  $(id).onclick = () => setMode(id === "tabExclude");

function addFilter(value) {
  addAtom({field: lookupOf(state.pickingCol), value,
           exclude: currentMode(),
           hierarchical: isHierarchical(state.pickingCol)});
}

function addAtom(term) {
  const gi = state.pickingGroup;
  const group = (gi === null || gi === undefined) ? null : state.filterGroups[gi];
  if (group) group.terms.push(term);            // another alternative (OR)
  else state.filterGroups.push({terms: [term]});  // a new conjunct (AND)
  state.pickingGroup = null;
  renderFilterChips();
  show("browse");
  search();
}

$("btnFreeValue").onclick = () => {
  const v = $("freeValue").value.trim();
  if (v) addFilter(v);
};
// No form here either; Enter does what the "use" button does, through the
// button so the two never drift apart.
$("freeValue").addEventListener("keydown", e => {
  if (e.key === "Enter") $("btnFreeValue").click();
});

// The same box filters the list below it and adds a value that isn't in it —
// the arrangement the book page's editors use, so a long vocabulary is
// reachable by typing rather than only by scrolling.
$("freeValue").addEventListener("input", () => {
  if (valFiltering) renderValTree();
});

function renderValTree() {
  renderScope();
  const box = $("valTree"); box.innerHTML = "";
  if (!valItems.length) {
    box.textContent = "no values readable — type one above";
    return;
  }
  const typed = $("freeValue").value.trim();
  const q = typed.toLowerCase();
  const scoped = visibleValues(valItems, valPresent, valShowAll, "");
  const items = visibleValues(valItems, valPresent, valShowAll, typed);
  if (!items.length) {
    box.textContent = !scoped.length
      ? "none of this column's values appear in these results — “show all” " +
        "lists the rest, or type one above"
      : 'nothing matches "' + typed + '" — the button adds it as a new value';
    return;
  }
  // Flat while filtering, even for a hierarchical column: matches can come
  // from anywhere in the tree, and their full paths say where they sit
  // better than a half-pruned tree would.
  if (!valHierarchical || q) {
    const ul = document.createElement("ul"); ul.className = "tree";
    for (const n of items) {
      const li = document.createElement("li");
      const a = document.createElement("span"); a.className = "node chip";
      a.textContent = n; a.onclick = () => addFilter(n);
      li.append(a); ul.append(li);
    }
    box.append(ul); return;
  }
  // Dotted paths -> a tree. Selecting any node filters on its full path, which
  // matches that value and everything under it.
  const root = {};
  for (const n of items) {
    let cur = root;
    const parts = n.split(".");
    for (let i = 0; i < parts.length; i++) {
      const key = parts.slice(0, i + 1).join(".");
      cur.children = cur.children || {};
      cur.children[key] = cur.children[key] || {label: parts[i]};
      cur = cur.children[key];
    }
  }
  const build = node => {
    const ul = document.createElement("ul"); ul.className = "tree";
    // Sorted per level, not just overall: a parent's children are what you
    // are scanning once you have found the parent.
    const children = Object.entries(node.children || {})
      .sort(([, a], [, b]) => a.label.localeCompare(b.label));
    for (const [path, child] of children) {
      const li = document.createElement("li");

      const a = document.createElement("span"); a.className = "node chip";
      a.textContent = child.label;
      a.onclick = () => addFilter(path);
      li.append(a);

      // Families start closed, so the top level is a short list to scan.
      // A separate twist rather than wrapping the value in <summary>: the
      // value itself has to stay a filter, and one control cannot both
      // select and expand without one of the two needing to be cancelled.
      let kids = null, twist = null;
      if (child.children) {
        twist = document.createElement("button");
        twist.type = "button";
        twist.className = "twist";
        twist.textContent = "▸";
        twist.setAttribute("aria-expanded", "false");
        twist.setAttribute("aria-label", "show values under " + child.label);
        li.append(twist);
      }

      if (child.children) {
        kids = build(child);
        kids.hidden = true;
        twist.onclick = () => {
          kids.hidden = !kids.hidden;
          twist.textContent = kids.hidden ? "▸" : "▾";
          twist.setAttribute("aria-expanded", String(!kids.hidden));
        };
        li.append(kids);
      }
      ul.append(li);
    }
    return ul;
  };
  box.append(build(root));
}
