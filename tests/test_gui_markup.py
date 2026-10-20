"""The contract between `index.html` and `app.js`, which is just ids.

Nothing else in the suite looks at the GUI's markup. Stage 3b rewrote the
whole Print tab -- seven panels became annotated sections, two fields moved
into the page title -- and all 768 tests passed without noticing, because
none of them reads the HTML.

That is survivable while a human opens every tab afterwards, and it is not
survivable across the four restructures still to come. A mistyped id fails
silently in the browser: `getElementById` returns null, the handler never
binds, and the control is simply inert. These tests are cheap and catch
exactly that.
"""

import os
import re

import pytest

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "src", "checkit_printit", "gui", "static")

#: Ids the page creates at runtime rather than declaring in the markup.
#: Keep this list short and say why each one is here.
def assigned_ids(js):
    """Ids the script creates itself, e.g. `bar.id = "stale"`.

    Derived rather than listed by hand. An allowlist would have to carry
    `course-name` and `stale` today, and the next hand-maintained entry is
    the one that quietly excuses a typo -- whereas a misspelt
    `getElementById` matches no assignment either, so it still fails.
    """
    return set(re.findall(r'\.id\s*=\s*"([^"]+)"', js))


def read(name):
    with open(os.path.join(STATIC, name), encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def html():
    return read("index.html")


@pytest.fixture(scope="module")
def js():
    return read("app.js")


def declared_ids(html):
    return set(re.findall(r'\bid="([^"]+)"', html))


def wanted_ids(js):
    return set(re.findall(r'getElementById\("([^"]+)"\)', js))


def strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def bare_classes(css):
    """Class names used as a selector on their own, e.g. `.band {`.

    `.skill.on` does not count for either name: a compound selector can
    only match an element that already carries the other class, so it
    cannot reach across into markup it was not written for. A bare one
    claims every element with that class in the whole document -- and
    the two stylesheets share a document.
    """
    css = strip_comments(css)
    out = set()
    for m in re.finditer(r"(^|[^\w\-.\]\)])\.([A-Za-z][\w-]*)", css):
        if css[m.end():m.end() + 1] not in (".", "["):
            out.add(m.group(2))
    return out


def test_no_bare_class_is_defined_in_both_stylesheets():
    """The two stylesheets share one document, so a bare class name in
    `style.css` is a claim about `seating.css` too.

    This has shipped twice. `.rail` in stage 2 hit Seating's mode rail and
    fitted the room at 20%; `.band` in stage 3c hit its selection
    rectangle, whose `position: absolute` turned a `<tr>` into a block and
    dropped it out of the table. Neither failed a test, and the second was
    committed one stage after the rule was written down -- so the rule is
    a test now rather than a paragraph.
    """
    shared = sorted(bare_classes(read("style.css"))
                    & bare_classes(read("seating/seating.css")))
    assert not shared, (
        "defined bare in both style.css and seating/seating.css: "
        + ", ".join(shared)
        + ". Rename, or qualify it so it cannot match on its own.")


def test_the_collision_check_would_have_caught_the_two_that_shipped():
    """A check that cannot fail is not a check. `.rail` and `.band` are
    still bare in seating.css, so adding either bare to style.css must be
    flagged -- and `.on`, which is shared today, must not be."""
    seating = bare_classes(read("seating/seating.css"))
    assert "rail" in seating and "band" in seating, (
        "seating.css no longer defines the two that collided; pick live "
        "examples or this test proves nothing")
    assert "on" not in seating, "`.on` is compound-only and must stay allowed"
    assert not bare_classes(".skill.on { color: red }")


def test_the_fixtures_actually_read_something(html, js):
    """A check that examined nothing passes for the wrong reason."""
    assert len(html) > 2000, "index.html looks empty"
    assert len(js) > 2000, "app.js looks empty"
    assert len(declared_ids(html)) > 40
    assert len(wanted_ids(js)) > 40


def test_every_id_the_script_reaches_for_exists(html, js):
    """`getElementById` on a name nothing declares returns null, and the
    control it was going to wire up is inert with no error anywhere."""
    missing = sorted(wanted_ids(js) - declared_ids(html) - assigned_ids(js))
    assert not missing, (
        "app.js asks for ids that index.html does not declare and app.js "
        "never assigns: " + ", ".join(missing))


def test_no_id_is_declared_twice(html):
    """Two elements with one id means `getElementById` silently picks the
    first, and the second is dead."""
    ids = re.findall(r'\bid="([^"]+)"', html)
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, "declared more than once: " + ", ".join(dupes)


def test_the_print_tab_still_has_what_the_draft_round_trips_through(html):
    """Every field of the print draft needs somewhere to live. Losing one
    in a restructure means a setting that silently stops being editable --
    which is how the title ended up read-only in the old top bar."""
    ids = declared_ids(html)
    for field in ("p-title", "p-date", "p-keys", "p-key-copies", "p-names"):
        assert field in ids, f"the print draft's {field} has no control"


def test_every_hint_button_has_something_to_reveal(html):
    """One `?` to one explanation, counted across the whole page.

    A button with nothing behind it does nothing when pressed; an
    explanation with no button is unreachable. Counting both ways catches
    each, and it keeps working for a `?` in a page header, which is not
    inside an annotated section at all.
    """
    buttons = len(re.findall(r'class="hint"', html))
    texts = len(re.findall(r'class="hint-text"', html))
    assert buttons, "no `?` buttons found; did the class change?"
    assert buttons == texts, (
        f"{buttons} `?` button(s) but {texts} explanation(s)")


def test_each_annotated_sections_hint_is_its_own(html):
    """Scope, not just arithmetic: a `?` inside a section must find its
    explanation there, because that is where the click handler looks."""
    sections = re.findall(r'<section class="annot[^"]*"(.*?)</section>',
                          html, re.S)
    assert sections, "no annotated sections found; did the class change?"
    lonely = [s[:60] for s in sections
              if 'class="hint"' in s and "hint-text" not in s]
    assert not lonely, f"{len(lonely)} `?` button(s) with no explanation"


def test_a_counter_is_not_inside_a_heading(html):
    """13.5: the name goes in the heading, the count sits right-aligned on
    the same row. `<h3>Extras <span id=extras-count>` was the old way."""
    bad = re.findall(r"<h3[^>]*>[^<]*<span", html)
    assert not bad, f"{len(bad)} heading(s) still contain a counter span"
