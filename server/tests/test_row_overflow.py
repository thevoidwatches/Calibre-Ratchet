"""Nothing in a book's row may make the page scroll sideways.

Hierarchical values are single unbreakable words — a real one in this
library is "Nonfiction.Informational.Science.Physics.Astrophysics", 53
characters — and a flex item will not shrink below its longest word. Every
text side of every row therefore has to be told it may break one."""

import re

from test_api import TOK, client   # noqa: F401  (shares the module-level config)


def css() -> str:
    return client.get("/ui/ui.css").text


def rule_for(selector: str) -> str:
    """Every declaration that applies to `selector`, from all the rules whose
    selector list names it — a span can be styled by more than one, and it is
    their sum that decides what it does."""
    found = [b.group(2) for b in re.finditer(r"([^{}]+)\{([^}]*)\}", css())
             if selector in b.group(1)]
    return " ".join(found)


def test_the_long_side_of_every_row_may_break_a_word():
    """The title and author sides already could; genres and tags could not,
    which is what let a long tag run off the edge."""
    for selector in (".list li .titlerow .t",
                     ".list li .byline .who",
                     ".list li .meta .genres",
                     ".list li .meta .tags"):
        decl = rule_for(selector)
        assert "min-width: 0" in decl, selector
        assert "overflow-wrap: anywhere" in decl, selector


def test_it_is_anywhere_rather_than_break_word():
    """Only "anywhere" counts towards how far a flex item may shrink;
    "break-word" wraps the text but leaves the row as wide as before."""
    assert "overflow-wrap: break-word" not in css()


def test_the_fixed_side_of_a_row_cannot_outgrow_it():
    """The right-hand spans do not shrink, so anything that could be long
    has to clip instead. The page count and the series are short by nature;
    a chosen column is not."""
    assert "text-overflow: ellipsis" in rule_for(".list li .titlerow .rowfield")
    assert "overflow: hidden" in rule_for(".list li .titlerow .rowfield")


def test_neither_side_of_the_meta_row_can_be_squeezed_past_half_the_other():
    """Flex shares room in proportion to content, so a long tag line beside
    one genre would starve the genre to a word's width — where no break
    point helps, because the word itself no longer fits."""
    floor = rule_for(".list li .meta > :not(:empty)")
    assert "min-width: calc((100% - var(--gap)) / 3)" in floor
    # A third each is the floor, so the other side tops out at two thirds:
    # a 1:2 ratio. The gap is named once and used by both.
    assert "--gap: 10px" in rule_for(".list li .meta")
    assert "gap: var(--gap)" in rule_for(".list li .meta")


def test_an_empty_side_still_gives_the_row_away():
    """A book with no genres must not leave a third of its row blank, so
    every floor in that row is guarded by :not(:empty) — the unconditional
    rule still says zero."""
    assert "min-width: 0" in rule_for(".list li .meta .genres")
    floors = [b.group(1) for b in re.finditer(r"([^{}]+)\{([^}]*)\}", css())
              if ".meta" in b.group(1) and "min-width: calc" in b.group(2)]
    assert floors, "no floor rule found"
    for selector in floors:
        assert ":not(:empty)" in selector, selector


def test_the_page_is_not_simply_told_to_hide_the_overflow():
    """overflow-x: hidden on the page would mask this rather than fix it,
    and would hide the next one too."""
    for selector in ("body", "html", "main"):
        assert "overflow-x" not in rule_for(selector), selector


def test_the_expander_in_the_value_tree_is_a_real_touch_target():
    """It was sized to the arrowhead — a few millimetres of glyph — which is
    below what a finger can reliably hit."""
    twist = rule_for(".tree .twist")
    assert "min-width: 44px" in twist and "min-height: 44px" in twist
    # Centred, since the glyph no longer fills the box it is hit in.
    assert "justify-content: center" in twist and "align-items: center" in twist


def test_choosing_the_placeholder_clears_the_filters():
    """The top entry of the saved-set dropdown is the way back out of a set;
    leaving its chips in place would show filters the dropdown disclaims."""
    js = client.get("/ui/filters.js").text
    assert "function clearFilters()" in js
    assert "if (!name) { clearFilters(); return; }" in js
    body = js.split("function clearFilters()")[1].split("}")[0]
    assert "state.filterGroups = []" in body
    assert "search()" in body      # and the list reflects it at once


SMALL_TRIANGLES = "▸▾◂▴"      # U+25B8 etc: "small" by design


def test_every_collapse_arrow_is_a_full_size_triangle():
    """The small triangles are half the ink of the full ones, so a larger box
    around one is still a tiny arrowhead to look at."""
    for path in ("/ui/picker.js", "/ui/browse.js", "/ui/ui.css", "/ui/"):
        text = client.get(path).text
        assert not [c for c in text if c in SMALL_TRIANGLES], path


def test_they_are_all_sized_from_one_place():
    """The value tree, the filter bar and the book page's field sections are
    the same control in three costumes; one token keeps them recognisable as
    such and tunable together."""
    assert "--twist-size:" in rule_for(":root")
    for selector in (".tree .twist", ".twisty",
                     "details.fieldset > summary::before"):
        assert "font-size: var(--twist-size)" in rule_for(selector), selector


def test_the_filter_bar_arrow_is_its_own_element():
    """Sized inside a button whose label stays its own size, which needs the
    arrow to be an element rather than part of the text."""
    browse = client.get("/ui/browse.js").text
    assert 'twist.className = "twisty"' in browse
    assert "btn.replaceChildren(twist," in browse
    assert 'class="twisty"' in client.get("/ui/").text   # and before JS runs


def test_the_picker_says_where_each_way_out_goes():
    """Leaving the column list abandons the filter and lands on the book
    list; leaving the value list only steps back to the column list."""
    html = client.get("/ui/").text

    def way_out(section: str) -> str:
        body = html.split(f'id="{section}"')[1].split("</section>")[0]
        return re.search(r"<button[^>]*data-nav[^>]*>(.*?)</button>", body).group(1)

    assert "cancel" in way_out("vPickCol")
    assert "back" in way_out("vPickVal")
    # The book page is a step off the list, so leaving it is a step back too.
    assert "back" in way_out("vDetail")
