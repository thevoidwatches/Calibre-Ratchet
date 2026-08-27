// Which fields match hierarchically, asked the way the book page asks it
// when one of its chips or its series/author line is tapped.
import "./dom_stub.mjs";

const { fieldIsHierarchical } = await import("../ratchet/static/picker.js");

const out = {};
for (const field of ["#genre", "tags", "#fandom", "#readinglist",
                     "series", "authors", "publisher", "languages"])
  out[field] = fieldIsHierarchical(field);
process.stdout.write(JSON.stringify(out));
