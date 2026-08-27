// Light/dark toggle. The palette lives in ui.css as custom properties; this
// only decides which set is active by stamping data-theme on <html>.
"use strict";
import { $ } from "./core.js";

const THEME_KEY = "ficsync_theme";
const media = window.matchMedia("(prefers-color-scheme: dark)");

/** An explicit choice wins; otherwise follow the device. */
function effective() {
  const stored = localStorage.getItem(THEME_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return media.matches ? "dark" : "light";
}

// Monochrome inline icons (currentColor follows the theme tokens); emoji
// would render as coloured glyphs on Android.
const MOON_SVG =
  '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">' +
  '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';
const SUN_SVG =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"' +
  ' stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/>' +
  '<path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2' +
  'M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';

function apply(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  // The wordmark is hand-drawn per theme rather than filtered.
  const logo = document.querySelector("header h1 .logo");
  if (logo) logo.src = theme === "dark" ? "logo-dark.png" : "logo-light.png";
  // Keep the browser chrome (address bar, PWA title bar) in step.
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", theme === "dark" ? "#000000" : "#ffffff");
  const btn = $("btnTheme");
  if (btn) {
    // Shows the CURRENT theme — sun in light mode, moon in dark — matching
    // the sound toggle, which also displays state rather than action.
    btn.innerHTML = theme === "dark" ? MOON_SVG : SUN_SVG;
    const label = theme === "dark" ? "switch to light mode" : "switch to dark mode";
    btn.title = label;
    btn.setAttribute("aria-label", label);
    btn.setAttribute("aria-pressed", String(theme === "dark"));
  }
}

export function initTheme() {
  apply(effective());
  // Track the device setting, but only while the user has not chosen one.
  media.addEventListener("change", () => {
    if (!localStorage.getItem(THEME_KEY)) apply(effective());
  });
  const btn = $("btnTheme");
  if (!btn) return;
  btn.onclick = () => {
    const next = effective() === "dark" ? "light" : "dark";
    localStorage.setItem(THEME_KEY, next);
    apply(next);
  };
}
