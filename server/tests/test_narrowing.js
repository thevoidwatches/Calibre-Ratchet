// Exercised from tests/test_narrowing.py via node.
import { visibleValues } from "../ratchet/static/format.js";

const ALL = ["Powers", "Powers.Brute.Taylor Hebert", "Powers.Changer.Taylor Hebert",
             "Romance.Miraculous.Marinette Dupain-Cheng/Adrien Agreste",
             "Tropes.Redemption.Anakin Skywalker"];
const HERE = new Set(["Powers.Brute.Taylor Hebert", "Tropes.Redemption.Anakin Skywalker"]);

process.stdout.write(JSON.stringify({
  not_narrowed: visibleValues(ALL, null, false, ""),
  narrowed: visibleValues(ALL, HERE, false, ""),
  show_all_overrides: visibleValues(ALL, HERE, true, ""),
  typed_within_narrowed: visibleValues(ALL, HERE, false, "taylor"),
  typed_within_all: visibleValues(ALL, HERE, true, "taylor"),
  typed_matches_leaf: visibleValues(ALL, null, false, "adrien"),
  typed_is_case_insensitive: visibleValues(ALL, null, false, "ANAKIN"),
  typed_trims: visibleValues(ALL, null, false, "  anakin  "),
  narrowed_to_nothing: visibleValues(ALL, new Set(), false, ""),
  empty_vocabulary: visibleValues([], HERE, false, ""),
  missing_vocabulary: visibleValues(null, null, false, ""),
}));
