// Entry point: nav wiring, token handling, boot.
"use strict";
import { $, state, setToken, setLibrary, setSort, apiJson, clearErr, show, ROOT_ENTRY, viewBehind, viewNow} from "./core.js";
import { renderFilterChips, renderFilterBar, search, queueAdd, firstUrl } from "./browse.js";
import "./picker.js";     // side effect: filter-picker button handlers
import "./actions.js";    // side effect: check/update/epub button handlers
import { initSfx, play } from "./sfx.js";
import { initTheme } from "./theme.js";
import { initFilters, loadSavedFilters } from "./filters.js";
import { openBook, closeCover } from "./detail.js";
import { ensureStorage, initStorage, inShell, openExternal,
         consumeSharedText, installedAt } from "./storage.js";
import { refreshCatalog } from "./catalog.js";

// On-screen back/cancel buttons pop history rather than jumping, so they and
// the system back button always agree about where "back" goes.
document.querySelectorAll("[data-nav]").forEach(b =>
  b.addEventListener("click", () => history.back()));

const POP_VIEWS = new Set(["browse", "pickcol", "detail", "token"]);

// One entry below everything, put in before any view records itself. Reaching
// it means the back button has run out of app to walk through, which is where
// the shell would otherwise close.
// Ratchet puts the book list back where it was itself (see show()). Left on
// "auto" the browser also restores a position of its own, asynchronously and
// after the popstate handler has run — so its guess, usually the top of the
// page, would win every time and the place kept here would never be seen.
if ("scrollRestoration" in history) history.scrollRestoration = "manual";

if (history.state === null) history.replaceState({view: ROOT_ENTRY}, "");

window.addEventListener("popstate", e => {
  // The cover overlay is the shallowest thing on screen: back dismisses it
  // and stops there, leaving the book page as it was.
  if (closeCover()) return;
  const st = e.state || {view: ROOT_ENTRY};
  if (st.view === ROOT_ENTRY) {
    const behind = viewBehind(viewNow());
    // Nothing behind the login screen: step back again and let the app close,
    // which is what the second press of back is asking for.
    if (behind === null) { history.back(); return; }
    show(behind);          // pushes, so there is something to pop next time
    return;
  }
  if (st.view === "detail" && st.bookId) { openBook(st.bookId, false); return; }
  // A pickval entry reopens as the column list: the value screen only means
  // something for the column that was being picked at the time.
  const view = st.view === "pickval" ? "pickcol" : st.view;
  show(POP_VIEWS.has(view) ? view : "browse", false);
});

initTheme();
initSfx();
initFilters();
initStorage();

// The wordmark is the app-update link. A tap asks first — it is easy to hit
// by accident — then downloads: plain browsers follow the href, while in the
// shell the WebView cannot download, so the system browser opens instead.
$("apkLink").addEventListener("click", async e => {
  e.preventDefault();
  if (!confirm(await updatePrompt())) return;
  play("select");       // off to the browser: a move, once agreed to
  if (inShell()) openExternal(window.location.origin + "/apk");
  else window.location.href = "/apk";
});

/** Say whether downloading would actually get anything newer.
 *
 *  Compared as timestamps — when the deployed APK was built against when this
 *  build was installed — because neither side tracks a version number the
 *  other can see, and this is the question being asked anyway. */
async function updatePrompt() {
  const ask = "Download the latest version of the Ratchet app?";
  if (!inShell()) return ask;
  try {
    const [info, mine] = await Promise.all([apiJson("/apk-info"), installedAt()]);
    if (!mine || !info.built_at) return ask;
    const built = new Date(info.built_at).toLocaleString();
    return info.built_at > mine
      ? `A newer version is available (built ${built}). Download it?`
      : `You already have the latest version (built ${built}). Download anyway?`;
  } catch (e) { return ask; }   // no answer is not a reason to block the update
}

/** A story link shared into Ratchet from elsewhere on the device. Checked on
 *  load and whenever the app comes back to the foreground, since a share into
 *  an already-running app never reloads the page. */
async function checkSharedStory() {
  const shared = firstUrl(await consumeSharedText());
  if (!shared) return;
  if (!confirm("Add this story to " + (state.library || "the library") + "?\n\n" +
               shared)) return;
  show("browse");
  queueAdd(shared);
}

// Inside the Android shell the WebView keeps this page alive across app
// switches — without this, an app "reopened" days later still runs whatever
// was loaded back then (stale JS, CSS, logos). Reload when coming back to the
// foreground after a real absence; short flips keep their state.
const STALE_AFTER_MS = 5 * 60 * 1000;
let hiddenAt = null;
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") { hiddenAt = Date.now(); return; }
  if (hiddenAt && Date.now() - hiddenAt > STALE_AFTER_MS) location.reload();
  hiddenAt = null;
  // A share into the running app brings it forward without reloading.
  checkSharedStory().catch(() => {});
});

$("btnSettings").onclick = () => { $("tokenInput").value = state.token; show("token"); };
$("btnSaveToken").onclick = () => {
  setToken($("tokenInput").value.trim());
  boot({announce: true});
};
// No form around the box, so Enter has to be wired by hand. Clicking the
// button rather than calling its handler keeps the tap sound, which comes
// from the click.
$("tokenInput").addEventListener("keydown", e => {
  if (e.key === "Enter") $("btnSaveToken").click();
});

/** The library to open on: whichever this device last chose, else the
 *  configured default, else the server's own default library. */
function pickStartingLibrary(data) {
  const known = new Set(state.libraries.map(l => l.id));
  // A remembered choice wins, unless that library is gone (renamed/removed).
  if (state.library && known.has(state.library)) return state.library;
  // config's [calibre] library_id, when it names a real library.
  if (data.default && known.has(data.default)) return data.default;
  // "" in config means "the content server's default library" — resolve it to
  // that library's actual id so the selector can show which one is active.
  const flagged = state.libraries.find(l => l.is_default);
  if (flagged) return flagged.id;
  return state.libraries.length ? state.libraries[0].id : "";
}

/** Put the selector back to its pre-login state: a single inert placeholder
 *  rather than a stale list from whoever was signed in before. */
export function resetLibrarySelect() {
  const sel = $("librarySelect");
  if (!sel) return;
  sel.innerHTML = '<option value="">Library</option>';
  sel.disabled = true;
  sel.hidden = false;
}

async function loadLibraries() {
  const sel = $("librarySelect");
  let data;
  try { data = await apiJson("/libraries"); }
  catch (e) { resetLibrarySelect(); sel.hidden = true; return; }
  state.libraries = data.libraries || [];
  state.library = pickStartingLibrary(data);
  sel.innerHTML = "";
  for (const lib of state.libraries) {
    const o = document.createElement("option");
    o.value = lib.id;
    o.textContent = lib.name;
    sel.append(o);
  }
  sel.value = state.library;
  sel.disabled = false;
  sel.hidden = state.libraries.length < 2;
  sel.onchange = () => {
    // Choosing from the dropdown is the move; the tap that opened it already
    // sounded. From another page the change of view below sounds instead.
    if (viewNow() === "browse") play("select");
    setLibrary(sel.value);        // persisted; this device reopens here
    $("q").value = "";
    renderFilterChips();
    loadSavedFilters();       // saved sets are per library
    show("browse");
    search();
  };
}

/** `announce` marks a deliberate sign-in. Plain page loads re-run boot() with
 *  a stored token, and chiming every time the app opens would be noise. */
function renderSortDir() {
  const btn = $("btnSortDir");
  const down = state.sortDir === "desc";
  btn.textContent = down ? "↓" : "↑";
  btn.title = down ? "descending" : "ascending";
  btn.setAttribute("aria-pressed", String(down));
}

/** The orders come from the server so the UI cannot offer one it would reject. */
function initSort(uiCfg) {
  state.sortOptions = uiCfg.sort_options || [];
  const valid = new Set(state.sortOptions.map(o => o.key));
  if (!valid.has(state.sort)) state.sort = uiCfg.default_sort || "title";

  const sel = $("sortSelect");
  sel.innerHTML = "";
  for (const o of state.sortOptions) {
    const opt = document.createElement("option");
    opt.value = o.key;
    opt.textContent = o.label;
    sel.append(opt);
  }
  sel.value = state.sort;
  renderSortDir();

  sel.onchange = () => { play("select"); setSort(sel.value, state.sortDir); search(); };
  $("btnSortDir").onclick = () => {
    setSort(state.sort, state.sortDir === "desc" ? "asc" : "desc");
    renderSortDir();
    search();
  };
}

async function boot({announce = false} = {}) {
  clearErr();
  if (!state.token) { resetLibrarySelect(); show("token", false); return; }
  try {
    const uiCfg = await apiJson("/ui-config");
    state.writable = uiCfg.writable_fields || [];
    if (uiCfg.genre_field !== undefined) state.genreField = uiCfg.genre_field;
    if (Array.isArray(uiCfg.editable_fields)) state.editable = uiCfg.editable_fields;
    initSort(uiCfg);
  } catch (e) { resetLibrarySelect(); return; }  // 401 already routed to the token view
  if (announce) play("success");   // the token was accepted
  await loadLibraries();
  ensureStorage();          // shell only: Ratchet/<library>/ folders on device
  refreshCatalog().catch(() => {});   // shell only: offline catalog upkeep
  show("browse");
  renderFilterChips();
  renderFilterBar();
  loadSavedFilters();
  search();
  // Last: a share that launched the app is only actionable once a library is
  // chosen, since that is what decides where the story lands.
  checkSharedStory().catch(() => {});
}
boot();
