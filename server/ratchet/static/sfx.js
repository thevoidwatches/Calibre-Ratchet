// Sounds: outcomes (success/refused/error), navigation (page-shift for a whole
// new page, select for smaller moves), and a tap for everything else clickable.
// Files are dropped into static/sfx/ by hand (see its README); each is
// optional, and a missing one simply stays silent.
"use strict";
import { $, UNAUTHORIZED_EVENT, VIEW_CHANGED_EVENT } from "./core.js";

const MUTE_KEY = "ratchet_muted";
// Several interchangeable taps, picked at random, so repeated button presses
// do not sound like a machine.
const TAPS = ["tap_01", "tap_02", "tap_03", "tap_04", "tap_05"];
const NAMES = ["success", "refused", "error", "page-shift", "select", ...TAPS];
// wav first: it is what these sounds ship as, so the probe usually stops on
// its first try instead of collecting 404s.
const EXTS = ["wav", "mp3", "ogg", "m4a"];

let muted = localStorage.getItem(MUTE_KEY) === "1";
const cache = {};        // name -> HTMLAudioElement | null (null = not present)

/** Find whichever extension the user actually dropped in, once per name. */
async function resolve(name) {
  if (name in cache) return cache[name];
  cache[name] = null;
  for (const ext of EXTS) {
    const url = "sfx/" + name + "." + ext;
    try {
      // HEAD avoids pulling the file body just to test for existence; the
      // static mount answers it the same as GET.
      const r = await fetch(url, {method: "HEAD"});
      if (r.ok) {
        const a = new Audio(url);
        a.preload = "auto";
        cache[name] = a;
        break;
      }
    } catch (e) { /* keep trying the next extension */ }
  }
  return cache[name];
}

export async function play(name) {
  if (name === "tap") name = TAPS[Math.floor(Math.random() * TAPS.length)];
  if (muted || !NAMES.includes(name)) return;
  const audio = await resolve(name);
  if (!audio) return;
  try {
    audio.currentTime = 0;
    // Mobile browsers reject playback without a prior user gesture; every
    // call site here follows a button tap, but never let a rejection surface
    // as an unhandled promise.
    await audio.play();
  } catch (e) { /* silence is an acceptable outcome for a sound effect */ }
}

/** Pick the sound that matches a decision payload from /check or /update. */
export function playForDecision(d) {
  if (!d || !d.action) return;
  if (d.action.startsWith("refuse")) play("refused");
  else if (d.updated === true) play("success");
}

// Monochrome inline icons; the speaker shows the CURRENT state (slashed while
// muted), which is the convention for volume indicators.
const SPEAKER =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"' +
  ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" fill="currentColor"/>' +
  '<path d="M15.5 8.5a5 5 0 0 1 0 7M18.4 5.6a9 9 0 0 1 0 12.8"/></svg>';
const SPEAKER_MUTED =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"' +
  ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" fill="currentColor"/>' +
  '<path d="M23 9l-6 6M17 9l6 6"/></svg>';

function render() {
  const btn = $("btnMute");
  btn.innerHTML = muted ? SPEAKER_MUTED : SPEAKER;
  const label = muted ? "unmute sounds" : "mute sounds";
  btn.title = label;
  btn.setAttribute("aria-label", label);
  btn.setAttribute("aria-pressed", String(muted));
}

/** Resolve and preload every sound once, on the first tap.
 *
 *  Two reasons this happens on a gesture rather than at load: mobile browsers
 *  only allow media to be prepared after the user has interacted, and an
 *  update can run for minutes — without warming, the chime would land several
 *  round trips (two 404 probes plus the fetch) after the update finished.
 */
function warm() {
  for (const name of NAMES) {
    resolve(name).then(a => { if (a) a.load(); }).catch(() => {});
  }
}

// Controls whose click ends in a view change or a collapse, which sound for
// themselves — a tap here as well would double up on one action.
const SOUNDED_ELSEWHERE = [
  "[data-nav]",        // back / cancel
  "#results li",       // open a book
  "#colList li",       // pick a column
  "#valTree .node",    // pick a value
  "#btnAddFilter",
  ".orbtn",            // "+ or"
  "#btnSettings",
  "#btnMute",          // muting should not itself make a noise
  "summary",           // handled as a collapse below
  "#btnToggleFilters",
].join(", ");

const COLLAPSE = "summary, #btnToggleFilters";
const TAPPABLE = "button, .chip, .node, select, input[type=checkbox]";

/** One delegated listener rather than a sound wired into every handler: new
 *  buttons then get the tap for free, and the exceptions stay in one list. */
function routeClick(e) {
  const t = e.target;
  if (!(t instanceof Element)) return;
  if (t.closest(COLLAPSE)) { play("select"); return; }
  if (t.closest(SOUNDED_ELSEWHERE)) return;
  if (t.closest(TAPPABLE)) play("tap");
}

export function initSfx() {
  document.addEventListener("pointerdown", warm, {once: true});
  document.addEventListener("keydown", warm, {once: true});
  document.addEventListener("click", routeClick);

  // Navigation: a whole new page, except stepping deeper into the filter
  // picker, which is a smaller move within the same task.
  window.addEventListener(VIEW_CHANGED_EVENT, e =>
    play(e.detail && e.detail.view === "pickval" ? "select" : "page-shift"));

  // A rejected token is a refusal like any other. On a cold load with a bad
  // stored token this fires before the first tap, so the browser may swallow
  // it; submitting a wrong token by hand always sounds.
  window.addEventListener(UNAUTHORIZED_EVENT, () => play("refused"));

  const btn = $("btnMute");
  if (!btn) return;
  render();
  btn.onclick = () => {
    muted = !muted;
    localStorage.setItem(MUTE_KEY, muted ? "1" : "0");
    render();
    if (!muted) play("success");   // confirm audibly that sound is back on
  };
}
