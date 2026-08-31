// Browse view: filter chips -> calibre search query -> results list.
"use strict";
import { $, state, apiJson, err, clearErr, show, forgetBrowseScroll,
         FILTER_BY_EVENT, PICK_FILTER_EVENT } from "./core.js";
import { seriesLabel, pageLabel, rowFieldLabel, metaLine } from "./format.js";
import { buildQuery, describeFilters, isDownloadedAtom, isPresetAtom } from "./query.js";
import { openBook } from "./detail.js";
import { downloadedIds } from "./catalog.js";
import { play } from "./sfx.js";
import { readClipboard } from "./storage.js";

const COLLAPSE_KEY = "ratchet_filters_collapsed";

export function termCount() {
  return state.filterGroups.reduce((n, g) => n + g.terms.length, 0);
}

/** The filter bar: collapse toggle plus the live term count. Collapsed still
 *  reports the count, because an active filter you cannot see is a good way to
 *  be confused about why a result list looks empty. */
export function renderFilterBar() {
  const n = termCount();
  const collapsed = localStorage.getItem(COLLAPSE_KEY) === "1";
  const btn = $("btnToggleFilters");
  btn.textContent = (collapsed ? "▸" : "▾") + " Filters" + (n ? " (" + n + ")" : "");
  btn.setAttribute("aria-expanded", String(!collapsed));
  // With no filters there is nothing to collapse; hiding the empty box keeps
  // the row from taking up space.
  $("filterChips").hidden = collapsed || n === 0;
  $("queryPreview").hidden = collapsed || n === 0;
  $("btnSaveFilters").disabled = n === 0;
}

$("btnToggleFilters").onclick = () => {
  localStorage.setItem(COLLAPSE_KEY,
                       localStorage.getItem(COLLAPSE_KEY) === "1" ? "0" : "1");
  renderFilterBar();
};

/** Saved sets keyed by name, so preset atoms can be expanded. */
function presetMap() {
  return Object.fromEntries((state.savedFilters || []).map(f => [f.name, f.groups]));
}

/** Async because a Downloaded atom (here or inside a referenced preset)
 *  needs the device catalog's ids; outside the shell that is an instant []. */
export async function fullQuery() {
  return buildQuery(state.filterGroups, $("q").value,
                    {presets: presetMap(), downloadedIds: await downloadedIds()});
}

/** Groups render as boxes of ORed chips, with "and" between the boxes. Each
 *  box carries its own "+ or" so another alternative can join that group
 *  rather than starting a new AND. */
export function renderFilterChips() {
  const box = $("filterChips"); box.innerHTML = "";
  state.filterGroups.forEach((group, gi) => {
    if (gi > 0) {
      const and = document.createElement("span");
      and.className = "joiner"; and.textContent = "and";
      box.append(and);
    }
    const wrap = document.createElement("span");
    wrap.className = "fgroup";
    group.terms.forEach((t, ti) => {
      if (ti > 0) {
        const or = document.createElement("span");
        or.className = "joiner or"; or.textContent = "or";
        wrap.append(or);
      }
      const c = document.createElement("span");
      const preset = isPresetAtom(t);
      c.className = "chip" + (t.exclude ? " excl" : "") + (preset ? " preset" : "");
      // A preset shows by name — displaying its expansion would defeat the alias.
      c.append(preset ? t.preset :
               isDownloadedAtom(t) ? "Downloaded" : t.field + ": " + t.value);
      if (preset && !(state.savedFilters || []).some(f => f.name === t.preset)) {
        c.classList.add("broken");
        c.title = "this saved set no longer exists";
      }
      const x = document.createElement("button");
      x.textContent = "×";
      x.title = "remove";
      x.onclick = () => {
        group.terms.splice(ti, 1);
        // A group with nothing left in it would otherwise render as an empty box.
        if (!group.terms.length) state.filterGroups.splice(gi, 1);
        renderFilterChips();
        search();
      };
      c.append(x);
      wrap.append(c);
    });
    const add = document.createElement("button");
    add.className = "small orbtn";
    add.textContent = "+ or";
    add.title = "add an alternative to this group";
    add.onclick = () => startPicking(gi);
    wrap.append(add);
    box.append(wrap);
  });
  $("queryPreview").textContent = describeFilters(state.filterGroups);
  renderFilterBar();   // the count and the collapse state live there
}

export async function search(more = false) {
  clearErr();
  const q = await fullQuery();
  // A fresh search replaces the list, so the place kept for coming back from
  // a book no longer means anything. "more" appends, and keeps it.
  if (!more) {
    state.offset = 0;
    $("results").innerHTML = "";
    forgetBrowseScroll();
    window.scrollTo(0, 0);
  }
  try {
    const data = await apiJson("/books?q=" + encodeURIComponent(q) +
                               "&num=30&offset=" + state.offset +
                               "&sort=" + encodeURIComponent(state.sort || "") +
                               "&sort_order=" + encodeURIComponent(state.sortDir));
    for (const b of data.books) {
      const li = document.createElement("li");
      li.innerHTML = '<div class="titlerow"><span class="t"></span>' +
                     '<span class="ser"></span>' +
                     '<span class="rowfield"></span></div>' +
                     '<div class="small muted byline"><span class="who"></span>' +
                     '<span class="len"></span></div>' +
                     '<div class="meta"><span class="genres"></span>' +
                     '<span class="tags"></span></div>';
      li.querySelector(".t").textContent = b.title || ("(book " + b.id + ")");
      // Empty when the book has no series; the CSS then collapses the span.
      li.querySelector(".ser").textContent = seriesLabel(b);
      // The configured column stands in at the end of the title line for a
      // book with no series to put there. Both spans collapse when empty, so
      // only ever one of them takes up the space.
      li.querySelector(".rowfield").textContent = rowFieldLabel(b);
      li.querySelector(".who").textContent = (b.authors || []).join(", ");
      // Blank rather than "0 pages" when calibre has never counted this one;
      // the CSS collapses an empty span, so the row does not gain a gap.
      li.querySelector(".len").textContent = pageLabel(b.pages);
      const meta = li.children[2];
      meta.querySelector(".genres").textContent = metaLine(b.genre);
      meta.querySelector(".tags").textContent = metaLine(b.tags);
      li.onclick = () => openBook(b.id);
      $("results").append(li);
    }
    state.offset += data.books.length;
    $("btnMore").hidden = !(data.total > state.offset && data.books.length > 0);
  } catch (e) { err("search failed — " + e.message); }
}

/** Jump from a book to everything else like it: the clicked genre, tag,
 *  series or author becomes the only filter.
 *
 *  Replaces rather than adds, because "show me the rest of this series" means
 *  exactly that — leaving earlier filters in place would hide most of the
 *  answer, and the chips make the new state plain enough to adjust.
 */
window.addEventListener(FILTER_BY_EVENT, e => {
  const {field, value, hierarchical} = e.detail || {};
  if (!field || !value) return;
  state.filterGroups = [{terms: [{field, value, exclude: false, hierarchical}]}];
  $("q").value = "";
  renderFilterChips();
  show("browse");
  search();
});

/** Ask picker.js to open the column list. `groupIndex` null means "start a new
 *  AND group"; a number means "add an alternative to that existing group". */
function startPicking(groupIndex) {
  state.pickingGroup = groupIndex;
  window.dispatchEvent(new CustomEvent(PICK_FILTER_EVENT));
}

$("searchForm").addEventListener("submit", e => { e.preventDefault(); search(); });
$("btnMore").onclick = () => search(true);

// ---- adding stories by URL --------------------------------------------------
//
// The button never locks: each URL joins a queue and the downloads run one at
// a time (FanFicFare fetches every chapter, so parallel adds would hammer the
// site). Each entry pins the library it was queued under, so switching
// libraries mid-queue cannot re-route a pending story. A single add still
// opens the new book; a batch stays on the list and reports per URL, since
// being yanked into each book as it lands would fight the next paste.

const addQueue = [];
let addRunning = false;
let addBatchTotal = 0;   // adds in the current batch, for the single-add case

function renderAddButton() {
  const btn = $("btnAddStory");
  btn.textContent = addRunning
    ? "adding…" + (addQueue.length ? " +" + addQueue.length : "")
    : "+ Add";
}

function addStatusLine(text) {
  const box = $("addStatus");
  box.hidden = false;
  const line = document.createElement("div");
  line.textContent = text;
  box.append(line);
}

/** Queue one story for adding to the current library. Shared by the button,
 *  the clipboard pre-fill and the Android share sheet. */
export function queueAdd(url) {
  if (!url || !url.trim()) return;
  if (!addRunning) {           // a fresh batch replaces the old batch's report
    $("addStatus").innerHTML = "";
    $("addStatus").hidden = true;
    addBatchTotal = 0;
  }
  addBatchTotal += 1;
  addQueue.push({url: url.trim(), library: state.library});
  runAddQueue();
}

/** The first http(s) URL in some text — a share often arrives as "Title —
 *  https://…", and a clipboard can hold anything at all. */
export function firstUrl(text) {
  const m = String(text || "").match(/https?:\/\/\S+/);
  return m ? m[0] : "";
}

$("btnAddStory").onclick = async () => {
  // Pre-fill from the clipboard when it holds a link: the URL is almost
  // always why the reader came here, and retyping it on a phone is miserable.
  let suggested = "";
  try { suggested = firstUrl(await readClipboard()); } catch (e) { /* no clipboard */ }
  const url = prompt(
    "Story URL to add to " + (state.library || "the library") + ":\n\n" +
    "The whole story is downloaded first, which can take minutes. Downloads " +
    "finish on the server even if you close the app; you can also keep " +
    "hitting + Add — extra stories queue up.", suggested);
  if (url) queueAdd(url);
};

async function runAddQueue() {
  if (addRunning) { renderAddButton(); return; }
  addRunning = true;
  let last = null;
  while (addQueue.length) {
    const {url, library} = addQueue.shift();
    renderAddButton();
    try {
      const d = await apiJson(
        "/books/add" + (library ? "?library=" + encodeURIComponent(library) : ""), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({url}),
      });
      last = d;
      play("success");
      addStatusLine("✓ " + d.title + " — " + d.chapter_count + " chapters");
    } catch (e) {
      play("error");
      addStatusLine("✗ " + url + " — " + e.message);
    }
  }
  addRunning = false;
  renderAddButton();
  if (addBatchTotal === 1 && last) openBook(last.book_id);
  else if (last) search();     // the list should show what just landed
}
