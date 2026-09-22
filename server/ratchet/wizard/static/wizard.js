// The setup wizard's page. Everything it knows comes from /api/state, and
// every button is one call that returns the state afresh — so what is shown
// is always what is true of the machine, not what the page assumes it did.
//
// The pure helpers up top run under plain node for tests; everything that
// touches the DOM is behind the `document` guard at the bottom.
"use strict";

// ---------------- pure helpers (node-tested) ----------------

// What each setting can sensibly point at. A genre kept in a Yes/No column
// is nobody's intention, and offering every column for everything would be
// one way to arrive there by accident.
const TEXTUAL = ["text", "enumeration", "series"];
export const COLUMN_KINDS = {
  genre: TEXTUAL, fandom: TEXTUAL, majchar: TEXTUAL, row: TEXTUAL,
  lastupdate: ["datetime"],
};

// calibre's own Date, which needs no column — at the price of date-added.
export const BUILT_IN_DATE = "timestamp";

/** The choices for one setting: [{value, label}], the empty choice first.
 *
 *  `byLibrary` is {library: [{lookup, name, datatype}]}. A column several
 *  libraries share is offered once, naming them all. A value already saved
 *  that no library has any more is still offered — saying so — rather than
 *  being silently replaced by whatever happens to be first in the list. */
export function columnChoices(byLibrary, kind, saved) {
  const found = new Map();
  for (const [library, columns] of Object.entries(byLibrary || {})) {
    for (const c of columns || []) {
      if (!COLUMN_KINDS[kind].includes(c.datatype)) continue;
      if (!found.has(c.lookup)) found.set(c.lookup, {name: c.name, libraries: []});
      found.get(c.lookup).libraries.push(library);
    }
  }
  const choices = [{value: "", label: "(none)"}];
  for (const [lookup, c] of [...found].sort((a, b) => a[0].localeCompare(b[0])))
    choices.push({value: lookup,
                  label: `${c.name} — ${lookup}  (${c.libraries.join(", ")})`});
  if (kind === "lastupdate")
    choices.push({value: BUILT_IN_DATE,
                  label: "calibre's built-in Date column — replaces the " +
                         "date you added each book, permanently"});
  if (saved && !choices.some(c => c.value === saved))
    choices.push({value: saved, label: `${saved} — not in any library now`});
  return choices;
}

/** What to send as the calibre password: what was typed; or null, meaning
 *  "the one already saved", when nothing was typed and one is saved; or ""
 *  for a server with no accounts. The page is never sent the saved password,
 *  so an empty box has to be able to mean "leave it alone". */
export function passwordToSend(typed, hasSaved) {
  if (typed) return typed;
  return hasSaved ? null : "";
}

/** How a step stands: "done", "todo" (yours to do), "stuck" (something is
 *  wrong), or "waiting" (nothing to do here until an earlier step is). */
export function stepClass({done, problem, blocked}) {
  if (blocked) return "waiting";
  if (problem) return "stuck";
  return done ? "done" : "todo";
}

// What each file in config/ is for, in a line — shown whether or not it
// exists yet, since "what would this even do?" comes before "make one".
export const LIBRARY_FILES = {
  "tag_rules.txt": "What becomes of each tag a story arrives with: renamed, " +
    "moved to a column, deleted, or left alone. Ratchet applies these " +
    "every time a book is added.",
  "tag_scheme.toml": "Your own vocabulary — spellings to fix, tags to move, " +
    "where characters sit. Used by the maintenance scripts in .scripts/.",
  "ao3_names.txt": "Which AO3 character tag means which character. Used by " +
    ".scripts/ao3_characters.py, which can also write it for you.",
};

/** One line summing up a file's findings: what there is of each kind, worst
 *  first, or that there is nothing. */
export function summarise(findings) {
  const count = level => findings.filter(f => f.level === level).length;
  const parts = [["error", "problem"], ["warning", "warning"], ["note", "note"]]
    .map(([level, word]) => [count(level), word])
    .filter(([n]) => n)
    .map(([n, word]) => `${n} ${word}${n === 1 ? "" : "s"}`);
  return parts.length ? parts.join(", ") : "nothing to report";
}

/** Findings in the order worth reading: by line, with whatever is about the
 *  file as a whole (line 0) last. */
export function inReadingOrder(findings) {
  return [...findings].sort((a, b) =>
    (a.line === 0) - (b.line === 0) || a.line - b.line);
}

// ---------------- DOM (absent under node) ----------------

const $ = id => document.getElementById(id);
let key = "";
let state = null;
let columns = null;          // from the last successful calibre test

async function api(path, body) {
  const r = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: {"X-Setup-Key": key, "Content-Type": "application/json"},
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `${r.status} from ${path}`);
  return data;
}

function problem(text) {
  $("problem").textContent = text || "";
  $("problem").hidden = !text;
}

function mark(id, how, status, bad) {
  const step = $(id);
  step.classList.remove("done", "todo", "stuck", "waiting");
  step.classList.add(stepClass(how));
  const line = step.querySelector(".status");
  if (line && status !== undefined) {
    line.textContent = status;
    line.classList.toggle("bad", !!bad);
  }
}

function say(id, text, bad) {
  $(id).textContent = text || "";
  $(id).classList.toggle("bad", !!bad);
}

/** Run something for a button: disabled while it runs, and anything that
 *  went wrong said at the top of the page. Gives back what `work` returned,
 *  or undefined if it failed. */
async function attempt(button, work) {
  problem("");
  button.disabled = true;
  try {
    return await work();
  } catch (e) {
    problem(String(e.message || e));
  } finally {
    button.disabled = false;
  }
}

/** One button, one call that answers with the machine's state afresh: the
 *  page is redrawn from the reply rather than from what it assumes it did. */
function act(button, path, body, saying) {
  return attempt(button, async () => {
    const got = await api(path, body);
    state = got;
    render();
    if (got.result && !got.result.ok && saying)
      say(saying, got.result.message, true);
    return got;
  });
}

function fill(select, choices, value) {
  select.replaceChildren(...choices.map(c => {
    const o = document.createElement("option");
    o.value = c.value; o.textContent = c.label;
    return o;
  }));
  select.value = value;
}

function qr(holder, svg) {
  holder.replaceChildren();
  if (!svg) return;
  const img = document.createElement("img");
  img.alt = "QR code";
  // As an image, not as markup: the page never parses what it is handed.
  img.src = "data:image/svg+xml;utf8," + encodeURIComponent(svg);
  holder.append(img);
}

function renderTailscale() {
  const t = state.tailscale;
  if (!t.installed)
    return mark("stepTailscale", {problem: true},
      "Tailscale is not installed. Get it from tailscale.com/download, sign " +
      "in, then reload this page.", true);
  if (!t.running)
    return mark("stepTailscale", {problem: true},
      `Tailscale is installed but not connected (${t.state || "stopped"}). ` +
      "Open it from the notification area and sign in, then reload.", true);
  mark("stepTailscale", {done: true},
       `Connected. This PC is ${t.name || t.ip} on your tailnet.`);
}

function renderCalibre() {
  const c = state.calibre;
  if (document.activeElement !== $("calUrl") && !$("calUrl").value)
    $("calUrl").value = c.base_url;
  if (!$("calUser").value) $("calUser").value = c.username;
  $("calPass").placeholder = c.has_password ? "(saved — leave empty to keep)" : "";
  $("stepCalibre").classList.remove("done", "todo", "stuck", "waiting");
  $("stepCalibre").classList.add(stepClass({done: state.configured}));
}

function renderColumns() {
  const c = state.calibre;
  fill($("colGenre"), columnChoices(columns, "genre", c.genre_field), c.genre_field);
  fill($("colFandom"), columnChoices(columns, "fandom", c.fandom_field), c.fandom_field);
  fill($("colMajchar"), columnChoices(columns, "majchar", c.majchar_field), c.majchar_field);
  fill($("colRow"), columnChoices(columns, "row", c.row_field), c.row_field);
  fill($("colLastupdate"), columnChoices(columns, "lastupdate", c.lastupdate_field),
       c.lastupdate_field);
}

function renderReach() {
  const blocked = !state.configured;
  const r = state.reach;
  const button = $("btnReach");
  button.disabled = blocked;
  if (state.direct) {
    button.hidden = true;
    return mark("stepReach", {done: true, blocked},
      "Already set up the other way: Ratchet listens on the tailnet address " +
      "itself, let in by a firewall rule of your own. Nothing to do here.");
  }
  button.hidden = false;
  button.textContent = r.enabled ? "Turn it off" : "Turn it on";
  if (!r.known)
    return mark("stepReach", {problem: !blocked, blocked},
      "Tailscale could not be asked. Is it running?", !blocked);
  if (r.other && !r.enabled)
    return mark("stepReach", {problem: !blocked, blocked},
      `Tailscale is already using port ${state.port} for ${r.other}. ` +
      "Turning this on replaces that.", !blocked);
  mark("stepReach", {done: r.enabled, blocked},
       r.enabled ? `On — your tailnet's port ${state.port} reaches Ratchet.`
                 : "Off — only this PC can reach Ratchet.");
}

function renderRun() {
  const blocked = !state.configured;
  $("btnStart").disabled = blocked || state.running;
  say("runStatus", state.running ? "Running." : "Not running.");
  const a = state.autostart;
  $("autostartRow").hidden = !a.applicable;
  $("btnAutostart").disabled = blocked;
  $("btnAutostart").textContent = a.enabled ? "Stop starting it when I log in"
                                            : "Start it when I log in";
  say("autostartStatus", a.enabled ? "Starts when you log in." : "");
  mark("stepRun", {done: state.running && (a.enabled || !a.applicable), blocked});
}

function renderPhone() {
  const blocked = !state.configured;
  const p = state.phone;
  $("btnApk").disabled = blocked;
  $("btnApk").textContent = state.apk.present ? "Fetch the newest app"
                                              : "Get the app ready";
  if (!$("apkStatus").classList.contains("bad"))
    say("apkStatus", state.apk.present
      ? `The app is ready (${(state.apk.size / 1048576).toFixed(1)} MB).` : "");
  const ready = !blocked && state.apk.present && state.running && !!p.apk_url;
  $("pairing").hidden = !ready;
  if (ready) {
    qr($("qrApk"), p.apk_qr);
    qr($("qrToken"), p.token_qr);
    $("apkUrl").textContent = p.apk_url;
    $("apkUrlTyped").textContent = p.apk_url;
    $("address").textContent = p.address;
    $("addressFull").textContent = p.address_full && p.address_full !== p.address
      ? `(or in full: ${p.address_full})` : "";
    $("token").textContent = p.token;
  }
  mark("stepPhone", {done: ready, blocked});
}

let checked = null;          // the last check's result, until a file changes

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderLibrary() {
  const blocked = !state.configured;
  $("btnCheck").disabled = blocked;
  const list = $("libraryFiles");
  list.replaceChildren();
  for (const [name, what] of Object.entries(LIBRARY_FILES)) {
    const file = state.library[name];
    const item = el("li");
    const head = el("div", "row");
    head.append(el("b", "mono", name));
    const button = el("button", "small",
                      file.exists ? "Open" : "Create from the example");
    button.disabled = blocked;
    button.onclick = () => attempt(button, async () => {
      const made = !file.exists;
      const got = await api(made ? "/api/library/create" : "/api/library/open",
                            {file: name});
      if (got.ok === false) throw new Error(got.message);
      // What was checked is about to change, or may be: a stale list of
      // problems beside a file being edited is worse than none.
      checked = null;
      state = await api("/api/state");
      render();
    });
    head.append(button);
    if (!file.exists) head.append(el("span", "status", "not made yet"));
    item.append(head, el("p", "hint", what));
    list.append(item);
  }

  const out = $("findings");
  out.replaceChildren();
  if (!checked) return mark("stepLibrary", {done: false, blocked});
  if (!checked.compared)
    out.append(el("p", "hint",
      "calibre could not be asked, so the files were only checked against " +
      "themselves — not against the tags and columns your library really has."));
  let trouble = 0;
  for (const [name, got] of Object.entries(checked.files)) {
    if (!got.exists) continue;
    const block = el("div", "file");
    block.append(el("h3", "", `${name} — ${summarise(got.findings)}`));
    const items = el("ul", "findings");
    for (const f of inReadingOrder(got.findings)) {
      const line = el("li", f.level);
      line.append(el("span", "where", f.line ? `line ${f.line}` : ""),
                  el("span", "", f.message));
      items.append(line);
      if (f.level !== "note") trouble++;
    }
    block.append(items);
    out.append(block);
  }
  mark("stepLibrary", {done: !trouble, problem: !!trouble, blocked});
}

function render() {
  renderTailscale();
  renderCalibre();
  renderReach();
  renderRun();
  renderPhone();
  renderLibrary();
}

async function testCalibre() {
  problem("");
  const line = $("stepCalibre").querySelector(".status");
  line.textContent = "Trying…"; line.classList.remove("bad");
  $("btnTest").disabled = true;
  try {
    const got = await api("/api/calibre/test", {
      base_url: $("calUrl").value,
      username: $("calUser").value,
      password: passwordToSend($("calPass").value, state.calibre.has_password),
    });
    line.textContent = got.message;
    line.classList.toggle("bad", !got.ok);
    $("libraryBlock").hidden = !got.ok;
    if (!got.ok) return;
    columns = got.columns;
    const saved = state.calibre.library_id;
    fill($("calLibrary"),
         [{value: "", label: "(whichever calibre opens on)"},
          ...got.libraries.map(l => ({value: l.id, label: l.name}))],
         got.libraries.some(l => l.id === saved) ? saved : "");
    renderColumns();
  } catch (e) {
    problem(String(e.message || e));
  } finally {
    $("btnTest").disabled = false;
  }
}

async function save() {
  const got = await act($("btnSave"), "/api/save", {
    calibre: {
      base_url: $("calUrl").value, username: $("calUser").value,
      library_id: $("calLibrary").value,
      genre_field: $("colGenre").value, fandom_field: $("colFandom").value,
      majchar_field: $("colMajchar").value, row_field: $("colRow").value,
      lastupdate_field: $("colLastupdate").value,
    },
    password: passwordToSend($("calPass").value, state.calibre.has_password),
  });
  if (!got) return;
  $("calPass").value = "";
  say("saveStatus", state.running
    ? "Saved. Ratchet is running on the old settings — quit it from its " +
      "icon by the clock and start it again to pick these up."
    : "Saved.");
}

async function init() {
  // The key arrives in the fragment, which a browser never sends anywhere,
  // and is taken out of the address bar so that it is not left in history.
  key = location.hash.slice(1);
  history.replaceState(null, "", location.pathname);
  if (!key) {
    problem("Open the wizard from the window Setup.bat started — this page " +
            "needs the key in the address it prints.");
    return;
  }
  try { state = await api("/api/state"); }
  catch (e) { problem(String(e.message || e)); return; }
  render();

  $("btnTest").onclick = testCalibre;
  $("btnSave").onclick = save;
  $("btnReach").onclick = () =>
    act($("btnReach"), "/api/reach", {enable: !state.reach.enabled});
  $("btnStart").onclick = async () => {
    await act($("btnStart"), "/api/service/start", {}, "runStatus");
    // It takes a few seconds to come up; ask again rather than guess.
    for (let i = 0; i < 8 && !state.running; i++) {
      await new Promise(r => setTimeout(r, 1500));
      state = await api("/api/state");
      render();
    }
  };
  $("btnAutostart").onclick = () =>
    act($("btnAutostart"), "/api/autostart", {enable: !state.autostart.enabled},
        "autostartStatus");
  $("btnApk").onclick = () => {
    say("apkStatus", "Downloading…");
    return act($("btnApk"), "/api/apk/download", {}, "apkStatus");
  };
  $("btnCopyToken").onclick = () =>
    navigator.clipboard.writeText(state.phone.token);
  $("btnCheck").onclick = () => attempt($("btnCheck"), async () => {
    say("checkStatus", "Reading your library to compare against — a few seconds…");
    try { checked = await api("/api/library/check", {}); }
    finally { say("checkStatus", ""); }
    render();
  });

  // A saved setup can be re-tested at once; a new one waits for an address.
  if (state.configured) testCalibre();
}

// Last, so every const above it is initialised. Node (the tests) has no
// document and only imports the pure helpers.
if (typeof document !== "undefined") init();
