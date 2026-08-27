// Turning filter state into a calibre search query.
//
// The model is an AND of ORs over ATOMS: a filter is a list of GROUPS, the
// atoms inside a group are ORed, and the groups are ANDed.
//
// An atom is a term ({field, value, ...}), a reference to a saved preset
// ({preset: "name"}), or the Downloaded pseudo-filter ({downloaded: true}).
// Because a preset expands to a parenthesised expression, referencing one
// inside a group is what allows "PresetA or PresetB" — the OR of two whole
// expressions — without adding a nesting level to the editor. "PresetA and
// genre:X" is simply two groups.
//
// Downloaded is device knowledge, not a calibre column: the caller supplies
// the ids of the books with a device copy (from the offline catalog) via the
// context, and the atom expands to an "(id:A or id:B ...)" query so paging,
// sorting and counts all stay server-side.
//
// Every term is parenthesised. calibre gives `not` tighter binding than `or`
// anyway, but wrapping means the emitted query never depends on that.
//
// Pure string building: no DOM, no storage, so it can be tested outside a
// browser.
"use strict";

/** A term matches its value and, for hierarchical columns, anything beneath it:
 *  "Science Fiction" also finds "Science Fiction.Space Opera". Flat columns
 *  (authors, series) match exactly, so a dot in a name is not read as depth. */
export function termToQuery(term) {
  const field = term.field;
  let part;
  if (term.hierarchical === false) {
    part = field + ':"=' + String(term.value).replace(/"/g, '\\"') + '"';
  } else {
    const esc = String(term.value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    part = field + ':"~^' + esc + '(\\.|$)"';
  }
  return term.exclude ? "not " + part : part;
}

export const isPresetAtom = a => !!(a && typeof a.preset === "string");
export const isDownloadedAtom = a => !!(a && a.downloaded === true);

const MAX_PRESET_DEPTH = 20;

/** Expand one atom. `ctx` carries {presets, downloadedIds}: presets maps
 *  name -> groups, downloadedIds lists the current library's on-device book
 *  ids. `seen` is the chain of preset names currently being expanded, so a
 *  preset that refers back to itself (directly or through others) is dropped
 *  instead of recursing forever. */
function atomToQuery(atom, ctx, seen) {
  if (isDownloadedAtom(atom)) {
    // Book ids start at 1, so with nothing on the device this matches no
    // book — and an excluded atom then correctly matches every book.
    const ids = ctx.downloadedIds || [];
    const part = ids.length
      ? "(" + ids.map(i => "id:" + i).join(" or ") + ")"
      : 'id:"<1"';
    return atom.exclude ? "not " + part : part;
  }
  if (!isPresetAtom(atom)) return termToQuery(atom);
  const name = atom.preset;
  if (seen.includes(name) || seen.length >= MAX_PRESET_DEPTH) return "";
  const groups = (ctx.presets || {})[name];
  if (!groups) return "";          // renamed or deleted since it was referenced
  const inner = buildQuery(groups, "", ctx, seen.concat(name));
  if (!inner) return "";
  return atom.exclude ? "not (" + inner + ")" : inner;
}

export function groupToQuery(group, ctx = {}, seen = []) {
  const atoms = (group && group.terms) || [];
  const parts = atoms
    .map(a => atomToQuery(a, ctx, seen))
    .filter(Boolean)
    .map(q => "(" + q + ")");
  if (!parts.length) return "";
  return parts.length === 1 ? parts[0] : "(" + parts.join(" or ") + ")";
}

/** Groups ANDed together, with any free-text calibre search appended as one
 *  more conjunct. `ctx` is {presets, downloadedIds}, both optional. */
export function buildQuery(groups, freeText = "", ctx = {}, seen = []) {
  const parts = (groups || [])
    .map(g => groupToQuery(g, ctx, seen))
    .filter(Boolean);
  const free = (freeText || "").trim();
  if (free) parts.push(free);
  return parts.join(" and ");
}

/** Names a filter cannot reference without creating a cycle: the set itself,
 *  plus anything that already (transitively) refers to it. */
export function wouldCycle(presets, targetName, candidateName) {
  if (targetName === candidateName) return true;
  const refs = (name, seen = []) => {
    if (seen.includes(name)) return [];
    const groups = (presets || {})[name] || [];
    return groups.flatMap(g => (g.terms || [])
      .filter(isPresetAtom)
      .flatMap(a => [a.preset, ...refs(a.preset, seen.concat(name))]));
  };
  return refs(candidateName).includes(targetName);
}

/** Human-readable echo of the same structure, for the preview line. Presets
 *  show by name rather than expanded — that is the point of an alias. */
export function describeFilters(groups) {
  return (groups || []).map(g => {
    const atoms = (g.terms || []).map(a => (a.exclude ? "not " : "") +
      (isPresetAtom(a) ? "[" + a.preset + "]" :
       isDownloadedAtom(a) ? "Downloaded" : a.field + ": " + a.value));
    return atoms.length > 1 ? "(" + atoms.join(" or ") + ")" : atoms[0] || "";
  }).filter(Boolean).join(" and ");
}
