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
