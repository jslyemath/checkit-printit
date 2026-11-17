"""Running pdflatex, and believing it only when it succeeded.

RV-5 of the 2026-11-16 review: `compile_pdf` asked one question -- does
`main.pdf` exist? -- and never looked at pdflatex's exit code or removed
an earlier PDF. Built a second time with an error in the *preamble*,
pdflatex stops before it opens its output, the first build's PDF is
still there, and it was handed back as this build's. The platform
learned "a PDF existing is not a clean compile" in `wrapper/tikz.py`;
this was the second copy of the same code.

Real pdflatex, because the behaviour being tested is pdflatex's.
"""

import os
import shutil

import pytest

from checkit_printit import compile as compile_mod

pytestmark = pytest.mark.skipif(shutil.which("pdflatex") is None,
                                reason="needs pdflatex")

GOOD = "\\documentclass{article}\n\\begin{document}\nfirst\n\\end{document}\n"
BAD_PREAMBLE = ("\\documentclass{article}\n\\usepackage{no-such-package-xyz}\n"
                "\\begin{document}\nsecond\n\\end{document}\n")
BAD_LATE = ("\\documentclass{article}\n\\begin{document}\npage one\\newpage\n"
            "\\undefinedmacroxyz\n\\end{document}\n")


def write(folder, text):
    with open(os.path.join(folder, "main.tex"), "w", encoding="utf-8") as f:
        f.write(text)


def test_a_clean_document_compiles(tmp_path):
    write(tmp_path, GOOD)
    assert os.path.isfile(compile_mod.compile_pdf(str(tmp_path)))


def test_an_error_in_the_preamble_is_not_last_week_s_pdf(tmp_path):
    write(tmp_path, GOOD)
    compile_mod.compile_pdf(str(tmp_path))
    write(tmp_path, BAD_PREAMBLE)
    with pytest.raises(compile_mod.CompileError):
        compile_mod.compile_pdf(str(tmp_path))


def test_the_stale_pdf_is_not_left_to_be_mistaken_for_this_one(tmp_path):
    """Somebody opening the folder by hand should not find it either."""
    write(tmp_path, GOOD)
    compile_mod.compile_pdf(str(tmp_path))
    write(tmp_path, BAD_PREAMBLE)
    with pytest.raises(compile_mod.CompileError):
        compile_mod.compile_pdf(str(tmp_path))
    assert not os.path.exists(tmp_path / "main.pdf")


def test_an_error_after_the_first_page_is_refused(tmp_path):
    write(tmp_path, BAD_LATE)
    with pytest.raises(compile_mod.CompileError):
        compile_mod.compile_pdf(str(tmp_path))


def test_an_error_only_on_the_second_pass_is_refused(tmp_path):
    """The case only the exit code catches. Pass one succeeds and writes
    a PDF; pass two, reading the labels pass one wrote, fails before it
    ships a page -- so pass one's PDF is still there, looking finished.
    Errors that appear once cross-references resolve are exactly this."""
    write(tmp_path, "\\documentclass{article}\n\\begin{document}\nfirst\n"
                    "\\makeatletter\\@ifundefined{r@x}{}{\\undefinedmacroxyz}"
                    "\\makeatother\n\\label{x}\n\\end{document}\n")
    with pytest.raises(compile_mod.CompileError):
        compile_mod.compile_pdf(str(tmp_path))


def test_the_message_carries_the_first_error(tmp_path):
    write(tmp_path, BAD_PREAMBLE)
    with pytest.raises(compile_mod.CompileError, match="no-such-package-xyz"):
        compile_mod.compile_pdf(str(tmp_path))
