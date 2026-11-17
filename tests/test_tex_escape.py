"""Text on its way into LaTeX is escaped.

RV-12 of the 2026-11-16 review. `main.tex` and `Skill Descriptions.tex` are
built with f-strings, and nothing escaped what went in: a name, a section,
the course, the semester, the instructor, the title or a skill
description holding & % # _ $ { } ~ ^ or a backslash was a compile error
-- or worse, silently lost text, because % starts a comment and swallows
the closing brace and the rest of the line.

The student id is deliberately not escaped: it is written verbatim into
the page index, and is digits.
"""

import os
import shutil
import subprocess

import pytest

from checkit_printit import assemble
from checkit_printit.assemble import Handout, tex_escape

NASTY = "Ana & Bo's 100% #1 {x} $5 a_b ~c ^d \\e"


class Pub:
    course = "Numbers & Operations"
    semester = "Fall 100%"
    professor = "Dr_Slye"
    printed_title = "Checkpoint #2"
    ids = True
    codes = True


def tex():
    h = Handout(name=NASTY, section="8&2", versions=[("AD", 401)],
                sid="806000001")
    return assemble.main_tex(Pub(), [h], [], None)


def test_the_name_is_escaped():
    assert "\\setname{" + tex_escape(NASTY) + "}" in tex()


def test_the_header_fields_are_escaped():
    out = tex()
    assert r"\acadclass{Numbers \& Operations}" in out
    assert r"\date{Fall 100\%}" in out
    assert r"\author{Dr\_Slye}" in out
    assert r"\title{Checkpoint \#2}" in out


def test_the_section_is_escaped():
    assert r"\setsect{8\&2}" in tex()


def test_the_student_id_is_left_alone():
    assert r"\setsid{806000001}" in tex()


def test_blank_stays_the_word_the_theme_looks_for():
    h = Handout(name="", section="", versions=[("AD", 401)], blank_name=True)
    out = assemble.main_tex(Pub(), [h], [], None)
    assert r"\setname{Blank}" in out and r"\setsect{Blank}" in out


def test_a_description_is_escaped():
    class Bank:
        def description(self, slug):
            return "I can add 50% & more"

        def color(self, slug):
            return None
    out = assemble.descriptions_tex(Bank(), ["AD"])
    assert r"\setskilldesc{AD}{I can add 50\% \& more}" in out


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="needs pdflatex")
def test_the_escaped_text_compiles_and_reads_as_written(tmp_path):
    """Not only "no error": the text has to come out as it went in."""
    (tmp_path / "t.tex").write_text(
        "\\documentclass{article}\\usepackage[T1]{fontenc}\n"
        "\\begin{document}\n" + tex_escape(NASTY) + "\n\\end{document}\n",
        encoding="utf-8")
    result = subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "t.tex"],
        cwd=tmp_path, capture_output=True)
    assert result.returncode == 0
    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        subprocess.run([pdftotext, "t.pdf", "t.txt"], cwd=tmp_path, check=True)
        text = " ".join((tmp_path / "t.txt").read_text(
            encoding="utf-8", errors="replace").split())
        for piece in ("Ana & Bo", "100%", "#1", "{x}", "$5", "a_b", "~c",
                      "^d", "\\e"):
            assert piece in text, piece
