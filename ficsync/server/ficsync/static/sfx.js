// Outcome sounds. Files are dropped into static/sfx/ by hand (see its
// README); each is optional, and a missing one simply stays silent.
"use strict";
import { $, UNAUTHORIZED_EVENT } from "./core.js";

const MUTE_KEY = "ficsync_muted";
const NAMES = ["success", "refused", "error"];
const EXTS = ["mp3", "ogg", "wav", "m4a"];

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

function render() {
  const btn = $("btnMute");
  // Labelled by the action the tap performs, not the current state.
  btn.textContent = muted ? "Unmute" : "Mute";
  btn.title = muted ? "sounds are off" : "sounds are on";
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

export function initSfx() {
  document.addEventListener("pointerdown", warm, {once: true});
  document.addEventListener("keydown", warm, {once: true});

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
