// Check / Update / epub download + decision rendering.
"use strict";
import { $, state, api, apiJson, err, clearErr } from "./core.js";
import { epubFilename, progressLabel } from "./format.js";
import { inShell, statBook, saveBookToDevice, deleteBookFromDevice,
         deviceCopyIsStale, openBookInReader } from "./storage.js";
import { play, playForDecision } from "./sfx.js";

/** The Update button is only emphasised once a Check has actually found new
 *  chapters — otherwise it is the loudest thing on a page where there may be
 *  nothing to do. */
export function setUpdateAvailable(available) {
  state.updateAvailable = available;
  $("btnUpdate").classList.toggle("primary", available);
}

// What the busy box shows, one line each. Page-bound operations (check,
// update, convert, delete, open) lock the buttons on every page while they
// run, as they always have; downloads lock only their own book's, so other
// books can be fetched or read meanwhile. Both are keyed by book: the box
// sits on every book's page and stays up while the user browses on, so a
// line names its book whenever the open page is another's, and one thing
// finishing never clears another's line.
const operations = new Map();     // id -> {id, title, text}
const downloads = new Map();      // id -> {id, title, bytes, total}

/** "“Title” " when the open page is not book `id`'s own; "" when it is. */
function whose(id, title) {
  if (state.bookId === id) return "";
  return "“" + (title || "book " + id) + "” ";
}

/** Redraw the busy box from what is in flight, and lock or free the open
 *  page's buttons accordingly. */
function renderBusy() {
  const box = $("busy");
  box.replaceChildren();
  const line = (text, bytes, total) => {
    const row = document.createElement("div");
    row.className = "busyline";
    const span = document.createElement("span");
    span.textContent = text;
    row.append(span);
    if (total) {
      const bar = document.createElement("progress");
      bar.max = total;
      bar.value = Math.min(bytes, total);
      row.append(bar);
    }
    box.append(row);
  };
  for (const o of operations.values()) line(whose(o.id, o.title) + o.text);
  for (const d of downloads.values()) {
    const text = "downloading " + whose(d.id, d.title) + "to this device…";
    line(d.bytes || d.total ? text + " " + progressLabel(d.bytes, d.total) : text,
         d.bytes, d.total);
  }
  box.hidden = !box.childElementCount;
  const locked = operations.size > 0 || downloads.has(state.bookId);
  for (const id of ["btnRead", "btnCheck", "btnUpdate", "btnConvert", "btnEpub"])
    $(id).disabled = locked;
}

/** Show `text` for a page-bound operation on book `id`; call the returned
 *  function when it ends. */
function busy(id, title, text) {
  operations.set(id, {id, title, text});
  renderBusy();
  return () => { operations.delete(id); renderBusy(); };
}

/** Fetch book `id` to the device, its line in the busy box following along. */
async function downloadToDevice(id, meta) {
  const d = {id, title: meta.title, bytes: 0, total: 0};
  downloads.set(id, d);
  renderBusy();
  try {
    await saveBookToDevice(meta, (bytes, total) => {
      d.bytes = bytes;
      d.total = total;
      renderBusy();
    });
  } finally {
    downloads.delete(id);
    renderBusy();
  }
}

/** Set the action buttons up for the open book: Check/Update or Convert per
 *  the server's story-state, Read only in the shell, and Get doubling as
 *  Delete while a device copy exists. */
export async function refreshActions() {
  const meta = state.bookMeta || {};
  // A page opened while things are in flight: relabel the box for this page
  // and apply its lock at once, rather than at the next progress event —
  // which a stalled download never sends.
  renderBusy();
  // Hidden until the server says which mode this book is in: FFF-managed
  // (Check/Update), site-sourced but not FFF-made (Convert), or neither.
  // The epub itself is the authority — no metadata column involved.
  $("btnCheck").hidden = $("btnUpdate").hidden = $("btnConvert").hidden = true;
  loadStoryState();
  const shell = inShell();
  $("btnRead").hidden = !shell;
  if (!shell) { $("btnEpub").textContent = "Get"; return; }
  $("btnEpub").textContent = (await statBook(meta)) ? "Delete" : "Get";
}

async function loadStoryState() {
  const id = state.bookId;
  try {
    const st = await apiJson("/books/" + id + "/story-state");
    if (state.bookId !== id) return;      // a different book opened meanwhile
    // site_blocked: the book's site is on the server's temporary blocklist
    // (outage, FFF breakage) — no site actions offered while it lasts.
    $("btnCheck").hidden = $("btnUpdate").hidden = !st.fff_managed || st.site_blocked;
    $("btnConvert").hidden = !st.convertible || st.site_blocked;
  } catch (e) {
    // A 404 just means the book has no epub — nothing to offer, no noise.
    if (state.bookId === id && !String(e.message).startsWith("404"))
      err("could not read story state — " + e.message);
  }
}

function renderDecision(d) {
  const box = $("decision"); box.hidden = false; box.innerHTML = "";
  const head = document.createElement("div");
  head.className = d.action && d.action.startsWith("refuse") ? "warn" : "box";
  const lines = [];
  if (d.updated === true)
    lines.push("✓ UPDATED — now " + d.final_chapter_count + " chapters");
  if (d.updated === false && d.dry_run) lines.push("(dry run — nothing written)");
  lines.push("decision: " + d.action);
  lines.push("local " + d.local_count + " / site " + d.remote_count + " chapters");
  for (const r of d.reasons || []) lines.push(r);
  head.textContent = lines.join("\n");
  head.style.whiteSpace = "pre-wrap";
  box.append(head);
  const list = (title, chapters) => {
    if (!chapters || !chapters.length) return;
    const el = document.createElement("div"); el.className = "box";
    const h = document.createElement("b"); h.textContent = title; el.append(h);
    const ul = document.createElement("ul"); ul.className = "small";
    for (const c of chapters) {
      const li = document.createElement("li"); li.textContent = c.title || c.key;
      ul.append(li);
    }
    el.append(ul); box.append(el);
  };
  list("⚠ chapters that would be LOST (" + (d.missing_chapters || []).length + ")",
       d.missing_chapters);
  list("new chapters (" + (d.new_chapters || []).length + ")", d.new_chapters);
  if (d.backup) {
    const p = document.createElement("div"); p.className = "small muted";
    p.textContent = "backup: " + d.backup; box.append(p);
  }
}

$("btnCheck").onclick = async () => {
  clearErr();
  const id = state.bookId, meta = state.bookMeta || {};
  const done = busy(id, meta.title, "checking against the site…");
  try {
    const d = await apiJson("/books/" + id + "/check", {method: "POST"});
    renderDecision(d);
    setUpdateAvailable(d.action === "update");
    // A check writes nothing, so "up to date" is just the tap that asked. The
    // two answers worth hearing are a refusal and new chapters waiting.
    playForDecision(d);
    if (d.action === "update") play("success");
  }
  catch (e) { err(whose(id, meta.title) + "check failed — " + e.message); }
  finally { done(); }
};

$("btnUpdate").onclick = async () => {
  if (!confirm("Fetch new chapters and update this epub in calibre?")) return;
  clearErr();
  const id = state.bookId, meta = state.bookMeta || {};
  const done = busy(id, meta.title,
                    "updating — big serials can take minutes; leave this page open…");
  try {
    const d = await apiJson("/books/" + id + "/update", {method: "POST"});
    renderDecision(d);
    setUpdateAvailable(false);   // whatever was pending has now been applied
    playForDecision(d);
  }
  catch (e) { err(whose(id, meta.title) + "update failed — " + e.message); }
  finally { done(); }
};

/** Save the epub, letting the browser choose a destination folder where it can.
 *
 *  Chromium on the DESKTOP exposes showSaveFilePicker, and remembers the last
 *  directory used for a given `id`, so picking a folder once makes every later
 *  save land there. Android Chrome does not implement it at all — there the
 *  only fallback is a normal download into the browser's download directory,
 *  which the page cannot influence. (Chrome's own "Ask where to save files"
 *  setting adds a per-download folder prompt; a site cannot turn it on.)
 */
async function saveEpub(blob, filename) {
  if (window.showSaveFilePicker) {
    const handle = await window.showSaveFilePicker({
      suggestedName: filename,
      id: "ratchet-epub",        // Chrome ties a remembered folder to this
      startIn: "downloads",
      types: [{description: "EPUB", accept: {"application/epub+zip": [".epub"]}}],
    });
    const writable = await handle.createWritable();
    await writable.write(blob);
    await writable.close();
    return;
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.append(a); a.click(); a.remove();
  URL.revokeObjectURL(a.href);
}

/** One tap from list to reading: make sure the device copy is current, then
 *  hand it to Moon+. Downloads only when calibre's copy is newer or the file
 *  is missing — the same path every time, so Moon+ keeps its position. */
$("btnRead").onclick = async () => {
  clearErr();
  const id = state.bookId, meta = state.bookMeta;
  try {
    if (await deviceCopyIsStale(meta)) {
      await downloadToDevice(id, meta);
      await refreshActions();
    }
    const done = busy(id, meta.title, "opening…");
    try { await openBookInReader(meta); }
    finally { done(); }
    play("success");      // handed to the reader
  } catch (e) {
    err(whose(id, meta.title) + "could not open — " + e.message);
  }
};

$("btnConvert").onclick = async () => {
  if (!confirm(
      "Replace this book with a fresh download from the site?\n\n" +
      "The current file is backed up on the server, but this first conversion " +
      "cannot check for chapters the author may have deleted. Afterwards the " +
      "book is fully managed and protected.")) return;
  clearErr();
  const id = state.bookId, meta = state.bookMeta || {};
  const done = busy(id, meta.title,
                    "downloading a fresh copy from the site — this can take minutes…");
  try {
    const d = await apiJson("/books/" + id + "/convert", {method: "POST"});
    const box = $("decision"); box.hidden = false;
    box.innerHTML = "";
    const head = document.createElement("div");
    head.className = "box";
    head.style.whiteSpace = "pre-wrap";
    head.textContent = "✓ CONVERTED — now FanFicFare-managed, " +
      d.chapter_count + " chapters\nbackup: " + d.backup;
    box.append(head);
    play("success");
    refreshActions();     // Check/Update take this button's place
  } catch (e) { err(whose(id, meta.title) + "convert failed — " + e.message); }
  finally { done(); }
};

$("btnEpub").onclick = async () => {
  clearErr();
  const id = state.bookId;
  const meta = state.bookMeta || {id};
  // In the shell this button manages the device copy: fetch it when absent,
  // delete it when present (re-fetching is then one more tap).
  if (inShell()) {
    try {
      if (await statBook(meta)) {
        if (!confirm("Delete this book's file from the device?")) return;
        const done = busy(id, meta.title, "deleting…");
        try { await deleteBookFromDevice(meta); }
        finally { done(); }
      } else {
        await downloadToDevice(id, meta);
      }
      await refreshActions();
      play("success");
    } catch (e) { err(whose(id, meta.title) + "failed — " + e.message); }
    return;
  }
  const done = busy(id, meta.title, "downloading epub…");
  try {
    const blob = await (await api("/books/" + id + "/epub")).blob();
    await saveEpub(blob, epubFilename(meta));
    play("success");
  } catch (e) {
    // Dismissing the folder picker is a choice, not a failure.
    if (e && e.name === "AbortError") return;
    err("download failed — " + e.message);
  }
  finally { done(); }
};
