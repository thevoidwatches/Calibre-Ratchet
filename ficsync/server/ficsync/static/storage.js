// Device-side book storage, active only inside the Android shell.
//
// Layout: a visible top-level folder in shared storage, one subfolder per
// calibre library —
//
//     /storage/emulated/0/Ratchet/<Library>/
//
// visible so Moon+ and file managers can browse it. Real paths there need
// "All files access" on Android 11+, which the shell's RatchetNative plugin
// checks for and requests; folder creation itself goes through the stock
// Filesystem plugin. In a plain browser every export here is an inert no-op.
"use strict";
import { $, state } from "./core.js";

const ROOT = "Ratchet";

const plugins = () => (window.Capacitor && window.Capacitor.Plugins) || null;

export const inShell = () =>
  !!(plugins() && plugins().Filesystem && plugins().RatchetNative);

async function hasAccess() {
  try { return (await plugins().RatchetNative.hasAllFilesAccess()).granted; }
  catch (e) { return false; }
}

/** Create Ratchet/<library>/ for every library the server reports. */
async function createFolders() {
  const fs = plugins().Filesystem;
  for (const lib of state.libraries || []) {
    try {
      await fs.mkdir({
        path: ROOT + "/" + lib.id,
        directory: "EXTERNAL_STORAGE",
        recursive: true,
      });
    } catch (e) {
      // "Directory exists" is success; anything else shows in the banner
      // rather than failing silently.
      const msg = String((e && e.message) || e);
      if (!/exist/i.test(msg)) throw new Error(lib.id + ": " + msg);
    }
  }
}

function banner(show, text) {
  const el = $("storageBanner");
  if (!el) return;
  el.hidden = !show;
  if (text) $("storageBannerText").textContent = text;
}

/** Make sure the folder tree exists, asking for the storage grant if needed.
 *  Runs after the library list loads, and again on each return to the app so
 *  granting access in Settings is picked up without a restart. */
export async function ensureStorage() {
  if (!inShell()) return;
  if (!(await hasAccess())) {
    banner(true, "Ratchet needs storage access to keep books in a folder " +
                 "Moon+ can read.");
    return;
  }
  try {
    await createFolders();
    banner(false);
  } catch (e) {
    banner(true, "Storage is granted but creating the Ratchet folder failed — " +
                 (e && e.message ? e.message : e));
  }
}

/** Open a URL outside the WebView (system browser). Falls back to a normal
 *  navigation in a plain browser. */
export function openExternal(url) {
  if (inShell()) return plugins().RatchetNative.openUrl({url});
  window.location.href = url;
}

export function initStorage() {
  const btn = $("btnGrantStorage");
  if (btn) btn.onclick = () => plugins().RatchetNative.openAllFilesSettings();
  // Returning from the Settings screen fires visibilitychange; re-check then.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") ensureStorage();
  });
}
