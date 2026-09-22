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

async function fetchWithin(ms, url, options) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), ms);
  try { return await fetch(url, {...options, signal: ctl.signal, cache: "no-store"}); }
  finally { clearTimeout(timer); }
}

/** What is at this address: "ratchet", "other", or "nothing".
 *
 *  Asks /ping, which only Ratchet answers with {ratchet: true}. "Did
 *  anything answer" is not enough: with Tailscale carrying the traffic
 *  (`tailscale serve`) it answers by itself whenever the PC is on, Ratchet
 *  running or not — and a mistyped port can land on calibre, which answers
 *  too. Telling "other" from "nothing" is for the message: one means check
 *  the address, the other means check that anything is switched on.
 *
 *  (offline.js has its own copy of the /ping half. It has to: that file is
 *  inlined whole into error.html and cannot import.) */
async function whatIsAt(origin) {
  try {
    const r = await fetchWithin(6000, origin + "/ping", {});
    if (r.ok && (await r.json()).ratchet === true) return "ratchet";
    return "other";
  } catch (e) { /* refused, timed out, not JSON, or unreadable */ }
  try {
    // Opaque, so it resolves only if something answered at all.
    await fetchWithin(4000, origin + "/", {mode: "no-cors"});
    return "other";
  } catch (e) { return "nothing"; }
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
  const found = await whatIsAt(got.origin);
  $("btnConnect").disabled = false;
  if (found === "ratchet") { use(got.origin); return; }

  // Not fatal either way: the address may be right and Ratchet merely
  // stopped. Saving it anyway lands on the offline page, which retries.
  say(found === "other"
    ? "Something answered at " + got.origin + ", but it is not Ratchet. " +
      "Check the name and the port — or, if they are right, that Ratchet " +
      "is running on the PC."
    : "Nothing answered at " + got.origin + ". Check that Tailscale is " +
      "connected on this device and that the PC is on — or check the " +
      "address for typos.");
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
