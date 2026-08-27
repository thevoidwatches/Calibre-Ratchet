// The device-side offline catalog: Ratchet/.catalog.json, one record per book
// with a device copy. The shell's bundled offline page (shell/www/offline.js)
// renders it when the server is unreachable; this module — served, so it can
// change without an app rebuild — is the only writer.
//
// Everything here is best-effort: the catalog is a convenience mirror, so no
// failure in it may break a download, a delete, or a metadata save. Outside
// the shell every export is an inert no-op.
"use strict";
import { apiJson, state } from "./core.js";
import { catalogEntry, epubFilename } from "./format.js";

const PATH = "Ratchet/.catalog.json";

// Deliberately not storage.js's inShell(): storage.js imports this module, and
// a back-import would make the two circular.
const fs = () => (window.Capacitor && window.Capacitor.Plugins &&
                  window.Capacitor.Plugins.Filesystem) || null;

async function readCatalog() {
  try {
    const res = await fs().readFile(
      {path: PATH, directory: "EXTERNAL_STORAGE", encoding: "utf8"});
    const cat = JSON.parse(res.data);
    if (Array.isArray(cat.books)) return cat;
  } catch (e) { /* absent or corrupt — start fresh */ }
  return {version: 1, books: []};
}

async function writeCatalog(cat) {
  await fs().writeFile({path: PATH, directory: "EXTERNAL_STORAGE",
                        data: JSON.stringify(cat), encoding: "utf8",
                        recursive: true});
}

const sameBook = (b, library, id) => b.library === library && b.id === id;

/** Ids of the current library's books with a device copy — what the
 *  "Downloaded" filter expands to. Empty outside the shell. */
export async function downloadedIds() {
  if (!fs()) return [];
  try {
    const cat = await readCatalog();
    return cat.books.filter(b => b.library === state.library).map(b => b.id);
  } catch (e) { return []; }
}

/** Record (or replace) the open book's entry after its epub lands on the
 *  device. The file name is recomputed to match what was just written. */
export async function upsertBook(meta) {
  if (!fs()) return;
  const entry = catalogEntry(meta, state.bookId, state.library, state.genreField);
  const cat = await readCatalog();
  const i = cat.books.findIndex(b => sameBook(b, entry.library, entry.id));
  if (i === -1) cat.books.push(entry);
  else cat.books[i] = entry;
  await writeCatalog(cat);
}

/** Drop the open book's entry after its device copy is deleted. */
export async function removeBook() {
  if (!fs()) return;
  const cat = await readCatalog();
  const before = cat.books.length;
  cat.books = cat.books.filter(b => !sameBook(b, state.library, state.bookId));
  if (cat.books.length !== before) await writeCatalog(cat);
}

/** After a metadata edit: bring the open book's entry up to date, if it has
 *  one. Keeps the recorded file name — the on-disk file is the truth, and a
 *  retitle only renames it on the next download. */
export async function refreshOpenBook(meta) {
  if (!fs()) return;
  const cat = await readCatalog();
  const i = cat.books.findIndex(b => sameBook(b, state.library, state.bookId));
  if (i === -1) return;
  const entry = catalogEntry(meta, state.bookId, state.library, state.genreField);
  entry.file = cat.books[i].file;
  cat.books[i] = entry;
  await writeCatalog(cat);
}

/** Bring the whole catalog up to date while the server is reachable: adopt
 *  device epubs downloaded before the catalog existed (matched to books by
 *  the filename the UI would have given them), then re-fetch every entry's
 *  metadata. Runs in the background on boot; any failure leaves the catalog
 *  as it was. */
export async function refreshCatalog() {
  if (!fs()) return;
  const cat = await readCatalog();

  for (const lib of state.libraries || []) {
    let names = [];
    try {
      const dir = await fs().readdir(
        {path: "Ratchet/" + lib.id, directory: "EXTERNAL_STORAGE"});
      names = (dir.files || []).map(f => f.name).filter(n => /\.epub$/i.test(n));
    } catch (e) { continue; }   // folder not created yet
    const known = new Set(cat.books.filter(b => b.library === lib.id)
                                   .map(b => b.file));
    const orphans = names.filter(n => !known.has(n));
    if (!orphans.length) continue;
    let listing;
    try {
      listing = await apiJson(
        "/books?num=100000&library=" + encodeURIComponent(lib.id));
    } catch (e) { continue; }
    const idByFile = new Map();
    for (const row of listing.books || []) idByFile.set(epubFilename(row), row.id);
    for (const name of orphans) {
      const id = idByFile.get(name);
      // Skeleton entry; the metadata pass below fills it in.
      if (id !== undefined) cat.books.push({library: lib.id, id, file: name});
    }
  }

  let any = false;
  for (const b of cat.books) {
    try {
      const data = await apiJson(
        "/books/" + b.id + "?library=" + encodeURIComponent(b.library));
      const entry = catalogEntry(data.calibre || {}, b.id, b.library,
                                 state.genreField);
      entry.file = b.file;
      Object.assign(b, entry);
      any = true;
    } catch (e) { /* offline blip, or gone from calibre — keep what we have */ }
  }
  if (any) await writeCatalog(cat);
}
