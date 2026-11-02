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
import shutil
import subprocess

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


def top_level_names(js):
    """`const X`, `let X`, `function X`, `class X` at column zero.

    Indentation is the test for top level, which is crude and right for
    these two files: both are written flat, and anything nested is
    indented by the project's own style.
    """
    return set(re.findall(r"^(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)",
                          js, re.M))


def compounds(css):
    """Every selector split into per-element compounds.

    `.a .b.c` is two elements: `.a`, then `.b.c`. Splitting on the
    combinators first is the whole point -- a descendant selector is
    ordinary, and an earlier version of this test flagged all 40 of
    them.
    """
    out = []
    for chunk in re.findall(r"([^{}]*)\{", css):
        for selector in chunk.split(","):
            out += _split(selector.strip())
    return out


def _split(selector):
    """One selector into compounds, descending into `:has()` and friends.

    What is inside a functional pseudo-class is its own selector, so
    `.deskwrap:has(.shape.tocount)` is two compounds and not one
    element with three classes. Without this the check read `.shape` as
    a modifier of `.deskwrap` and reported a collision that is not
    there -- `.shape` is the head of its own compound and `.tocount`
    qualifies it.
    """
    inner = []
    def lift(match):
        inner.extend(_split(match.group(1)))
        return ""
    while True:
        after = re.sub(r":(?:has|not|is|where)\(([^()]*)\)", lift, selector)
        if after == selector:
            break
        selector = after
    return [p for p in re.split(r"[\s>+~]+", selector) if p] + inner


def test_a_class_that_escapes_the_page_is_never_a_modifier():
    """`position: fixed` or `absolute` on a bare `.foo` means `.foo`
    cannot also qualify something else: whatever you attach it to is
    lifted out of the document.

    `.stale` is the page-is-older-than-the-server banner -- fixed, warn
    background, drop shadow, bottom-centre of the window. The Print
    tab's "chosen for another day" cell was given `class="aged stale"`,
    and one table cell left the table and parked itself over the page.
    Every one of the 805 tests passed. It took a screenshot.

    Narrow on purpose. Sharing a word is not by itself wrong --
    `.vcircle.badge.editing` wants the bare `.badge` rule to apply.
    Sharing a word with a rule that takes an element out of flow always
    is, because nothing downstream can put it back.
    """
    escapes, used_as_modifier = {}, {}
    for name in ("style.css", "seating/seating.css"):
        css = re.sub(r"/\*.*?\*/", "", read(name), flags=re.S)
        for block in re.findall(r"([^{}]*)\{([^{}]*)\}", css):
            selector, body = block
            if not re.search(r"position:\s*(fixed|absolute)", body):
                continue
            for part in compounds(selector + "{"):
                if re.fullmatch(r"\.[\w-]+", part):
                    escapes[part[1:]] = name
        for part in compounds(css):
            classes = re.findall(r"\.([\w-]+)", part)
            for word in classes[1:]:
                used_as_modifier.setdefault(word, set()).add(part)

    clashes = {w: used_as_modifier[w] for w in escapes if w in used_as_modifier}
    assert not clashes, "takes an element out of flow and also qualifies one: " \
        + "; ".join(f"`.{w}` ({escapes[w]}) is attached in {sorted(where)}"
                    for w, where in sorted(clashes.items()))


def test_that_check_would_have_caught_the_one_that_shipped():
    """Green on a clean stylesheet proves nothing. This is the real
    pair, fed to the same helpers."""
    css = ".stale { position: fixed; bottom: 18px; }\n" \
          "#who td.aged.stale { color: red; }"
    escaping = {p[1:] for block in re.findall(r"([^{}]*)\{([^{}]*)\}", css)
                if re.search(r"position:\s*(fixed|absolute)", block[1])
                for p in compounds(block[0] + "{")
                if re.fullmatch(r"\.[\w-]+", p)}
    assert escaping == {"stale"}
    attached = {w for p in compounds(css)
                for w in re.findall(r"\.([\w-]+)", p)[1:]}
    assert "stale" in attached, "the check would not have noticed"


def test_the_two_scripts_declare_no_name_twice():
    """`app.js` and `seating/seating.js` are two plain <script> tags, so
    they share one global scope.

    Renaming `NAV_ICON` to `ICON` collided with seating.js's own `ICON`.
    A duplicate `const` at top level is a SyntaxError, and the file that
    loses is the *other* one -- the Roster rendered perfectly while Seats
    failed to load at all, with nothing on the Roster to suggest why.

    Same failure as the two CSS collisions, in a second language, so it
    gets the same treatment.
    """
    shared = sorted(top_level_names(read("app.js"))
                    & top_level_names(read("seating/seating.js")))
    assert not shared, (
        "declared at top level in both app.js and seating/seating.js: "
        + ", ".join(shared) + ". One of the two files will not load.")


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


@pytest.mark.parametrize("name", ["app.js", "seating/seating.js"])
def test_the_scripts_parse(name):
    """`node --check`, because a SyntaxError is invisible from here.

    Nothing in this suite runs the browser's JavaScript, so a duplicate
    `const` in one function is a blank tab and a green test run. It has
    happened twice: `ICON` against seating.js's own, and `dropped`
    declared twice inside `renderRoster`.

    Skipped where node is missing rather than failing -- the suite has
    to run on a machine that only has Python.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    path = os.path.join(STATIC, *name.split("/"))
    done = subprocess.run([node, "--check", path],
                          capture_output=True, text=True)
    assert done.returncode == 0, (
        f"{name} does not parse:\n{done.stderr.strip()}")


def test_no_control_is_styled_as_underlined_text():
    """A standing rule from the instructor: **plain underlined text is
    not how a function looks here.**

    An underline says "this navigates". Every one of these does
    something instead, and a row of them reads as a marked-up paragraph
    rather than as a set of controls. The class was literally called
    `.link` for as long as it looked like one.
    """
    css = strip_comments(read("style.css"))
    # Underlines on a :hover of a real anchor are fine; a button is not.
    offenders = []
    for block in re.finditer(r"([^{}]+)\{([^}]*)\}", css):
        selector, body = block.group(1).strip(), block.group(2)
        if "text-decoration" not in body:
            continue
        if not re.search(r"underline", body):
            continue
        if "button" in selector or ".act" in selector or ".iconbtn" in selector:
            offenders.append(selector)
    assert not offenders, (
        "styled as underlined text: " + "; ".join(offenders))


def test_the_warning_mark_is_not_typed_into_sentences(js):
    """`.warnline` draws its own mark.

    It used to be typed into the message -- two of eight had it -- so
    warnings in the same report did not look alike. A mark that has to
    be remembered is a mark that gets forgotten.
    """
    typed = [l.strip()[:60] for l in js.splitlines() if "⚠" in l]
    assert not typed, (
        "a warning mark is written into the text; `.warnline::before` "
        "draws it: " + "; ".join(typed))


def test_every_tab_with_a_save_bar_has_exactly_one(html):
    """One scope per tab. The Update form had its Save inside a section,
    which said the button belonged to that section when the same save
    also wrote the fields above it."""
    bars = re.findall(r'class="savebar" id="([\w-]+)"', html)
    assert sorted(bars) == sorted(set(bars)), f"duplicate save bars: {bars}"
    assert len(bars) >= 4, f"expected a bar per editable tab, found {bars}"
    for view in bars:
        assert view.endswith("-bar"), view


def test_no_save_button_lives_outside_its_bar(html):
    """A Save loose in a toolbar is the arrangement this replaced."""
    for block in re.findall(r'<div class="toolbar">(.*?)</div>', html, re.S):
        assert "Save</button>" not in block, (
            "a Save button is still in a toolbar: " + block.strip()[:80])


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


def rules_only():
    """`style.css` with every comment removed.

    Both weight checks below were written against the raw file and both
    failed on their first run, for the same reason and neither of them
    on a real fault. One matched a `stroke-width:` that appears inside a
    comment explaining the weight rule; the other blamed the unsaved dot,
    because splitting on braces hands you everything since the last `}`
    as the "selector", comments included, and the comment above that
    block says the word `svg`.

    This is the project's standing hazard in a new place: prose about
    the syntax, read as the syntax. Both Mustache and Jinja templates
    broke this way. Strip first, then scan.
    """
    return re.sub(r"/\*.*?\*/", "", read("style.css"), flags=re.S)


def without_comments(source):
    """Comments removed, line numbers preserved.

    A block comment is replaced by its own newlines rather than by
    nothing. Collapsing them shifts every line below, and the first
    version of this check reported `seating.js:3585` for a call that
    is on line 4757 -- which cost a search through unrelated code
    before the number was doubted.
    """
    source = re.sub(r"/\*.*?\*/",
                    lambda m: "\n" * m.group(0).count("\n"),
                    source, flags=re.S)
    return re.sub(r"//[^\n]*", "", source)


def native_modals(source):
    """Every `confirm`/`alert`/`prompt` that reaches the real global.

    Two patterns, not one. A single "not preceded by a dot" rule misses
    `window.confirm(...)`, which is the same suppressed global wearing a
    qualifier -- and a rule that allows a leading dot flags
    `dialog.confirm(...)`, which is somebody's own method. So: bare
    calls, plus calls qualified by the global object by name.
    """
    bare = re.finditer(r"(?:^|[^.\w$])(confirm|alert|prompt)\s*\(", source)
    qualified = re.finditer(
        r"\b(?:window|globalThis|self)\.(confirm|alert|prompt)\s*\(",
        source)
    return list(bare) + list(qualified)


def test_no_native_modal_is_used():
    """`confirm`, `alert` and `prompt` do nothing in the desktop pane.

    They are suppressed, and a suppressed `confirm` returns falsy -- so
    `if (!confirm(...)) return;` is a control that silently does
    nothing. That shipped twice: the Roster's drop button, and then the
    form's Push it button, which is the one control in the app that
    changes what students see.

    `ask()` is the replacement: a promise over a `<dialog>`, which is an
    element on the page rather than browser chrome. CLAUDE.md has said
    "never confirm, alert or prompt" since the first time; a paragraph
    did not stop the second time, so here is a test.
    """
    bad = []
    for name in ("app.js", "seating/seating.js"):
        source = without_comments(read(name))
        for call in native_modals(source):
            line = source[:call.start()].count("\n") + 1
            bad.append(f"{name}:{line} {call.group(1)}(")
    assert not bad, ("native modal(s), which the desktop pane suppresses -- "
                     "use ask(): " + "; ".join(bad))


def test_that_check_would_have_caught_the_push_button():
    """Watched failing against the line that actually shipped, and
    against `window.confirm`, which the first version of this check
    let straight through -- found by mutation, not by reading."""
    for source in ('  if (!confirm("Push this to the form?")) return;',
                   '  if (window.confirm("x")) return;',
                   "  globalThis.alert(1);",
                   "  self.prompt(2);"):
        assert native_modals(source), f"not caught: {source.strip()}"


def test_the_modal_check_allows_a_method_named_confirm():
    """`thing.confirm(...)` is a method call, not the global. Narrow
    enough not to flag one, or the next person deletes the test."""
    source = "dialog.confirm(x); this.alert(y); obj.prompt(z); d.alert(1);"
    assert not native_modals(source), "false positive on a method call"


def test_every_glyph_size_comes_with_its_own_variable():
    """One optical line weight across the whole app, enforced here.

    `.glyph` sets `stroke-width: calc(24 * 1.5 / var(--glyph-size))`. The
    glyphs are drawn in a 24-unit box, so that lands every stroke on
    screen at 1.5px no matter what size the glyph is rendered at -- but
    only if `--glyph-size` says the truth. A block that sets `width:
    16px` and forgets the variable inherits 18 and draws at 1.33px, and
    the drift is far too small to see in isolation and perfectly obvious
    once two of them sit side by side. That is exactly how the rail's
    gear and chevron came out lighter than the icons above them.

    So: any rule that gives a glyph a width must set `--glyph-size` to
    the same number in the same block.
    """
    blocks = re.findall(r"([^{}]*)\{([^{}]*)\}", rules_only())
    bad = []
    for selector, body in blocks:
        if "glyph" not in selector and "svg" not in selector:
            continue
        width = re.search(r"(?<!-)\bwidth:\s*(\d+)px", body)
        if not width:
            continue
        size = re.search(r"--glyph-size:\s*(\d+)", body)
        if not size or size.group(1) != width.group(1):
            bad.append((selector.strip().splitlines()[-1].strip(),
                        width.group(1),
                        size.group(1) if size else "missing"))
    assert not bad, "glyph width without a matching --glyph-size: " + "; ".join(
        f"{sel} is {w}px but --glyph-size is {g}" for sel, w, g in bad)


def test_the_weight_check_would_notice_a_forgotten_variable():
    """The check above passes on a clean stylesheet, which proves nothing
    until it has been watched failing. Same shape as the collision
    check's twin: feed it the mistake and confirm it objects."""
    body = "width: 16px; height: 16px;"
    width = re.search(r"(?<!-)\bwidth:\s*(\d+)px", body)
    size = re.search(r"--glyph-size:\s*(\d+)", body)
    assert width and not size, "the patterns no longer match what they must"


def test_the_one_weight_is_stated_once():
    """1.5px lives in a single declaration. Two of them is how a second
    weight gets introduced without anyone deciding to."""
    rule = re.findall(r"stroke-width:\s*([^;]+);", rules_only())
    assert rule == ["calc(24 * 1.5 / var(--glyph-size, 18))"], (
        f"expected one stroke-width declaration, found {rule}")


def test_a_counter_is_not_inside_a_heading(html):
    """13.5: the name goes in the heading, the count sits right-aligned on
    the same row. `<h3>Extras <span id=extras-count>` was the old way."""
    bad = re.findall(r"<h3[^>]*>[^<]*<span", html)
    assert not bad, f"{len(bad)} heading(s) still contain a counter span"


def test_the_drop_area_has_no_button_beside_it(html):
    """The whole point of the drop area is that it is the only control.

    An Import button went in beside it, was taken out, and a Start over
    button went straight back into the same slot -- twice in one day,
    because "it is only a small button" is true of every one of them.
    The pair that belongs beside a Save belongs in the save bar.
    """
    picker = re.search(r'<div class="scan-pick">(.*?)</div>', html, re.S)
    assert picker, "the scan picker is gone"
    loose = re.findall(r"<button[^>]*>", picker.group(1))
    assert not loose, (
        "a button is back beside the drop area; it belongs in "
        "#scans-bar: " + "; ".join(loose))


def test_start_over_is_in_the_scans_save_bar(html):
    """Where every other tab keeps the same pair."""
    bar = re.search(r'<div class="savebar" id="scans-bar".*?</div>',
                    html, re.S)
    assert bar, "the scans save bar is gone"
    assert 'id="scan-clear"' in bar.group(0), (
        "Start over is not in the scans save bar")


# ------------------------------------------------------- the layout ----

def media_blocks(css):
    """Each `@media (...)` block's condition and body, comments stripped."""
    out, css = [], strip_comments(css)
    for m in re.finditer(r"@media([^{]+)\{", css):
        depth, i = 1, m.end()
        while i < len(css) and depth:
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        out.append((m.group(1).strip(), css[m.end():i - 1]))
    return out


def test_no_media_query_styles_a_bare_tag_name():
    """A tag-name rule is aimed at whatever the markup contains later.

    `@media (max-width: 820px)` was written for a top bar this app no
    longer has, and styled `header`, `h1`, `nav` and `nav button`. The
    bar went away; the selectors did not. Every page heading is a
    `<header class="pagehead">` and `buildNav()` builds the rail's
    destination list as a `<nav>`, so below 820px nine headings took on
    a padding their own content did not have -- 12px to the right, 7px
    down -- and the rail's buttons changed size at a second threshold
    80px from the one the rail uses itself. That is a heading that
    moves left, right, up and down as the window narrows.

    Classes are fine here. The rule is about bare tag names, which
    cannot say which elements they meant.
    """
    css = read("style.css")
    tags = app_tags()
    offenders = []
    for condition, body in media_blocks(css):
        for selector in re.findall(r"(?m)^\s*([^{}@/]+?)\s*\{", body):
            for part in selector.split(","):
                lead = part.strip().split()[0] if part.strip() else ""
                # Only the leftmost compound decides. `.pagehead h2` is
                # scoped by a class and can only reach markup that asked
                # for it; `nav button` and `header` cannot.
                if lead in tags:
                    offenders.append(
                        f"@media{condition} {{ {part.strip()} }}")
    assert not offenders, (
        "a media query styles elements by tag name, and the app builds "
        "those tags: " + "; ".join(offenders))


def app_tags():
    """Every element name the app can put on the page.

    Both sources, because the first version of this test read only
    `index.html` and would have missed the `nav` half of the bug it was
    written for: the rail's destination list is built by `buildNav()`,
    so `<nav` appears nowhere in the markup.
    """
    html, js = read("index.html"), read("app.js")
    return (set(re.findall(r"<([a-z][a-z0-9]*)[\s>]", html))
            | set(re.findall(r'createElement\("([a-z][a-z0-9]*)"\)', js)))


def test_main_has_one_gutter():
    """One answer to "where does the content start", at every width.

    `main` had three paddings across two overlapping breakpoints: 16px,
    12px below 820, and 16px again below 720 -- the last added later and
    three hundred lines further down the file, so it won where both
    matched. Narrowing the window moved the content right, then left
    again. Everything in a view now hangs off `--gutter`, and the only
    thing that changes with width is the rail.
    """
    css = strip_comments(read("style.css"))
    inside = [c for c, body in media_blocks(css)
              if re.search(r"(?m)^\s*main\s*\{", body)]
    assert not inside, (
        "main's padding changes at a breakpoint again: " + "; ".join(inside))
    assert "--gutter:" in css, "the gutter token is gone"
    assert re.search(r"(?m)^main\s*\{[^}]*var\(--gutter\)", css), (
        "main no longer uses --gutter for its side padding")


def test_every_page_heading_is_a_pagename(html):
    """Progress drew its heading at 18px while the other six drew 20px.

    Nothing said so, because two tabs are never on screen together. The
    `.pagename` class is what makes a heading a page heading; a bare
    `<h2>` falls through to the stylesheet's smaller default.
    """
    bare = [m for m in re.findall(r"<h2(?![^>]*\bclass=)[^>]*>", html)]
    assert not bare, "a page heading is not a .pagename: " + "; ".join(bare)
