// The shell's first page: asks where the Ratchet server is, once, and hands
// the answer to the native side (ShellBridge), which reloads the app into it.
//
// The address cannot be built into the app — that would mean an APK per
// person, each built with a JDK and the Android SDK — so it is asked for
// here instead, and one APK serves anybody.
//
// Bundled into the APK (changes here need a rebuild). The pure helper up top
// runs under plain node for tests — everything DOM-touching is behind the
// `document` guard at the bottom.
"use strict";

// What the service listens on unless its config says otherwise, and so what
// a bare hostname almost certainly means.
export const DEFAULT_PORT = 8484;

/** What someone typed, as the origin the app should load: {origin}, or
 *  {error} saying what is wrong with it.
 *
 *  Forgiving about form, because this is typed on a phone: "my-pc.ts.net",
 *  "my-pc.ts.net:8484", "http://my-pc.ts.net:8484/ui/" and "100.64.0.1" all
 *  mean the same server. A bare name gets http:// and the default port. A
 *  scheme that was typed is taken at its word — "https://my-pc.ts.net" is
 *  `tailscale serve` on 443, and adding :8484 to it would be wrong. */
export function normaliseServer(text) {
  const typed = String(text == null ? "" : text).trim();
  if (!typed) return {error: "Enter the server's address."};

  const scheme = /^([a-z][a-z0-9+.-]*):\/\//i.exec(typed);
  if (scheme && !/^https?$/i.test(scheme[1]))
    return {error: "The address has to start with http:// or https://."};

  let url;
  try { url = new URL(scheme ? typed : "http://" + typed); }
  catch (e) { return {error: "That does not look like an address."}; }
  if (!url.hostname) return {error: "That does not look like an address."};

  // Asked of what was typed, not of url.port: the parser reports the
  // scheme's own port (":80") as no port at all.
  const rest = scheme ? typed.slice(scheme[0].length) : typed;
  const namedPort = /:\d+(\/|$)/.test(rest.split(/[?#]/)[0]);
  if (!scheme && !namedPort) url.port = String(DEFAULT_PORT);

  return {origin: url.origin};
}

// ---------------- DOM (absent under node) ----------------

function $(id) { return document.getElementById(id); }

/** Reachable at all is the question, so an opaque no-cors probe is enough —
 *  it resolves only when something answered at that address. */
async function answers(origin) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 6000);
  try {
    await fetch(origin + "/health", {mode: "no-cors", signal: ctl.signal,
                                     cache: "no-store"});
    return true;
  } catch (e) { return false; }
  finally { clearTimeout(timer); }
}

function say(text) { $("status").textContent = text; }

function use(origin) {
  const problem = window.RatchetShell.setServer(origin);
  // On success the app is already reloading into the server.
  if (problem) say("Could not save that — " + problem + ".");
}

async function connect() {
  $("btnAnyway").hidden = true;
  const got = normaliseServer($("addr").value);
  if (got.error) { say(got.error); return; }

  say("Looking for " + got.origin + " …");
  $("btnConnect").disabled = true;
  const up = await answers(got.origin);
  $("btnConnect").disabled = false;
  if (up) { use(got.origin); return; }

  // Not fatal: the address may be right and the PC merely off. Saving it
  // anyway lands on the offline page, which retries by itself.
  say("Nothing answered at " + got.origin + ". Check that Tailscale is " +
      "connected on this device and that Ratchet is running on the PC — " +
      "or check the address for typos.");
  $("btnAnyway").hidden = false;
  $("btnAnyway").onclick = () => use(got.origin);
}

function init() {
  if (!window.RatchetShell) {
    say("This page is part of the Ratchet app and does nothing in a browser.");
    $("btnConnect").disabled = true;
    return;
  }
  // Coming back to fix an address starts from the one being fixed.
  $("addr").value = window.RatchetShell.getPreviousServer() || "";
  $("btnConnect").onclick = connect;
  $("addr").onkeydown = e => { if (e.key === "Enter") connect(); };
}

// Last, so every const above it is initialised. Node (the tests) has no
// document and only imports the pure helper.
if (typeof document !== "undefined") init();
