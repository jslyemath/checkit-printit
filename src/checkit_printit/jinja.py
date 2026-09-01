"""The Jinja environment the print templates are written against.

`textemplate.tex` files use `\\VAR{key}` rather than `{{key}}`, because braces
and percent signs mean something in LaTeX and the default Jinja delimiters
collide with them constantly.

These delimiters are copied from the `latex` PyPI package's `ENV_ARGS`, which
the original `pdfgenerator.py` used via `latex.jinja2.make_env`. They are
reproduced here rather than depended on: `latex` is unmaintained, its only other
use was shelling out to `pdflatex` (which we do directly), and a template
language's delimiters are not something to take a dependency for.

Verified against mat-106's 30 templates: 319 `\\VAR{}` uses, no `\\BLOCK{}`,
no line statements. The full set is kept anyway so an author can reach for a
loop without the environment changing under them.
"""

import jinja2

DELIMITERS = {
    "block_start_string": r"\BLOCK{",
    "block_end_string": "}",
    "variable_start_string": r"\VAR{",
    "variable_end_string": "}",
    "comment_start_string": r"\#{",
    "comment_end_string": "}",
    "line_statement_prefix": "%-",
    "line_comment_prefix": "%#",
}


class RecordingUndefined(jinja2.Undefined):
    """Renders as empty, like Jinja's default, but writes down what was missing.

    Neither of the obvious choices is right here.

    `StrictUndefined` raises, which sounds correct until you meet a real
    template: several `textemplate.tex` files keep a retired section
    commented out with LaTeX `%`. Jinja has no idea `%` is a comment, so it
    resolves `\\VAR{}` inside those lines and a strict environment refuses to
    render a template that is *working correctly*.

    The default renders empty and says nothing, which is how an outcome shipped
    "If one  represents one unit" to students for a year -- a template asking
    for a key the generator never set, leaving a hole in the sentence.

    So: render empty, and collect the names. The caller decides whether a given
    miss matters, and can report every one of them at the end rather than dying
    on the first.
    """

    _missing = None

    def _fail_with_undefined_error(self, *args, **kwargs):
        self._record()
        return ""

    def __str__(self):
        self._record()
        return ""

    def _record(self):
        if self._missing is not None and self._undefined_name:
            self._missing.add(self._undefined_name)


def make_env(missing=None, **kwargs):
    """A Jinja environment for LaTeX templates.

    `autoescape` is off deliberately. Jinja's escaping is for HTML, and applying
    it here would mangle every backslash in the generated mathematics. The
    generator is responsible for producing valid LaTeX; see the SpaTeXt guide's
    notes on raw strings.

    Pass a `set` as `missing` to be told which keys a template asked for and did
    not get.
    """
    undefined = RecordingUndefined
    if missing is not None:
        undefined = type("RecordingUndefined", (RecordingUndefined,),
                         {"_missing": missing})

    settings = dict(DELIMITERS)
    settings.update(trim_blocks=True, autoescape=False, undefined=undefined)
    settings.update(kwargs)
    return jinja2.Environment(**settings)
