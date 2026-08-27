// Loads the UI's module graph under a stub browser.
//
// `node --check` only parses; it cannot see a call to a function that was
// moved to another module, or a name that no longer exists. Actually
// evaluating every module catches both, and any import/export mismatch.
import "./dom_stub.mjs";

const failures = [];
process.on("unhandledRejection", e => failures.push("unhandled rejection: " + e.message));

await import("../ratchet/static/app.js");
await new Promise(r => setTimeout(r, 50));   // let boot()'s microtasks settle

if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log("ok");
