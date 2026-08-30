// Where each view starts when you arrive at it. Exercised from
// tests/test_scroll.py via node.
import "./dom_stub.mjs";
const { show, forgetBrowseScroll } = await import("../ratchet/static/core.js");

const out = {};
const at = () => globalThis.window.scrollY;
const scrollTo = y => { globalThis.window.scrollY = y; };

show("browse");                 // the first view: the app opening

// Step into a book from partway down the list and come back.
scrollTo(1200);
show("detail");
out.book_page_starts_at_the_top = at();
show("browse");
out.list_comes_back_where_it_was = at();

// The same through a sub-view, which is what the back button walks.
scrollTo(800);
show("pickcol");
out.picker_starts_at_the_top = at();
show("pickval");
show("browse");
out.list_survives_a_detour = at();

// A second book must not inherit the first one's position.
scrollTo(640);
show("detail");
scrollTo(300);                  // scrolled down inside the book page
show("browse");
show("detail");
out.each_book_starts_at_the_top = at();

// Re-showing the view already on screen leaves the page alone: a filter
// applied from the list must not throw the reader back to the top.
show("browse");
scrollTo(450);
show("browse");
out.same_view_does_not_move = at();

// A new list is a new set of books; the old offset would point at strangers.
scrollTo(900);
show("detail");
forgetBrowseScroll();           // what search() calls when it replaces results
show("browse");
out.a_new_search_starts_at_the_top = at();

process.stdout.write(JSON.stringify(out));
