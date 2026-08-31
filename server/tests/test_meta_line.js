// Where a book row's genre and tag line is allowed to wrap.
// Exercised from tests/test_meta_line.py via node.
import "./dom_stub.mjs";
const { metaLine } = await import("../ratchet/static/format.js");

const ZWSP = "​";
const out = {};
// Reported with the break made visible, so a failure says where it landed.
const show = s => s.split(ZWSP).join("<>");

out.deep = show(metaLine(
  ["Nonfiction.Informational.Science.Physics.Astrophysics"]));
out.shallow = show(metaLine(["Comedy.Dark Humor", "Isekai.Urban.Fantasy"]));

// Royal Road's flat genres: nothing to break, nothing added.
out.flat = show(metaLine(["Action", "Adventure", "Cozy"]));
out.flat_untouched = metaLine(["Action", "Adventure"]).includes(ZWSP);

// A dot followed by a space already has a break opportunity, and is usually
// an abbreviation rather than a hierarchy.
out.abbreviation = show(metaLine(["Jonathan Strange and Mr. Norrell"]));

out.empty = show(metaLine([]));
out.missing = show(metaLine(null));
out.separator = show(metaLine(["A.B", "C.D"]));

// The breaks are invisible: what a reader sees must be unchanged.
const visible = s => s.split(ZWSP).join("");
out.reads_the_same = visible(metaLine(["Fantasy.High", "Romance"]))
  === ["Fantasy.High", "Romance"].join(" · ");

process.stdout.write(JSON.stringify(out));
