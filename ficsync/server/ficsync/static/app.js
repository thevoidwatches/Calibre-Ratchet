// Entry point: nav wiring, token handling, boot.
"use strict";
import { $, state, setToken, setLibrary, apiJson, clearErr, show } from "./core.js";
import { renderFilterChips, search } from "./browse.js";
import "./picker.js";     // side effect: filter-picker button handlers
import "./actions.js";    // side effect: check/update/epub button handlers
import { initSfx, play } from "./sfx.js";
import { initTheme } from "./theme.js";

document.querySelectorAll("[data-nav]").forEach(b =>
  b.addEventListener("click", () => show(b.dataset.nav)));

initTheme();
initSfx();

$("btnSettings").onclick = () => { $("tokenInput").value = state.token; show("token"); };
$("btnSaveToken").onclick = () => {
  setToken($("tokenInput").value.trim());
  boot({announce: true});
};

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
    setLibrary(sel.value);        // persisted; this device reopens here
    $("q").value = "";
    renderFilterChips();
    show("browse");
    search();
  };
}

/** `announce` marks a deliberate sign-in. Plain page loads re-run boot() with
 *  a stored token, and chiming every time the app opens would be noise. */
async function boot({announce = false} = {}) {
  clearErr();
  if (!state.token) { resetLibrarySelect(); show("token"); return; }
  try {
    const uiCfg = await apiJson("/ui-config");
    state.writable = uiCfg.writable_fields || [];
    if (uiCfg.genre_field !== undefined) state.genreField = uiCfg.genre_field;
  } catch (e) { resetLibrarySelect(); return; }  // 401 already routed to the token view
  if (announce) play("success");   // the token was accepted
  await loadLibraries();
  show("browse");
  renderFilterChips();
  search();
}
boot();
