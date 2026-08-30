// What the configured column shows at the right of a row's title line.
// Exercised from tests/test_row_field.py via node.
import "./dom_stub.mjs";
const { rowFieldLabel } = await import("../ratchet/static/format.js");

const out = {};

out.one = rowFieldLabel({row_values: ["Worm"]});
out.several = rowFieldLabel({row_values: ["Worm", "My Hero Academia"]});
out.hierarchical = rowFieldLabel({row_values: ["Riordanverse.Olympian"]});

// A series already occupies that space, so the column gives way to it.
out.series_wins = rowFieldLabel({row_values: ["Worm"], series: "Cosmere",
                                 series_index: 2.0});
out.series_without_index_still_wins = rowFieldLabel(
  {row_values: ["Worm"], series: "Cosmere"});

// Libraries without the column, and books that simply have no value in it.
out.absent = rowFieldLabel({title: "A book"});
out.empty_list = rowFieldLabel({row_values: []});
out.nothing = rowFieldLabel({});

process.stdout.write(JSON.stringify(out));
