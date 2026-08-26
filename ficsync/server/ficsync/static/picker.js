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
import { renderFilterChips, search } from "./browse.js";
import { wouldCycle } from "./query.js";

// Pseudo-column in the picker listing the saved sets themselves.
const PRESET_COL = "Saved sets";

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

async function pickValue(colName) {
  state.pickingCol = colName;
  $("pickValTitle").textContent = colName;
  $("freeValue").value = "";
  $("valTree").innerHTML = "loading…";
  show("pickval");
  const items = await loadCatItems(colName);
  renderValTree(items, isHierarchical(colName));
}

/** Choose a saved set to drop in as a single atom. */
function pickPreset() {
  state.pickingCol = PRESET_COL;
  $("pickValTitle").textContent = PRESET_COL;
  $("freeValue").value = "";
  const box = $("valTree");
  box.innerHTML = "";
  const ul = document.createElement("ul"); ul.className = "tree";
  for (const f of state.savedFilters || []) {
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
          "make the two refer to each other.");
      show("browse");
      return;
    }
  }
  addAtom({preset: name, exclude: currentMode()});
}

function currentMode() {
  return document.querySelector('input[name="mode"]:checked').value === "exclude";
}

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

function renderValTree(items, hierarchical) {
  const box = $("valTree"); box.innerHTML = "";
  if (!items.length) { box.textContent = "no values readable — type one above"; return; }
  if (!hierarchical) {
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
    for (const [path, child] of Object.entries(node.children || {})) {
      const li = document.createElement("li");
      const a = document.createElement("span"); a.className = "node chip";
      a.textContent = child.label;
      a.onclick = () => addFilter(path);
      li.append(a);
      if (child.children) li.append(build(child));
      ul.append(li);
    }
    return ul;
  };
  box.append(build(root));
}
