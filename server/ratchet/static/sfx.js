// Sounds: outcomes (success/refused/error), select for moving about — a new
// page, a step through the filter picker, a section opened or closed, the
// cover overlay, a choice from a dropdown — and a tap for everything else
// clickable. Every error message sounds by itself, through core.js's event.
// Files are dropped into static/sfx/ by hand (see its README); each is
// optional, and a missing one stays silent.
"use strict";
import { $, ERROR_EVENT, UNAUTHORIZED_EVENT, VIEW_CHANGED_EVENT } from "./core.js";

const MUTE_KEY = "ratchet_muted";
const VOLUME_KEY = "ratchet_volume";
// Several interchangeable taps, picked at random, so repeated button presses
// do not sound like a machine.
const TAPS = ["tap_01", "tap_02", "tap_03", "tap_04", "tap_05"];
const NAMES = ["success", "refused", "error", "select", ...TAPS];
// wav first: it is what these sounds ship as, so the probe usually stops on
// its first try instead of collecting 404s.
const EXTS = ["wav", "mp3", "ogg", "m4a"];

let muted = localStorage.getItem(MUTE_KEY) === "1";
const cache = {};        // name -> HTMLAudioElement | null (null = not present)

// The slider's own 0..1 position — what the reader sets and what is stored.
// It is NOT handed to the audio element directly: see gain().
function storedVolume() {
  const raw = parseFloat(localStorage.getItem(VOLUME_KEY));
  return Number.isFinite(raw) ? Math.min(1, Math.max(0, raw)) : 1;
}
let volume = storedVolume();

// Full slider is half of what the device could actually output: these sounds
// are UI feedback, and at a phone's full volume the raw files are shouting.
const MAX_GAIN = 0.5;

/** Slider position -> amplitude.
 *
 *  Squared, because an audio element's volume is linear amplitude while
 *  hearing is closer to logarithmic: mapping the slider straight across makes
 *  the bottom half of its travel sound barely quieter than the top. Squaring
 *  gives the low end somewhere to go. */
function gain() {
  return MAX_GAIN * volume * volume;
}

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
  if (muted || volume === 0 || !NAMES.includes(name)) return;
  const audio = await resolve(name);
  if (!audio) return;
  try {
    audio.volume = gain();
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
  // Volume 0 is muted in every way that matters, so the icon says so.
  const silent = muted || volume === 0;
  btn.innerHTML = silent ? SPEAKER_MUTED : SPEAKER;
  const label = (silent ? "unmute sounds" : "mute sounds") + " (hold for volume)";
  btn.title = label;
  btn.setAttribute("aria-label", label);
  btn.setAttribute("aria-pressed", String(silent));
  const range = $("volRange"), value = $("volValue");
  if (range) range.value = String(Math.round(volume * 100));
  if (value) value.textContent = Math.round(volume * 100) + "%";
}

// ---- volume popover -------------------------------------------------------
//
// A hold on the speaker rather than a permanent slider: volume is set once in
// a while, and the header has three buttons and a library selector to fit on
// a phone already.

const HOLD_MS = 450;

function volumeOpen() { return !$("volPop").hidden; }

function closeVolume() {
  const pop = $("volPop");
  if (pop) pop.hidden = true;
}

function openVolume() {
  const pop = $("volPop");
  if (!pop) return;
  render();                 // slider starts at the stored value
  pop.hidden = false;
  $("volRange").focus();
  // The hold that opens this is the one press on the speaker that should be
  // heard: it is reaching for sound, not switching it off.
  play("tap");
}

function setVolume(next) {
  volume = Math.min(1, Math.max(0, next));
  localStorage.setItem(VOLUME_KEY, String(volume));
  // Reaching for the slider means wanting sound; staying muted would make it
  // look broken.
  if (volume > 0) muted = false;
  localStorage.setItem(MUTE_KEY, muted ? "1" : "0");
  render();
}

function initVolume() {
  const btn = $("btnMute"), pop = $("volPop"), range = $("volRange");
  if (!btn || !pop || !range) return;

  let timer = null, opened = false;
  const cancel = () => { clearTimeout(timer); timer = null; };

  btn.addEventListener("pointerdown", () => {
    opened = false;
    timer = setTimeout(() => { opened = true; openVolume(); }, HOLD_MS);
  });
  for (const ev of ["pointerup", "pointercancel", "pointerleave"])
    btn.addEventListener(ev, cancel);
  // A hold has already acted; the click that follows must not also toggle mute.
  btn.addEventListener("click", e => {
    if (!opened) return;
    opened = false;
    e.stopImmediatePropagation();
    e.preventDefault();
  }, true);
  // The desktop equivalent of a long press.
  btn.addEventListener("contextmenu", e => { e.preventDefault(); openVolume(); });

  range.addEventListener("input", () => setVolume(Number(range.value) / 100));
  // Preview on release rather than on every step, which would stutter.
  range.addEventListener("change", () => play("tap"));

  document.addEventListener("pointerdown", e => {
    if (!volumeOpen()) return;
    if (!e.target.closest("#volPop") && !e.target.closest("#btnMute"))
      closeVolume();
  });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && volumeOpen()) closeVolume();
  });
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
  "#btnFreeValue",     // "use" a typed value: lands on the book list
  ".gofilter",         // a book-page value that filters the list
  "#btnAddFilter",
  ".orbtn",            // "+ or"
  "#btnSettings",
  "#btnMute",          // muting should not itself make a noise
  "summary",           // handled as a collapse below
  "#btnToggleFilters",
].join(", ");

const COLLAPSE = "summary, #btnToggleFilters";
const TAPPABLE = "button, .chip, .node, select, input[type=checkbox]";
// Looks tappable, does nothing: a filter-bar chip's body — only its × acts.
// A sound for a press that changes nothing would suggest it should have.
const INERT = "#filterChips .chip";

/** One delegated listener rather than a sound wired into every handler: new
 *  buttons then get the tap for free, and the exceptions stay in one list. */
function routeClick(e) {
  const t = e.target;
  if (!(t instanceof Element)) return;
  if (t.closest(COLLAPSE)) { play("select"); return; }
  if (t.closest(SOUNDED_ELSEWHERE)) return;
  // The nearest control, so a chip's × (a button) still taps while the chip
  // around it stays quiet.
  const hit = t.closest(TAPPABLE);
  if (hit && !hit.matches(INERT)) play("tap");
}

export function initSfx() {
  document.addEventListener("pointerdown", warm, {once: true});
  document.addEventListener("keydown", warm, {once: true});
  document.addEventListener("click", routeClick);

  window.addEventListener(VIEW_CHANGED_EVENT, () => play("select"));

  // A rejected token is a refusal like any other. On a cold load with a bad
  // stored token this fires before the first tap, so the browser may swallow
  // it; submitting a wrong token by hand always sounds.
  window.addEventListener(UNAUTHORIZED_EVENT, () => play("refused"));

  // Every message in the error box, wherever it came from — including ones
  // nobody tapped for, such as a book's story state failing to load.
  window.addEventListener(ERROR_EVENT,
                          e => play((e.detail && e.detail.kind) || "error"));

  const btn = $("btnMute");
  if (!btn) return;
  initVolume();
  render();
  btn.onclick = () => {
    // Unmuting at zero volume would be silent and look broken; give it a
    // usable level back.
    if (muted && volume === 0) setVolume(1);
    muted = !muted;
    localStorage.setItem(MUTE_KEY, muted ? "1" : "0");
    render();
    if (!muted) play("success");   // confirm audibly that sound is back on
  };
}
