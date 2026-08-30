// Pure display/name formatting. Deliberately free of DOM and storage
// access so it can be imported and tested outside a browser.
"use strict";

/** calibre stores the series index as a float; show 2 rather than 2.0. */
function seriesIndexText(idx) {
  if (idx === null || idx === undefined || idx === "") return "";
  const n = Number(idx);
  return Number.isFinite(n) ? String(+n.toFixed(2)) : String(idx);
}

/** "Rivers of London #2" — series name plus index when there is one. Shared by
 *  the book list and the detail page so the two cannot format it differently. */
export function seriesLabel(meta) {
  const name = meta && meta.series;
  if (!name) return "";
  const idx = seriesIndexText(meta.series_index);
  return idx ? name + " #" + idx : name;
}

// Characters Windows, Android and calibre all dislike in a file name, plus the
// control range. Replaced rather than dropped so words do not run together.
const UNSAFE_FILENAME = /[<>:"/\\|?*\u0000-\u001f]/g;
const MAX_STEM = 180;   // leaves room for ".epub" under a 255-byte limit

/** What to offer in a field's "existing values" dropdown: everything the
 *  library already uses, minus what this book already has, deduped and in a
 *  readable order (the vocabulary arrives in tree-walk order, not sorted). */
export function suggestValues(all, current) {
  const have = new Set(current || []);
  return [...new Set(all || [])]
    .filter(v => v && !have.has(v))
    .sort((a, b) => a.localeCompare(b));
}

/** Arrange suggestions by their top hierarchy level, so a long vocabulary
 *  reads as a few headed groups instead of one flat wall.
 *
 *  Returns {loose, groups}: `loose` are values with no relatives, listed
 *  plainly; each group heads a family under its first path segment. Labels
 *  drop the part the heading already says — under "Fantasy", the value
 *  "Fantasy.Xianxia" reads as "Xianxia" — while the value saved stays the
 *  full dotted path. Groups are one level deep because that is all <optgroup>
 *  allows; a deeper value keeps the rest of its path in the label.
 */
export function groupSuggestions(values) {
  const families = new Map();
  for (const v of values || []) {
    const head = String(v).split(".")[0];
    if (!families.has(head)) families.set(head, []);
    families.get(head).push(v);
  }
  const loose = [], groups = [];
  for (const [head, members] of families) {
    if (members.length === 1 && members[0] === head) {
      loose.push({value: head, label: head});
      continue;
    }
    // The family's own bare value first, then its children.
    const items = members
      .map(v => ({value: v, label: v === head ? head : v.slice(head.length + 1)}))
      .sort((a, b) => (a.value === head ? -1 : b.value === head ? 1 : 0)
                      || a.label.localeCompare(b.label));
    groups.push({label: head, items});
  }
  return {loose, groups};
}

/** One offline-catalog record: the metadata the shell's bundled offline page
 *  shows and filters on when the server is unreachable. Pure so node tests
 *  can pin the shape the two sides agree on. */
export function catalogEntry(meta, id, library, genreField) {
  const m = meta || {};
  const um = m.user_metadata || {};
  const listOf = f => {
    const v = (um[f] || {})["#value#"];
    return Array.isArray(v) ? v : v ? [v] : [];
  };
  const rl = (um["#readinglist"] || {})["#value#"];
  return {
    library,
    id,
    file: epubFilename(m),
    title: m.title || "",
    series: m.series || null,
    series_index: m.series_index ?? null,
    authors: m.authors || [],
    genres: listOf(genreField),
    tags: m.tags || [],
    readinglist: rl == null ? "" : String(rl),
    last_modified: m.last_modified || "",
  };
}

/** "The Abyss 2. The Edge of the Abyss - Emily Skrutskie.epub"
 *  Without a series: "Blue Core - Ivan Kal.epub". */
export function epubFilename(meta) {
  const m = meta || {};
  const title = (m.title || "").trim();
  const authors = (m.authors || []).join(", ").trim();
  const prefix = m.series
    ? [m.series, seriesIndexText(m.series_index)].filter(Boolean).join(" ") + "."
    : "";
  let stem = [prefix, title].filter(Boolean).join(" ");
  if (authors) stem += " - " + authors;
  stem = stem.replace(UNSAFE_FILENAME, "-").replace(/\s+/g, " ").trim();
  // Windows rejects names ending in a dot or space.
  stem = stem.slice(0, MAX_STEM).replace(/[. ]+$/, "");
  return (stem || String(m.id ?? "book")) + ".epub";
}


/** Which of a column's values the filter picker should draw.
 *
 *  Two independent narrowings, applied in this order so the "N of M" count
 *  above the tree describes exactly the set the tree is built from: first to
 *  the values that occur in the books the current filters match (`present`,
 *  or null when the list is not being narrowed), then to what has been typed.
 *  Matching is case-insensitive and anywhere in the value, because a value
 *  five levels down is more often remembered by its leaf than its root. */
export function visibleValues(all, present, showAll, typed) {
  const scoped = (present && !showAll)
    ? (all || []).filter(v => present.has(v)) : (all || []);
  const q = String(typed || "").trim().toLowerCase();
  return q ? scoped.filter(v => v.toLowerCase().includes(q)) : scoped;
}


/** "312 pages" for a book calibre has measured, and nothing for one it has
 *  not. calibre fills the count in when a book's format is written, so an
 *  older book that has never been updated reports 0 — which means unknown
 *  here, not empty. */
/** How far a download has got, for the busy line: "41% — 360 of 877 MB"
 *  when the total is known, "360 MB so far" when it is not. */
export function progressLabel(bytes, total) {
  const mb = n => (n / 1e6).toFixed(n < 10e6 ? 1 : 0);
  if (!total) return mb(bytes) + " MB so far";
  return Math.floor(100 * Math.min(bytes, total) / total) + "% — " +
         mb(bytes) + " of " + mb(total) + " MB";
}

export function pageLabel(pages) {
  const n = Number(pages);
  if (!Number.isFinite(n) || n <= 0) return "";
  return n === 1 ? "1 page" : n.toLocaleString() + " pages";
}
