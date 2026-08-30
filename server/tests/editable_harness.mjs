// Which columns the book page offers editors for, and in what order.
import "./dom_stub.mjs";
const { state, isWritable } = await import("../ratchet/static/core.js");
const { editableColumns } = await import("../ratchet/static/detail.js");

// A book carrying every column the Fanfiction library uses.
const META = {
  tags: ["Content.Erotica"],
  user_metadata: {
    "#fandom": {datatype: "text", is_multiple: "|", name: "Fandom", "#value#": ["Worm"]},
    "#genre": {datatype: "text", is_multiple: "|", name: "Genre", "#value#": ["AU"]},
    "#majchar": {datatype: "text", is_multiple: "|", name: "Major Characters", "#value#": []},
    "#readinglist": {datatype: "enumeration", name: "Reading List", "#value#": "Unread"},
    "#downloaded": {datatype: "bool", name: "Downloaded", "#value#": null},
  },
};

const fields = () => editableColumns(META).map(c => c.field);
const out = {};

state.writable = ["title", "tags", "rating", "#*"];
state.genreField = "#genre";

state.editable = [];
out.unconfigured = fields();

state.editable = ["#majchar", "tags"];
out.configured_selects_and_orders = fields();

state.editable = ["#readinglist", "#majchar", "#genre", "tags", "#fandom"];
out.configured_full_order = fields();

// A column named in editable_fields but not permitted by writable_fields must
// still not get an editor: the list chooses, it does not grant.
state.writable = ["tags"];
state.editable = ["#majchar", "tags"];
out.editable_cannot_grant = fields();

// ...nor may it conjure a column the book does not have.
state.writable = ["#*", "tags"];
state.editable = ["#nosuchcolumn", "tags"];
out.unknown_field_ignored = fields();

// bool columns have no editor whatever the config says.
state.editable = ["#downloaded", "tags"];
out.bool_column_skipped = fields();

// The description is orderable like any other field, so something can sit
// below it — but it is not an editor and appears only when the book has one.
const WITH_DESC = Object.assign({}, META, {comments: "<p>A blurb.</p>"});
const descFields = () => editableColumns(WITH_DESC).map(c => c.field);

state.writable = ["title", "tags", "rating", "#*"];
state.editable = [];
out.description_last_by_default = descFields();

state.editable = ["#fandom", "#majchar", "#genre", "tags", "comments", "#readinglist"];
out.description_takes_its_place = descFields();
out.description_absent_when_empty = fields();      // META has no comments

// A configured list that omits it hides it, as for any other field.
state.editable = ["tags", "#genre"];
out.description_omitted = descFields();

process.stdout.write(JSON.stringify(out));
