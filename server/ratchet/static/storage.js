// Device-side book storage, active only inside the Android shell.
//
// Layout: a visible top-level folder in shared storage, one subfolder per
// calibre library —
//
//     /storage/emulated/0/Ratchet/<Library>/
//
// visible so Moon+ and file managers can browse it. Real paths there need
// "All files access" on Android 11+, which the shell's RatchetNative plugin
// checks for and requests; folder creation itself goes through the stock
// Filesystem plugin. In a plain browser every export here is an inert no-op.
"use strict";
import { $, api, state } from "./core.js";
import { epubFilename } from "./format.js";
import { removeBook, upsertBook } from "./catalog.js";

const ROOT = "Ratchet";

const plugins = () => (window.Capacitor && window.Capacitor.Plugins) || null;

export const inShell = () =>
  !!(plugins() && plugins().Filesystem && plugins().RatchetNative);

async function hasAccess() {
  try { return (await plugins().RatchetNative.hasAllFilesAccess()).granted; }
  catch (e) { return false; }
}

/** Create Ratchet/<library>/ for every library the server reports. */
async function createFolders() {
  const fs = plugins().Filesystem;
  for (const lib of state.libraries || []) {
    try {
      await fs.mkdir({
        path: ROOT + "/" + lib.id,
        directory: "EXTERNAL_STORAGE",
        recursive: true,
      });
    } catch (e) {
      // "Directory exists" is success; anything else shows in the banner
      // rather than failing silently.
      const msg = String((e && e.message) || e);
      if (!/exist/i.test(msg)) throw new Error(lib.id + ": " + msg);
    }
  }
}

function banner(show, text) {
  const el = $("storageBanner");
  if (!el) return;
  el.hidden = !show;
  if (text) $("storageBannerText").textContent = text;
}

/** Make sure the folder tree exists, asking for the storage grant if needed.
 *  Runs after the library list loads, and again on each return to the app so
 *  granting access in Settings is picked up without a restart. */
export async function ensureStorage() {
  if (!inShell()) return;
  if (!(await hasAccess())) {
    banner(true, "Ratchet needs storage access to keep books in a folder " +
                 "Moon+ can read.");
    return;
  }
  try {
    await createFolders();
    banner(false);
  } catch (e) {
    banner(true, "Storage is granted but creating the Ratchet folder failed — " +
                 (e && e.message ? e.message : e));
  }
}

/** Open a URL outside the WebView (system browser). Falls back to a normal
 *  navigation in a plain browser. */
export function openExternal(url) {
  if (inShell()) return plugins().RatchetNative.openUrl({url});
  window.location.href = url;
}

/** The clipboard's text, or "" when it cannot be read.
 *
 *  In the shell this goes through the native plugin: navigator.clipboard
 *  needs a secure context, and Ratchet is served over plain http on the
 *  tailnet, so the web API is unavailable exactly where it would be most
 *  useful. Desktop browsers on https still get the standard route.
 */
export async function readClipboard() {
  if (inShell()) {
    try { return (await plugins().RatchetNative.readClipboard()).text || ""; }
    catch (e) { return ""; }
  }
  try { return await navigator.clipboard.readText(); }
  catch (e) { return ""; }        // blocked, denied, or no clipboard API
}

/** Text shared into the app since it was last asked, or "". Collected once
 *  and cleared natively, so a later return to the app cannot re-add it. */
export async function consumeSharedText() {
  if (!inShell()) return "";
  try { return (await plugins().RatchetNative.consumeSharedText()).text || ""; }
  catch (e) { return ""; }
}

/** When this build was installed, in epoch ms; 0 when unknown. */
export async function installedAt() {
  if (!inShell()) return 0;
  try { return Number((await plugins().RatchetNative.appInfo()).installedAt) || 0; }
  catch (e) { return 0; }
}

// ---- device copies of books (Ratchet/<library>/<filename>.epub) ----

function devicePath(meta) {
  return ROOT + "/" + (state.library || "Library") + "/" + epubFilename(meta);
}

/** stat for this book's device copy: {mtimeMs, size} or null when absent. */
export async function statBook(meta) {
  if (!inShell()) return null;
  try {
    const st = await plugins().Filesystem.stat(
      {path: devicePath(meta), directory: "EXTERNAL_STORAGE"});
    return {mtimeMs: Number(st.mtime) || 0, size: Number(st.size) || 0};
  } catch (e) { return null; }
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onerror = () => reject(r.error);
    r.onload = () => resolve(String(r.result).split(",", 2)[1]);
    r.readAsDataURL(blob);
  });
}

/** Download the epub from the server and write it over the device copy —
 *  same path every time, so Moon+ keeps its reading position. */
export async function saveBookToDevice(meta) {
  // The calibre metadata object has no plain .id; the open book's id lives in
  // shared state.
  const blob = await (await api("/books/" + state.bookId + "/epub")).blob();
  await plugins().Filesystem.writeFile({
    path: devicePath(meta),
    directory: "EXTERNAL_STORAGE",
    data: await blobToBase64(blob),
    recursive: true,
  });
  // The offline catalog mirrors what is on the device; it must never be the
  // reason a download counts as failed.
  try { await upsertBook(meta); } catch (e) { /* best-effort */ }
}

export async function deleteBookFromDevice(meta) {
  await plugins().Filesystem.deleteFile(
    {path: devicePath(meta), directory: "EXTERNAL_STORAGE"});
  try { await removeBook(); } catch (e) { /* best-effort */ }
}

/** True when the device copy is missing or older than calibre's copy. */
export async function deviceCopyIsStale(meta) {
  const st = await statBook(meta);
  if (!st) return true;
  const server = Date.parse(meta.last_modified || "") || 0;
  return server > st.mtimeMs;
}

// Opened by explicit package: Android keys "default app" choices to the
// intent's exact shape, so on Boox the built-in reader hijacks generic epub
// intents no matter what default the user picked. Preference order: Moon+
// Pro, Moon+ free, then whatever Android resolves.
const READER_PACKAGES = ["com.flyersoft.moonreaderp", "com.flyersoft.moonreader"];

export async function openBookInReader(meta) {
  const {uri} = await plugins().Filesystem.getUri(
    {path: devicePath(meta), directory: "EXTERNAL_STORAGE"});
  await plugins().RatchetNative.openFile({
    path: decodeURIComponent(uri.replace(/^file:\/\//, "")),
    contentType: "application/epub+zip",
    packages: READER_PACKAGES,
  });
}

export function initStorage() {
  const btn = $("btnGrantStorage");
  if (btn) btn.onclick = () => plugins().RatchetNative.openAllFilesSettings();
  // Returning from the Settings screen fires visibilitychange; re-check then.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") ensureStorage();
  });
}
