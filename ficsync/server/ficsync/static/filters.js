// Saved filter sets, and collapsing the filter chips.
//
// Sets live on the server (see /filters) rather than in localStorage, so one
// saved on the phone is available on the ereader. They are scoped per library
// by the server, since a filter naming '#genre' means nothing in a library
// without that column.
//
// Collapsing the chips is browse.js's business (it renders them); this module
// only handles the saved sets, so the dependency runs one way.
"use strict";
import { $, state, apiJson, api, err, clearErr } from "./core.js";
import { renderFilterChips, renderFilterBar, search, termCount } from "./browse.js";

export async function loadSavedFilters() {
  const sel = $("savedFilters");
  const previous = sel.value;
  let list = [];
  try { list = (await apiJson("/filters")).filters || []; }
  catch (e) { /* saved sets are a convenience; a failure must not block browsing */ }
  state.savedFilters = list;
  sel.innerHTML = '<option value="">Saved…</option>';
  for (const f of list) {
    const o = document.createElement("option");
    o.value = f.name;
    o.textContent = f.name;
    sel.append(o);
  }
  sel.value = list.some(f => f.name === previous) ? previous : "";
  $("btnDeleteFilters").hidden = !sel.value;
}

function applySaved(name) {
  const found = (state.savedFilters || []).find(f => f.name === name);
  if (!found) return;
  // Deep-copied so editing the chips afterwards does not mutate the cached set.
  state.filterGroups = JSON.parse(JSON.stringify(found.groups || []));
  renderFilterChips();
  renderFilterBar();
  search();
}

export function initFilters() {
  $("savedFilters").onchange = () => {
    const name = $("savedFilters").value;
    $("btnDeleteFilters").hidden = !name;
    if (name) applySaved(name);
  };

  $("btnSaveFilters").onclick = async () => {
    if (!termCount()) return;
    const suggested = $("savedFilters").value || "";
    const name = (prompt("Save this filter set as:", suggested) || "").trim();
    if (!name) return;
    clearErr();
    try {
      await api("/filters/" + encodeURIComponent(name), {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({groups: state.filterGroups}),
      });
      await loadSavedFilters();
      $("savedFilters").value = name;
      $("btnDeleteFilters").hidden = false;
    } catch (e) { err("could not save filter set — " + e.message); }
  };

  $("btnDeleteFilters").onclick = async () => {
    const name = $("savedFilters").value;
    if (!name || !confirm('Delete the saved filter set "' + name + '"?')) return;
    clearErr();
    try {
      await api("/filters/" + encodeURIComponent(name), {method: "DELETE"});
      await loadSavedFilters();
    } catch (e) { err("could not delete filter set — " + e.message); }
  };
}
