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

import json
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


def stray_comment_closes(css):
    """Lines carrying a `*/` that closes nothing.

    CSS comments do not nest, so `/* a */ b */` leaves the second
    close dangling. Walked rather than matched with a regex, because
    the question is about state -- am I inside a comment -- and a
    regex that answers it is harder to read than the loop.
    """
    bad = []
    line = 1
    inside = False
    i = 0
    while i < len(css):
        if css[i] == "\n":
            line += 1
        if not inside and css.startswith("/*", i):
            inside = True
            i += 2
            continue
        if inside and css.startswith("*/", i):
            inside = False
            i += 2
            continue
        if not inside and css.startswith("*/", i):
            bad.append(line)
        i += 1
    return bad, inside


@pytest.mark.parametrize("sheet", ["style.css", "seating/seating.css"])
def test_no_comment_closes_a_comment_that_was_never_opened(sheet):
    """A dangling `*/` silently eats the rule after it.

    Extending a comment that already ended -- writing another
    paragraph after its `*/` and closing again -- leaves prose
    sitting as bare CSS and a second `*/` closing nothing. The parser
    recovers by discarding to the next brace, which takes the rule
    underneath with it. Nothing errors and nothing is logged: the
    stylesheet loads, and one rule is simply absent.

    This shipped twice in one sitting, in two different paragraphs,
    and was found only because a panel came out 245px wide when its
    rule said 320. The rule had not been overridden; it had been
    swallowed.
    """
    bad, unterminated = stray_comment_closes(read(sheet))
    assert not bad, (
        f"{sheet}: `*/` closing nothing at line(s) "
        + ", ".join(str(n) for n in bad)
        + ". The rule after it is being discarded. Did a comment get "
          "extended past its own close?")
    assert not unterminated, (
        f"{sheet}: a comment is opened and never closed, so everything "
        f"after it is being swallowed.")


def test_that_comment_check_would_have_caught_the_one_that_shipped():
    """The stylesheet as it was when the panel lost its width."""
    broken = (
        "/* why the panel takes width rather than floating. */\n"
        "   320px, which is what the parts that cannot shrink need. */\n"
        ".flyout { flex: 0 0 320px; }\n")
    bad, unterminated = stray_comment_closes(broken)
    assert bad == [2], bad
    assert not unterminated
    # And the shape it should have been.
    fixed = (
        "/* why the panel takes width rather than floating.\n"
        "\n"
        "   320px, which is what the parts that cannot shrink need. */\n"
        ".flyout { flex: 0 0 320px; }\n")
    assert stray_comment_closes(fixed) == ([], False)


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


# -------------------------------------------- the scan arithmetic ----

def pure_block():
    """The marked region of app.js, which uses no DOM.

    Lifted rather than imported because app.js is a browser script,
    not a module: loading it reaches for `document` on the first line
    that runs.
    """
    js = read("app.js")
    # From the outcome table, because the counting asks each status
    # whether it is one to chase, to the whole of the closing marker --
    # cutting inside it leaves an unterminated comment.
    start = js.index("const SCAN_OUTCOME = {")
    end = js.index("/* --- end pure --- */")
    assert start < end, "the pure block is not where it says it is"
    return js[start:end]


def run_js(body):
    """`node -e` over the pure block plus an assertion, as JSON."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    done = subprocess.run([node, "-e", pure_block() + "\n" + body],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr.strip()
    return json.loads(done.stdout)


#: A stack shaped like the demo one: twelve pages printed, one never
#: handed in, four of them the key -- and two double feeds, one of a
#: student's paper and one of a key.
#:
#: The key is fed twice on purpose. With four distinct key pages and
#: no repeat, counting key *sheets* and counting key *papers* give the
#: same answer, and a fixture that cannot tell them apart is a test
#: that passes either way -- which is what this one did until a
#: mutation put `placed.filter(...).length` back and nothing failed.
DEMO = """
const data = {
  counts: { placed: 13, blank: 1 },
  runs: [{ no: 1, title: "Checkpoint", date: "2026-10-25", pages: 12 }],
  sheets: [
    {status:"placed",run:1,page:1,kind:"student"},
    {status:"placed",run:1,page:1,kind:"student"},
    {status:"placed",run:1,page:2,kind:"student"},
    {status:"placed",run:1,page:3,kind:"student"},
    {status:"placed",run:1,page:5,kind:"student"},
    {status:"placed",run:1,page:6,kind:"student"},
    {status:"placed",run:1,page:7,kind:"student"},
    {status:"placed",run:1,page:9,kind:"student"},
    {status:"placed",run:1,page:11,kind:"key"},
    {status:"placed",run:1,page:11,kind:"key"},
    {status:"placed",run:1,page:12,kind:"key"},
    {status:"placed",run:1,page:13,kind:"key"},
    {status:"placed",run:1,page:14,kind:"key"},
    {status:"blank",run:null,page:null,kind:""}
  ],
  missing: [{ run: 1, page: 10 }]
};
"""


def test_a_paper_fed_twice_is_counted_once():
    """Eleven papers came back, not thirteen sheets.

    Counting sheets gave "12 of 12 back" beside a chip reading
    "1 missing" -- two numbers that cannot both be true. Found by
    reading the real demo stack, which has a double feed in it;
    nothing smaller would have shown it.
    """
    out = run_js(DEMO + 'console.log(JSON.stringify('
                        'jobCounts(data, data.runs[0])));')
    # 13 placed sheets, two of them repeats: 11 papers. And 11 matched
    # plus the 1 missing is the 12 that were printed.
    assert out["matched"] == 11, out
    assert out["missing"] == 1, out


def test_blank_is_a_pile_count_not_a_job_one():
    """A blank carries no code, so it has no run.

    It was computed per job once, by filtering that job's sheets on
    run number -- which dropped every blank there was, and the one
    blank in the demo stack appeared nowhere on the screen at all.
    """
    job = run_js(DEMO + 'console.log(JSON.stringify('
                        'jobCounts(data, data.runs[0])));')
    assert "blank" not in job, (
        "blank is back on the job's own counts, where its run is "
        "null: " + str(job))
    pile = run_js(DEMO + 'console.log(JSON.stringify(pileCounts(data)));')
    assert pile["blank"] == 1, pile


def test_only_the_pages_worth_chasing_are_unmatched():
    """A barcode from somewhere else is a cover sheet, not work.

    Chasing `foreign` would be chasing the copier.
    """
    counts = ('const data = { counts: { placed: 6, blank: 2, '
              'unreadable: 3, "unknown-run": 1, foreign: 1 } };')
    out = run_js(counts + 'console.log(JSON.stringify(pileCounts(data)));')
    assert out["unmatched"] == 4, out
    assert out["blank"] == 2, out


def test_the_job_date_is_month_and_day():
    out = run_js('console.log(JSON.stringify('
                 '[shortDay("2026-11-02"), shortDay(""), shortDay("odd")]));')
    assert out == ["11/2", "", "odd"], out


# ------------------------------------------------- the Progress grid --

def progress_block():
    """The marked Progress arithmetic from app.js, which uses no DOM.

    Its own region rather than part of the scan block: the two are
    nowhere near each other in the file, and a single marker pair
    spanning both would drag `renderProgress` in with them.
    """
    js = read("app.js")
    start = js.index("/* --- pure: progress ---")
    end = js.index("/* --- end pure: progress --- */")
    assert start < end, "the Progress block is not where it says it is"
    return js[start:end]


def run_progress_js(body):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    done = subprocess.run([node, "-e", progress_block() + "\n" + body],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr.strip()
    return json.loads(done.stdout)


class TestTheColourOfWhatIsInACell:
    r"""One rule: whatever is in a cell is the cell's own colour.

    Stated as `color` on the `td`, which a glyph picks up through
    `currentColor` and the fraction through `inherit`. Asserted here
    because a measurement in a browser is not something the suite can
    make, and six rules kept in step by hand is how two of them end up
    disagreeing.
    """

    @staticmethod
    def block(selector):
        """The body of the one rule that applies to this selector.

        The selector need not be the whole of the rule's own, only
        one of the comma-separated selectors in it. The drill-in's
        header repeats a cell and is named beside each cell rule so
        the colour is said once, and asking for an exact match would
        make that the failure rather than the second copy it avoids.
        """
        import re
        found = []
        # No `\}` anchor: it would be eaten by the previous match and
        # every rule after the first would be missed. A selector and a
        # body both simply hold no braces, which is enough to split on
        # and skips an `@media`'s own line for free.
        for whole, body in re.findall(r"([^{}]*)\{([^{}]*)\}", rules_only()):
            if selector in [s.strip() for s in whole.split(",")]:
                found.append(body)
        assert len(found) == 1, f"{selector}: {len(found)} rules, wanted 1"
        return found[0]

    def test_a_mark_carries_its_own_colour(self):
        r"""A tick is green and a cross is red wherever they appear,
        the same way round. The cross was muted grey, which made
        "nobody has passed this" look like "nothing here"."""
        assert "var(--accent)" in self.block("#progress-grid td.passed")
        assert "var(--bad)" in self.block("#progress-grid td.none-passed")
        assert "var(--warn)" in self.block("#progress-grid td.query")

    def test_every_highlight_colours_what_is_inside_it(self):
        """Not only the background. A 1/2 in an amber cell is amber."""
        for tone, token in (("justin", "--accent"), ("open", "--warn"),
                            ("stuck", "--bad")):
            body = self.block(f"#progress-grid td.tone-{tone}")
            assert f"background: var({token}-soft)" in body, tone
            assert f"color: var({token})" in body, tone

    def test_a_highlight_wins_over_the_mark_s_own_colour(self):
        """Same specificity, so source order decides, so the tones
        have to come after. A cross in an amber cell reads amber --
        the one pairing where the two actually disagree."""
        css = rules_only()
        assert css.index("#progress-grid td.none-passed") \
            < css.index("#progress-grid td.tone-open")
        assert css.index("#progress-grid td.part") \
            < css.index("#progress-grid td.tone-open")

    def test_the_fraction_takes_the_cell_s_colour(self):
        """`inherit`, not a colour of its own, or an amber cell would
        light its background and leave the number the wrong colour."""
        assert "color: inherit" in self.block("#progress-grid .cellcount")

    def test_the_legend_names_its_marks_rather_than_counting_them(self):
        """`:nth-child` on the legend is a claim about the order of
        the strip, not about what each mark is: reorder it and the
        colours follow the wrong items."""
        import re
        strip = [line for line in rules_only().splitlines()
                 if ".legend-item" in line and "nth-child" in line]
        assert not strip, strip
        for kind in ("passed", "none-passed", "query", "part"):
            assert re.search(r"\.legend-mark\." + re.escape(kind) + r"\b",
                             rules_only()), kind


def cell(attempts=0, passes=0, queries=0, absents=0, last=None, pin="old"):
    last = "null" if last is None else f'"{last}"'
    return (f"{{attempts:{attempts}, passes:{passes}, queries:{queries}, "
            f"absents:{absents}, lastSat:{last}, passedIn:\"{pin}\"}}")


LIT = '{stuckAt:2, recent:new Set(["NEW"])}'


def state(cell_js, threshold=1, lit=LIT):
    return run_progress_js(
        f"console.log(JSON.stringify(cellState({cell_js}, {threshold}, {lit})))")


class TestWhatACellShows:
    r"""One mark per cell, from `PRINT_TOOL_DESIGN.md` 17.

    Never run by the suite before these existed: `cellState` lives
    outside the block the markup tests lift, and `node --check` parses
    app.js without executing a line of it.
    """

    def test_nothing_recorded_shows_nothing(self):
        assert state("null")["kind"] == "none"
        assert state(cell())["kind"] == "none"

    def test_a_skill_only_ever_missed_is_a_blank_cell(self):
        """Did-not-sit is recorded and reaches the grid nowhere. A
        student who missed it twice looks exactly like one who was
        never handed it, which is what was asked for."""
        assert state(cell(1, absents=1))["kind"] == "none"
        assert state(cell(2, absents=2))["kind"] == "none"

    def test_an_absence_does_not_count_as_a_go(self):
        """Three attempts of which one was missed is two sittings,
        and the red threshold counts sittings."""
        out = state(cell(3, 0, absents=1, last="failed"))
        assert out["sat"] == 2 and out["tone"] == "stuck"

    def test_passing_is_a_tick_and_never_a_number(self):
        r"""`\u27132` meaning "passed at the second go" and
        `\u27132/2` meaning "two of the two needed" were the same
        shape in the same place."""
        out = state(cell(3, 1, last="passed"))
        assert out["kind"] == "passed" and out["mark"] == "pass"
        assert not out["count"]

    def test_part_way_is_the_fraction_and_no_glyph(self):
        out = state(cell(1, 1, last="passed"), threshold=2)
        assert out["kind"] == "part" and out["count"] == "1/2"
        assert not out["mark"]

    def test_nothing_passed_is_the_cross(self):
        out = state(cell(1, 0, last="failed"))
        assert out["kind"] == "none-passed" and out["mark"] == "fail"

    def test_a_query_most_recently_replaces_the_cross(self):
        out = state(cell(2, 0, queries=1, last="queried"))
        assert out["kind"] == "query" and out["mark"] == "query"

    def test_a_query_does_not_replace_a_fraction(self):
        """A cell part way through has a number worth more than the
        fact that the last paper is in question. The amber carries
        the question instead."""
        out = state(cell(2, 1, queries=1, last="queried"), threshold=2)
        assert out["kind"] == "part" and out["count"] == "1/2"
        assert out["tone"] == "open"

    def test_a_query_does_not_replace_a_tick(self):
        """Passed twice, sat again, and that one queried. The skill
        is still passed, and a settled skill is not in question."""
        out = state(cell(3, 2, queries=1, last="queried"), threshold=2)
        assert out["kind"] == "passed" and out["tone"] == ""

    def test_no_box_glyph_survives_anywhere(self):
        """The old vocabulary drew six of its seven states as
        variations on an outlined box. Every mark is now a named icon
        or nothing."""
        for js, threshold in ((cell(1, 0, last="failed"), 1),
                              (cell(2, 0, queries=1, last="queried"), 1),
                              (cell(1, 1, last="passed"), 2),
                              (cell(1, 1, last="passed"), 1),
                              (cell(1, absents=1), 1)):
            out = state(js, threshold)
            assert out["mark"] in ("", "pass", "fail", "query"), out


class TestWhatLightsACell:
    def test_red_once_the_sittings_reach_the_reader_s_number(self):
        assert state(cell(1, 0, last="failed"))["tone"] == ""
        assert state(cell(2, 0, last="failed"))["tone"] == "stuck"

    def test_zero_turns_the_red_off(self):
        out = state(cell(9, 0, last="failed"),
                    lit='{stuckAt:0, recent:new Set()}')
        assert out["tone"] == ""

    def test_amber_for_an_open_question_even_when_it_is_not_the_latest(self):
        """The parenthetical in the brief: amber applies whether or
        not the `?` is the glyph."""
        out = state(cell(3, 0, queries=1, last="failed"))
        assert out["kind"] == "none-passed" and out["tone"] == "open"

    def test_amber_beats_red(self):
        """Both fit here -- three goes, no passes, one queried. A
        query means the cell is not decided, and "stuck" is a
        judgement the query may overturn."""
        out = state(cell(3, 0, queries=1, last="failed"))
        assert out["tone"] == "open"

    def test_a_passed_skill_is_never_amber(self):
        out = state(cell(3, 1, queries=1, last="passed"))
        assert out["tone"] == ""

    def test_green_only_for_a_pass_in_the_reader_s_window(self):
        assert state(cell(1, 1, last="passed", pin="NEW"))["tone"] == "justin"
        assert state(cell(1, 1, last="passed", pin="old"))["tone"] == ""

    def test_an_empty_window_lights_nothing_green(self):
        out = state(cell(1, 1, last="passed", pin="NEW"),
                    lit="{stuckAt:2, recent:new Set()}")
        assert out["tone"] == ""


class TestTheOrderASkillColumnSortsIn:
    """One click on a skill brings the people who need it to the top."""

    def test_trouble_first_and_nothing_printed_last(self):
        out = run_progress_js(
            "const rows = ["
            f"['none-passed', {cell(2, 0, last='failed')}, 1],"
            f"['query', {cell(1, 0, 1, last='queried')}, 1],"
            f"['part', {cell(1, 1, last='passed')}, 2],"
            f"['passed', {cell(1, 1, last='passed')}, 1],"
            "['none', null, 1]];"
            "const keyed = rows.map(([n, c, t]) => [n, cellSortKey(c, t)]);"
            "keyed.sort((a, b) => a[1].localeCompare(b[1]));"
            "console.log(JSON.stringify(keyed.map(k => k[0])))")
        assert out == ["none-passed", "query", "part", "passed", "none"]

    def test_more_sittings_outrank_fewer(self):
        out = run_progress_js(
            "console.log(JSON.stringify(["
            f"cellSortKey({cell(5, 0, last='failed')}, 1),"
            f"cellSortKey({cell(2, 0, last='failed')}, 1)]))")
        assert out[0] < out[1]

    def test_ten_sittings_do_not_sort_below_two(self):
        out = run_progress_js(
            "console.log(JSON.stringify(["
            f"cellSortKey({cell(10, 0, last='failed')}, 1),"
            f"cellSortKey({cell(2, 0, last='failed')}, 1)]))")
        assert out[0] < out[1]

    def test_absences_do_not_move_a_row_up(self):
        """Sorting by a skill is about who needs it. Somebody who
        missed four papers is not four times as stuck as somebody who
        missed one; neither of them has sat it."""
        out = run_progress_js(
            "console.log(JSON.stringify(["
            f"cellSortKey({cell(4, 0, absents=4)}, 1),"
            f"cellSortKey({cell(1, 0, absents=1)}, 1)]))")
        assert out[0] == out[1]
