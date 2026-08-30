// A boot that cannot reach the service must still leave a view on screen.
// Exercised from tests/test_boot.py via node.
import { localStorageStore } from "./dom_stub.mjs";

// A stored token, so boot() gets as far as asking the service for its config
// instead of stopping at the login screen.
localStorageStore.set("ratchet_token", "seeded");

const out = {};
const { viewNow } = await import("../ratchet/static/core.js");
out.before = viewNow();          // nothing shown yet: the app has not booted

// dom_stub's fetch rejects, so /ui-config fails the way an unreachable
// service does — the case that used to leave every section hidden.
await import("../ratchet/static/app.js");
// boot() is async and started during that import; let its rejection settle.
for (let i = 0; i < 20; i++) await Promise.resolve();
await new Promise(r => setTimeout(r, 0));

out.after = viewNow();
process.stdout.write(JSON.stringify(out));
