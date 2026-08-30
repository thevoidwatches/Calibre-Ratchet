// Exercised from tests/test_backchain.py via node.
import "./dom_stub.mjs";
const { viewBehind, ROOT_ENTRY } = await import("../ratchet/static/core.js");

const views = ["detail", "pickcol", "pickval", "browse", "token"];
const out = {root_entry: ROOT_ENTRY};
for (const v of views) out[v] = viewBehind(v);
// Walking back repeatedly must terminate rather than cycle.
let at = "detail", walk = [];
for (let i = 0; i < 6 && at !== null; i++) { at = viewBehind(at); walk.push(at); }
out.walk_from_detail = walk;
out.unknown = viewBehind("nonsense");
process.stdout.write(JSON.stringify(out));
