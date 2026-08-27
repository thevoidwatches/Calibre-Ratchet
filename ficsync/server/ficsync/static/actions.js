// Check / Update / epub download + decision rendering.
"use strict";
import { $, state, api, apiJson, err, clearErr } from "./core.js";
import { epubFilename } from "./format.js";
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

function busy(msg) {
  $("busy").hidden = !msg;
  $("busy").textContent = msg || "";
  for (const id of ["btnRead", "btnCheck", "btnUpdate", "btnConvert", "btnEpub"])
    $(id).disabled = !!msg;
}

/** Set the action buttons up for the open book: Check/Update or Convert per
 *  the server's story-state, Read only in the shell, and Get doubling as
 *  Delete while a device copy exists. */
export async function refreshActions() {
  const meta = state.bookMeta || {};
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
    $("btnCheck").hidden = $("btnUpdate").hidden = !st.fff_managed;
    $("btnConvert").hidden = !st.convertible;
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
  clearErr(); busy("checking against the site…");
  try {
    const d = await apiJson("/books/" + state.bookId + "/check", {method: "POST"});
    renderDecision(d);
    setUpdateAvailable(d.action === "update");
    // A check writes nothing, so "success" would overstate it; only a refusal
    // — the thing worth hearing about — gets its own sound.
    playForDecision(d);
  }
  catch (e) { err("check failed — " + e.message); play("error"); }
  finally { busy(null); }
};

$("btnUpdate").onclick = async () => {
  if (!confirm("Fetch new chapters and update this epub in calibre?")) return;
  clearErr();
  busy("updating — big serials can take minutes; leave this page open…");
  try {
    const d = await apiJson("/books/" + state.bookId + "/update", {method: "POST"});
    renderDecision(d);
    setUpdateAvailable(false);   // whatever was pending has now been applied
    playForDecision(d);
  }
  catch (e) { err("update failed — " + e.message); play("error"); }
  finally { busy(null); }
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
      id: "ficsync-epub",        // Chrome ties a remembered folder to this
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
  const meta = state.bookMeta;
  try {
    if (await deviceCopyIsStale(meta)) {
      busy("downloading to this device…");
      await saveBookToDevice(meta);
      await refreshActions();
    }
    busy("opening…");
    await openBookInReader(meta);
  } catch (e) { err("could not open — " + e.message); play("error"); }
  finally { busy(null); }
};

$("btnConvert").onclick = async () => {
  if (!confirm(
      "Replace this book with a fresh download from the site?\n\n" +
      "The current file is backed up on the server, but this first conversion " +
      "cannot check for chapters the author may have deleted. Afterwards the " +
      "book is fully managed and protected.")) return;
  clearErr();
  busy("downloading a fresh copy from the site — this can take minutes…");
  try {
    const d = await apiJson("/books/" + state.bookId + "/convert", {method: "POST"});
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
  } catch (e) { err("convert failed — " + e.message); play("error"); }
  finally { busy(null); }
};

$("btnEpub").onclick = async () => {
  clearErr();
  const meta = state.bookMeta || {id: state.bookId};
  // In the shell this button manages the device copy: fetch it when absent,
  // delete it when present (re-fetching is then one more tap).
  if (inShell()) {
    try {
      if (await statBook(meta)) {
        if (!confirm("Delete this book's file from the device?")) return;
        busy("deleting…");
        await deleteBookFromDevice(meta);
      } else {
        busy("downloading to this device…");
        await saveBookToDevice(meta);
      }
      await refreshActions();
      play("success");
    } catch (e) { err("failed — " + e.message); play("error"); }
    finally { busy(null); }
    return;
  }
  busy("downloading epub…");
  try {
    const blob = await (await api("/books/" + state.bookId + "/epub")).blob();
    await saveEpub(blob, epubFilename(meta));
    play("success");
  } catch (e) {
    // Dismissing the folder picker is a choice, not a failure.
    if (e && e.name === "AbortError") return;
    err("download failed — " + e.message);
    play("error");
  }
  finally { busy(null); }
};
