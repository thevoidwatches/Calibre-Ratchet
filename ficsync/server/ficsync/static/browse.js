// Browse view: filter chips -> calibre search query -> results list.
"use strict";
import { $, state, apiJson, err, clearErr } from "./core.js";
import { openBook } from "./detail.js";

// Hierarchical columns get a prefix match so a parent finds its descendants
// ("Science Fiction" hits "Science Fiction.Space Opera"); flat columns get an
// exact match, since a "." in an author name is punctuation, not hierarchy.
function filterToQuery(f) {
  let part;
  if (f.hierarchical === false) {
    part = f.field + ':"=' + f.value.replace(/"/g, '\\"') + '"';
  } else {
    const esc = f.value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    part = f.field + ':"~^' + esc + '(\\.|$)"';
  }
  return f.exclude ? "not " + part : part;
}

export function fullQuery() {
  const parts = state.filters.map(filterToQuery);
  const free = $("q").value.trim();
  if (free) parts.push(free);
  return parts.join(" and ");
}

export function renderFilterChips() {
  const box = $("filterChips"); box.innerHTML = "";
  state.filters.forEach((f, i) => {
    const c = document.createElement("span");
    c.className = "chip" + (f.exclude ? " excl" : "");
    c.append(f.field + ": " + f.value);
    const x = document.createElement("button");
    x.textContent = "×";
    x.onclick = () => { state.filters.splice(i, 1); renderFilterChips(); search(); };
    c.append(x);
    box.append(c);
  });
  $("queryPreview").textContent = fullQuery();
}

export async function search(more = false) {
  clearErr();
  const q = fullQuery();
  if (!more) { state.offset = 0; $("results").innerHTML = ""; }
  try {
    const data = await apiJson("/books?q=" + encodeURIComponent(q) +
                               "&num=30&offset=" + state.offset);
    for (const b of data.books) {
      const li = document.createElement("li");
      li.innerHTML = '<div class="t"></div><div class="small muted"></div>' +
                     '<div class="meta"><span class="genres"></span>' +
                     '<span class="tags"></span></div>';
      li.children[0].textContent = b.title || ("(book " + b.id + ")");
      li.children[1].textContent = (b.authors || []).join(", ");
      const meta = li.children[2];
      meta.querySelector(".genres").textContent = (b.genre || []).join(" · ");
      meta.querySelector(".tags").textContent = (b.tags || []).join(" · ");
      li.onclick = () => openBook(b.id);
      $("results").append(li);
    }
    state.offset += data.books.length;
    $("btnMore").hidden = !(data.total > state.offset && data.books.length > 0);
  } catch (e) { err("search failed — " + e.message); }
}

$("searchForm").addEventListener("submit", e => { e.preventDefault(); search(); });
$("btnMore").onclick = () => search(true);
