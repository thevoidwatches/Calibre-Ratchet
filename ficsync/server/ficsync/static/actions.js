// Check / Update / epub download + decision rendering.
"use strict";
import { $, state, api, apiJson, err, clearErr } from "./core.js";
import { play, playForDecision } from "./sfx.js";

/** The Update button is only emphasised once a Check has actually found new
 *  chapters — otherwise it is the loudest thing on a page where there may be
 *  nothing to do. */
export function setUpdateAvailable(available) {
  state.updateAvailable = available;
  $("btnUpdate").classList.toggle("primary", available);
}

function busy(msg) {
  $("busy").hidden = !msg;
  $("busy").textContent = msg || "";
  for (const id of ["btnCheck", "btnUpdate", "btnEpub"]) $(id).disabled = !!msg;
}

function renderDecision(d) {
  const box = $("decision"); box.hidden = false; box.innerHTML = "";
  const head = document.createElement("div");
  head.className = d.action && d.action.startsWith("refuse") ? "warn" : "box";
  const lines = [];
  if (d.updated === true)
    lines.push("✓ UPDATED — now " + d.final_chapter_count + " chapters");
  if (d.updated === false && d.dry_run) lines.push("(dry run — nothing written)");
  lines.push("decision: " + d.action);
  lines.push("local " + d.local_count + " / site " + d.remote_count + " chapters");
  for (const r of d.reasons || []) lines.push(r);
  head.textContent = lines.join("\n");
  head.style.whiteSpace = "pre-wrap";
  box.append(head);
  const list = (title, chapters) => {
    if (!chapters || !chapters.length) return;
    const el = document.createElement("div"); el.className = "box";
    const h = document.createElement("b"); h.textContent = title; el.append(h);
    const ul = document.createElement("ul"); ul.className = "small";
    for (const c of chapters) {
      const li = document.createElement("li"); li.textContent = c.title || c.key;
      ul.append(li);
    }
    el.append(ul); box.append(el);
  };
  list("⚠ chapters that would be LOST (" + (d.missing_chapters || []).length + ")",
       d.missing_chapters);
  list("new chapters (" + (d.new_chapters || []).length + ")", d.new_chapters);
  if (d.backup) {
    const p = document.createElement("div"); p.className = "small muted";
    p.textContent = "backup: " + d.backup; box.append(p);
  }
}

$("btnCheck").onclick = async () => {
  clearErr(); busy("checking against the site…");
  try {
    const d = await apiJson("/books/" + state.bookId + "/check", {method: "POST"});
    renderDecision(d);
    setUpdateAvailable(d.action === "update");
    // A check writes nothing, so "success" would overstate it; only a refusal
    // — the thing worth hearing about — gets its own sound.
    playForDecision(d);
  }
  catch (e) { err("check failed — " + e.message); play("error"); }
  finally { busy(null); }
};

$("btnUpdate").onclick = async () => {
  if (!confirm("Fetch new chapters and update this epub in calibre?")) return;
  clearErr();
  busy("updating — big serials can take minutes; leave this page open…");
  try {
    const d = await apiJson("/books/" + state.bookId + "/update", {method: "POST"});
    renderDecision(d);
    setUpdateAvailable(false);   // whatever was pending has now been applied
    playForDecision(d);
  }
  catch (e) { err("update failed — " + e.message); play("error"); }
  finally { busy(null); }
};

$("btnEpub").onclick = async () => {
  clearErr(); busy("downloading epub…");
  try {
    const blob = await (await api("/books/" + state.bookId + "/epub")).blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = state.bookId + ".epub";
    document.body.append(a); a.click(); a.remove();
    URL.revokeObjectURL(a.href);
    play("success");
  } catch (e) { err("download failed — " + e.message); play("error"); }
  finally { busy(null); }
};
