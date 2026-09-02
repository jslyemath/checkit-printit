"""Rendering the SpaTeXt a generator puts inside its own data fields.

A generator returns strings, and some of those strings carry inline SpaTeXt:
`<m>` for maths, `<em>` for emphasis, `<glyphs>` for a numeral in an ancient
script, `<nobreak>` for something that must not break across lines. `template.xml`
inserts such a field with triple braces, so the markup becomes part of the
document the stylesheets transform, and the web gets it right.

`textemplate.tex` inserts the same field into LaTeX, where a tag is just text.
That is how `<glyphs font="egyptian" latex="\\Hone">` reached pdflatex intact and
took a hieroglyph with it.

So the print path renders those fields the same way the web does: through
`latex.xsl`, the one place that knows `<m>` is `\\(...\\)` and that `<glyphs>`
carries its own LaTeX in an attribute. Reusing the stylesheet rather than
reimplementing it means a fix to the vocabulary reaches print for free.
"""

import re
from xml.sax.saxutils import unescape

from lxml import etree

from checkit.static import read_resource

#: Only these fields get transformed. A field with no tag in it is plain text or
#: plain LaTeX -- `x \\lt y`, `3 & 4` -- and XML-parsing it would fail on
#: characters that are perfectly good LaTeX. A field WITH a tag is already
#: XML-safe, because `template.xml` pastes it in raw and the web build would
#: have failed otherwise.
_TAG_RE = re.compile(r"<\s*/?\s*[a-zA-Z][a-zA-Z0-9-]*(\s[^<>]*)?/?>")

#: The transform needs a document, and the smallest one that reaches the inline
#: templates is a knowl holding one paragraph.
_WRAPPER = (
    '<knowl mode="exercise" xmlns="https://spatext.clontz.org" version="0.3">'
    "<content><p>%s</p></content></knowl>"
)

#: latex.xsl prefixes a block defining \\stxKnowl and friends, closed by a rule
#: of percent signs, then emits `\\stxKnowl{ ... }`. The content is what sits
#: between that opening brace and the final closing one.
_PREAMBLE_END = "%" * 28
_BODY_OPEN = "\\stxKnowl{"

_transform = None


class SpatextError(Exception):
    pass


def _stylesheet():
    """Compiled once: parsing latex.xsl per field is slow and pointless."""
    global _transform
    if _transform is None:
        _transform = etree.XSLT(etree.fromstring(read_resource("latex.xsl")))
    return _transform


def has_markup(value):
    return isinstance(value, str) and bool(_TAG_RE.search(value))


def to_latex(value, where=""):
    """Inline SpaTeXt as LaTeX.

    A string with no markup still gets its XML entities resolved. A field
    destined for a `{{{triple brace}}}` slot has to arrive already escaped or
    `template.xml` would not parse, so N2's alignment ampersands are `&amp;` in
    the data. The web gets them back when the XML is parsed; print never parsed
    anything, so `\\begin{align*}` received `&amp;=` and typeset a column break
    followed by the word `amp;`.

    Unescaping is safe for a field that was never escaped: a raw `&` is left
    alone, since it matches no entity.
    """
    if not has_markup(value):
        return unescape(value) if isinstance(value, str) else value
    doc = _WRAPPER % value
    try:
        rendered = str(_stylesheet()(etree.fromstring(doc.encode("utf-8"))))
    except etree.XMLSyntaxError as exc:
        raise SpatextError(
            f"{where or 'a field'} looks like SpaTeXt but will not parse as "
            f"XML: {exc}\n\nThe value was:\n  {value!r}\n\n"
            "A generator field carrying markup has to be valid XML, since "
            "template.xml pastes it in raw."
        ) from exc
    return _unwrap(rendered)


def _unwrap(rendered):
    """The content latex.xsl put inside \\stxKnowl{...}."""
    if _PREAMBLE_END in rendered:
        rendered = rendered.split(_PREAMBLE_END, 1)[1]
    start = rendered.find(_BODY_OPEN)
    if start == -1:
        return rendered.strip()
    body = rendered[start + len(_BODY_OPEN):]
    end = body.rfind("}")
    if end != -1:
        body = body[:end]
    return body.strip()


def render_fields(data, slug=""):
    """Every field of one exercise, with its SpaTeXt turned into LaTeX."""
    return {
        key: to_latex(value, where=f"{slug}'s {key}" if slug else key)
        for key, value in data.items()
    }
