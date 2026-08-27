// Exercised from tests/test_query.py via node.
import { buildQuery, describeFilters, termToQuery, wouldCycle } from "../ratchet/static/query.js";

const t = (field, value, opts = {}) => ({field, value, ...opts});
const g = (...terms) => ({terms});
const cases = {
  single: buildQuery([g(t("#genre", "Fantasy"))]),
  or_same_field: buildQuery([g(t("#readinglist", "Unread"), t("#readinglist", "Following"))]),
  or_across_fields: buildQuery([g(t("#genre", "Fantasy"), t("tags", "Progression"))]),
  and_of_groups: buildQuery([g(t("#genre", "Fantasy")), g(t("tags", "Progression"))]),
  and_not: buildQuery([g(t("#genre", "Fantasy")), g(t("tags", "litrpg", {exclude: true}))]),
  negated_inside_or: buildQuery([g(t("#genre", "Fantasy"), t("tags", "litrpg", {exclude: true}))]),
  flat_column_exact: buildQuery([g(t("authors", "R.A. Scott", {hierarchical: false}))]),
  with_free_text: buildQuery([g(t("tags", "x"))], "royalroad"),
  free_text_only: buildQuery([], "royalroad"),
  empty: buildQuery([], ""),
  empty_group_skipped: buildQuery([g(), g(t("tags", "x"))]),
  describe: describeFilters([g(t("#genre", "A"), t("tags", "B")), g(t("x", "y", {exclude: true}))]),
  regex_escaped: termToQuery(t("#genre", "Sci-Fi (Hard)")),
};


// --- preset atoms -----------------------------------------------------------

const presets = {
  // "(Rainy Day or Shortlist)"
  Backlog: [g(t("#readinglist", "Rainy Day"), t("#readinglist", "Reading Shortlist"))],
  // "(Fantasy) and (not litrpg)"
  Cosy: [g(t("#genre", "Fantasy")), g(t("tags", "litrpg", {exclude: true}))],
  SelfRef: [g({preset: "SelfRef"})],
  A: [g({preset: "B"})],
  B: [g({preset: "A"})],
};
const p = (name, opts = {}) => ({preset: name, ...opts});
const presetCases = {
  // The case that prompted this: OR of two whole expressions.
  or_two_presets: buildQuery([g(p("Backlog"), p("Cosy"))], "", {presets}),
  and_preset_with_term: buildQuery([g(p("Cosy")), g(t("tags", "web-serial"))], "", {presets}),
  excluded_preset: buildQuery([g(t("#genre", "Fantasy")), g(p("Backlog", {exclude: true}))], "", {presets}),
  missing_preset: buildQuery([g(p("Gone")), g(t("tags", "x"))], "", {presets}),
  self_reference: buildQuery([g(p("SelfRef"))], "", {presets}),
  mutual_reference: buildQuery([g(p("A"))], "", {presets}),
  describe_preset: describeFilters([g(p("Backlog"), t("tags", "x"))]),
  cycle_direct: wouldCycle(presets, "Backlog", "Backlog"),
  cycle_indirect: wouldCycle(presets, "A", "B"),
  cycle_none: wouldCycle(presets, "Backlog", "Cosy"),
};
// --- the Downloaded pseudo-filter -------------------------------------------

const dl = (opts = {}) => ({downloaded: true, ...opts});
const downloadedCases = {
  downloaded_ids: buildQuery([g(dl())], "", {downloadedIds: [5, 97]}),
  downloaded_empty: buildQuery([g(dl())], "", {downloadedIds: []}),
  downloaded_no_ctx: buildQuery([g(dl())]),
  downloaded_excluded: buildQuery([g(dl({exclude: true}))], "", {downloadedIds: [5]}),
  downloaded_excluded_empty: buildQuery([g(dl({exclude: true}))], "", {downloadedIds: []}),
  downloaded_or_term: buildQuery([g(dl(), t("tags", "x"))], "", {downloadedIds: [1, 2]}),
  downloaded_in_preset: buildQuery([g(p("OnDevice"))], "",
    {presets: {OnDevice: [g(dl())]}, downloadedIds: [7]}),
  describe_downloaded: describeFilters([g(dl({exclude: true}), t("tags", "x"))]),
};

process.stdout.write(JSON.stringify({...cases, ...presetCases, ...downloadedCases}));
