// Entry point: nav wiring, token handling, boot.
"use strict";
import { $, state, setToken, setLibrary, apiJson, clearErr, show } from "./core.js";
import { renderFilterChips, search } from "./browse.js";
import "./picker.js";     // side effect: filter-picker button handlers
import "./actions.js";    // side effect: check/update/epub button handlers
import { initSfx } from "./sfx.js";

document.querySelectorAll("[data-nav]").forEach(b =>
  b.addEventListener("click", () => show(b.dataset.nav)));

initSfx();

$("btnSettings").onclick = () => { $("tokenInput").value = state.token; show("token"); };
$("btnSaveToken").onclick = () => {
  setToken($("tokenInput").value.trim());
  boot();
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

async function loadLibraries() {
  const sel = $("librarySelect");
  let data;
  try { data = await apiJson("/libraries"); }
  catch (e) { sel.hidden = true; return; }
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
  sel.hidden = state.libraries.length < 2;
  sel.onchange = () => {
    setLibrary(sel.value);        // persisted; this device reopens here
    $("q").value = "";
    renderFilterChips();
    show("browse");
    search();
  };
}

async function boot() {
  clearErr();
  if (!state.token) { show("token"); return; }
  try {
    const uiCfg = await apiJson("/ui-config");
    state.writable = uiCfg.writable_fields || [];
    if (uiCfg.genre_field !== undefined) state.genreField = uiCfg.genre_field;
  } catch (e) { return; }   // 401 already routed to the token view
  await loadLibraries();
  show("browse");
  renderFilterChips();
  search();
}
boot();
