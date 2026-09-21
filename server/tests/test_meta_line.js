// Where a book row's genre and tag line is allowed to wrap.
// Exercised from tests/test_meta_line.py via node.
import "./dom_stub.mjs";
const { metaLine, segments, breakable, seriesLabel } =
  await import("../ratchet/static/format.js");

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

// One value, as shown wherever it may have to wrap: a series on a book's
// row, a chip on a book's page. Same breaks as the line above, same rule.
out.series_dotted = show(breakable(seriesLabel(
  {series: "Cosmere.Mistborn.Era One", series_index: 2})));
out.series_doctor = show(breakable(seriesLabel({series: "Dr. Greta Helsing"})));
out.series_plain = show(breakable("A Practical Guide to Sorcery"));
out.breakable_nothing = [breakable(null), breakable(undefined), breakable("")];
out.breakable_same_text = visible(breakable("Powers.Specific.Shipgirl")) ===
  "Powers.Specific.Shipgirl";

// Splitting a hierarchy: the separator is a dot with the next level right
// behind it, so a dot followed by a space belongs to the name.
out.seg_deep = segments("Nonfiction.Informational.Science");
out.seg_title = segments("Dr. Greta Helsing");
out.seg_fandom = segments("Jonathan Strange and Mr. Norrell");
out.seg_mixed = segments("A.B. C");
out.seg_colon = segments("Cosmere.Mistborn.1: Fall of the Empire");
out.seg_flat = segments("Romance");
out.seg_empty = segments("");
out.seg_missing = segments(null);
// Every level's key is rebuilt by rejoining, so the round trip must be exact.
out.seg_roundtrip = ["Dr. Greta Helsing", "A.B. C", "Worm.Internship.Deputy"]
  .every(v => segments(v).join(".") === v);

process.stdout.write(JSON.stringify(out));
