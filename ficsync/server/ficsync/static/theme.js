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
    // Labelled by the action it performs, like the sound toggle.
    btn.textContent = theme === "dark" ? "Light" : "Dark";
    btn.title = theme === "dark" ? "switch to light mode" : "switch to dark mode";
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
