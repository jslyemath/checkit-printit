"""Tests for checkit-printit.

Weighted toward the things that would be wrong *silently*: a version handed to
two neighbours, a key that does not match the handouts, an output folder that
only compiles because the bank happened to be next to it.
"""

import os
import random
import shutil
import subprocess
import sys

import pytest

from checkit_printit import assemble as assemble_mod
from checkit_printit import compile as compile_mod
from checkit_printit import publication as pub_mod
from checkit_printit import roster as roster_mod
from checkit_printit import seating, spatext, theme
from checkit_printit.bank import Bank, BankError, FIRST_PRINTABLE_SEED
from checkit_printit.jinja import make_env


# ---------------------------------------------------------------- bank ----

class TestBank:
    def test_printable_seeds_start_above_the_published_range(self, bank_dir):
        """Seeds 50-399 are published in derived.json *with their answers*.
        Printing from there would print a quiz whose answers are a fetch away."""
        seeds = Bank(bank_dir).printable_seeds("AD")
        assert seeds, "the fixture bank generated nothing printable"
        assert min(seeds) >= FIRST_PRINTABLE_SEED

    def test_variant_labels_are_readable(self, bank_dir):
        bank = Bank(bank_dir)
        labels = {bank.variant("AD", s) for s in bank.printable_seeds("AD")}
        assert labels == {"small", "large"}

    def test_asking_for_a_variant_narrows_the_pool(self, bank_dir):
        bank = Bank(bank_dir)
        small = bank.seeds_with_variant("AD", "small")
        assert small
        assert all(bank.variant("AD", s) == "small" for s in small)

    def test_an_unknown_variant_says_what_exists(self, bank_dir):
        with pytest.raises(BankError, match="small"):
            Bank(bank_dir).seeds_with_variant("AD", "enormous")

    def test_a_directory_that_is_not_a_bank_says_so(self, tmp_path):
        with pytest.raises(BankError, match="bank.xml"):
            Bank(str(tmp_path))


# -------------------------------------------------------------- roster ----

class TestRoster:
    def write(self, tmp_path, body):
        p = tmp_path / "roster.toml"
        p.write_text(body, encoding="utf-8")
        return str(p)

    def test_loads_students(self, tmp_path):
        r = roster_mod.load(self.write(tmp_path, """
            [[student]]
            name = "Ada"
            skills = ["AD"]
        """))
        assert len(r) == 1
        assert r.students[0].name == "Ada"

    def test_a_nameless_student_is_refused(self, tmp_path):
        with pytest.raises(roster_mod.RosterError, match="no name"):
            roster_mod.load(self.write(tmp_path, '[[student]]\nskills = ["AD"]'))

    def test_skills_used_keeps_first_seen_order(self, tmp_path):
        """The key follows this order, so it can be checked against the stack."""
        r = roster_mod.load(self.write(tmp_path, """
            [[student]]
            name = "Ada"
            skills = ["SU", "AD"]
            [[student]]
            name = "Bo"
            skills = ["AD"]
        """))
        assert r.skills_used() == ["SU", "AD"]


class TestSelectionModes:
    def roster(self):
        return roster_mod.Roster([
            roster_mod.Student(name="Ada", skills=["AD"]),
            roster_mod.Student(name="Bo", skills=[]),
        ])

    def test_simply_print_overrides_everyone(self):
        out = roster_mod.apply_selection_modes(self.roster(), simply_print=["SU"])
        assert [s.skills for s in out] == [["SU"], ["SU"]]

    def test_default_applies_only_to_the_student_who_chose_nothing(self):
        out = roster_mod.apply_selection_modes(self.roster(), default_when_missing=["SU"])
        assert [s.skills for s in out] == [["AD"], ["SU"]]

    def test_append_adds_to_both_and_does_not_duplicate(self):
        out = roster_mod.apply_selection_modes(
            self.roster(), default_when_missing=["SU"], append_for_everyone=["AD"])
        assert [s.skills for s in out] == [["AD"], ["SU", "AD"]]

    def test_the_input_roster_is_not_mutated(self):
        original = self.roster()
        roster_mod.apply_selection_modes(original, simply_print=["SU"])
        assert original.students[0].skills == ["AD"]


# ------------------------------------------------------------- seating ----

class TestSeating:
    def write(self, tmp_path, body):
        p = tmp_path / "seating.toml"
        p.write_text(body, encoding="utf-8")
        return str(p)

    def test_versions_alternate_so_neighbours_differ(self, tmp_path):
        chart = seating.load(self.write(tmp_path, """
            [[group]]
            seats = ["A1", "A2", "A3", "A4"]
        """))
        assert [s.version for s in chart] == ["A", "B", "A", "B"]
        assert chart.collisions() == []

    def test_each_group_restarts_the_alternation(self, tmp_path):
        """Groups are tables. Two tables are not adjacent to each other, so the
        pattern restarts rather than running on."""
        chart = seating.load(self.write(tmp_path, """
            [[group]]
            seats = ["A1", "A2", "A3"]
            [[group]]
            seats = ["B1", "B2"]
        """))
        assert [s.version for s in chart] == ["A", "B", "A", "A", "B"]
        assert chart.collisions() == []

    def test_a_pinned_seat_keeps_its_version(self, tmp_path):
        chart = seating.load(self.write(tmp_path, """
            [[group]]
            seats = [{name = "A1", version = "B"}, "A2"]
        """))
        assert chart.version_of("A1") == "B"

    def test_a_pin_that_collides_is_reported_not_refused(self, tmp_path):
        """Pinning is deliberate; the operator may have a reason. Say so and
        let them decide."""
        chart = seating.load(self.write(tmp_path, """
            [[group]]
            seats = ["A1", {name = "A2", version = "A"}]
        """))
        collisions = chart.collisions()
        assert len(collisions) == 1
        assert {s.name for s in collisions[0]} == {"A1", "A2"}

    def test_one_version_is_refused(self, tmp_path):
        with pytest.raises(seating.SeatingError, match="at least two"):
            seating.load(self.write(tmp_path, 'versions = ["A"]\n[[group]]\nseats = ["A1"]'))

    def test_an_unknown_pin_is_refused(self, tmp_path):
        with pytest.raises(seating.SeatingError, match="not in"):
            seating.load(self.write(tmp_path,
                '[[group]]\nseats = [{name = "A1", version = "Z"}]'))

    def test_order_puts_unseated_students_last_rather_than_dropping_them(self, tmp_path):
        chart = seating.load(self.write(tmp_path, '[[group]]\nseats = ["Bo"]'))
        r = roster_mod.Roster([
            roster_mod.Student(name="Ada", skills=[]),
            roster_mod.Student(name="Bo", skills=[]),
        ])
        ordered, unseated = chart.order(r)
        assert [s.name for s in ordered] == ["Bo"]
        assert [s.name for s in unseated] == ["Ada"]


# --------------------------------------------------------------- jinja ----

class TestJinja:
    def test_var_delimiters_are_what_the_templates_use(self):
        env = make_env()
        assert env.from_string(r"\VAR{x}!").render(x=3) == "3!"

    def test_backslashes_survive(self):
        """Jinja's autoescape is for HTML. Left on, it would mangle every
        command in the generated mathematics."""
        env = make_env()
        assert env.from_string(r"\VAR{m}").render(m=r"\frac{1}{2}") == r"\frac{1}{2}"

    def test_a_missing_key_renders_empty_and_is_recorded(self):
        """Neither raising nor silence is right: a retired block commented out
        with LaTeX % still resolves its \\VAR, so raising breaks a working
        template -- but silence is how a hole in a sentence ships."""
        seen = set()
        env = make_env(missing=seen)
        assert env.from_string(r"a\VAR{nope}b").render() == "ab"
        assert seen == {"nope"}


# ---------------------------------------------------------- publication ----

class TestPublication:
    def test_paths_resolve_relative_to_the_file(self, tmp_path, bank_dir):
        sub = tmp_path / "course"
        sub.mkdir()
        (sub / "publication.toml").write_text(
            f'[bank]\npath = {bank_dir!r}\n[roster]\npath = "roster.toml"\n',
            encoding="utf-8")
        pub = pub_mod.load(str(sub / "publication.toml"))
        assert pub.roster_path == os.path.normpath(str(sub / "roster.toml"))

    def test_a_missing_bank_is_refused_up_front(self, tmp_path):
        p = tmp_path / "publication.toml"
        p.write_text('[bank]\npath = "nowhere"\n', encoding="utf-8")
        with pytest.raises(pub_mod.PublicationError, match="does not exist"):
            pub_mod.load(str(p))


# ------------------------------------------------------------ assembly ----

def make_publication(bank_dir, **kwargs):
    return pub_mod.Publication(
        course="TEST 101", semester="Fall", professor="Nobody",
        title="Checkpoint", date="2026-01-01", bank_path=bank_dir, **kwargs)


def two_students():
    return roster_mod.Roster([
        roster_mod.Student(name="Ada", section="1", skills=["AD"]),
        roster_mod.Student(name="Bo", section="1", skills=["AD", "SU"]),
    ])


def chart_for(tmp_path, names):
    p = tmp_path / "seating.toml"
    seats = ", ".join(f'"{n}"' for n in names)
    p.write_text(f"[[group]]\nseats = [{seats}]\n", encoding="utf-8")
    return seating.load(str(p))


class TestAssembly:
    def build(self, bank_dir, tmp_path, publication=None, roster=None, chart=None):
        publication = publication or make_publication(bank_dir)
        roster = roster or two_students()
        chart = chart if chart is not None else chart_for(tmp_path, ["Ada", "Bo"])
        out = str(tmp_path / "out")
        source, _ = theme.load(bank_dir)
        report = assemble_mod.assemble(publication, roster, chart, out, source,
                                       rng=random.Random(1))
        return out, report

    def test_neighbours_get_different_versions(self, bank_dir, tmp_path):
        out, report = self.build(bank_dir, tmp_path)
        main = open(os.path.join(out, "main.tex"), encoding="utf-8").read()
        ada = main.split(r"\setname{Ada}")[1].split(r"\preparefornextstudent")[0]
        bo = main.split(r"\setname{Bo}")[1].split(r"\preparefornextstudent")[0]
        assert "AD/AD v" in ada and "AD/AD v" in bo
        assert ada.split("AD/AD v")[1][:4] != bo.split("AD/AD v")[1][:4]

    def test_every_referenced_skill_file_exists(self, bank_dir, tmp_path):
        """The failure that produced no PDF the first time this ran."""
        out, _ = self.build(bank_dir, tmp_path)
        main = open(os.path.join(out, "main.tex"), encoding="utf-8").read()
        import re
        for ref in re.findall(r"\\skillpage\{([^}]+)\}", main):
            assert os.path.isfile(os.path.join(out, ref + ".tex")), ref

    def test_keys_are_deduplicated_and_ordered_by_the_bank(self, bank_dir, tmp_path):
        pub = make_publication(bank_dir, keys=True, key_copies=1)
        out, report = self.build(bank_dir, tmp_path, publication=pub)
        main = open(os.path.join(out, "main.tex"), encoding="utf-8").read()
        key_block = main.split("% ---- answer keys")[1]
        import re
        refs = re.findall(r"\\skillpage\{([^}]+)\}", key_block)
        assert len(refs) == len(set(refs)), "a key page was printed twice"
        slugs = [r.split("/")[0] for r in refs]
        assert slugs == sorted(slugs, key=["AD", "SU"].index)

    def test_no_keys_when_asked_for_none(self, bank_dir, tmp_path):
        pub = make_publication(bank_dir, keys=False)
        out, _ = self.build(bank_dir, tmp_path, publication=pub)
        main = open(os.path.join(out, "main.tex"), encoding="utf-8").read()
        assert r"\setboolean{anstoggle}{true}" not in main
        assert "answer keys" not in main

    def test_extras_are_appended_with_a_blank_name(self, bank_dir, tmp_path):
        pub = make_publication(bank_dir, extras=(pub_mod.Extra("AD", 2),))
        out, report = self.build(bank_dir, tmp_path, publication=pub)
        assert report["extras"] == 2
        main = open(os.path.join(out, "main.tex"), encoding="utf-8").read()
        extras_block = main.split("% ---- extras")[1]
        assert extras_block.count(r"\setname{Blank}") == 2
        assert main.index(r"\setname{Ada}") < main.index("% ---- extras")

    def test_names_off_blanks_every_student(self, bank_dir, tmp_path):
        pub = make_publication(bank_dir, names=False)
        out, _ = self.build(bank_dir, tmp_path, publication=pub)
        main = open(os.path.join(out, "main.tex"), encoding="utf-8").read()
        assert r"\setname{Ada}" not in main
        assert r"\setname{Blank}" in main

    def test_a_pinned_seed_is_used(self, bank_dir, tmp_path):
        seed = Bank(bank_dir).printable_seeds("AD")[0]
        pub = make_publication(bank_dir, seeds={"A": seed, "B": seed})
        out, report = self.build(bank_dir, tmp_path, publication=pub)
        assert report["seeds"][("A", "AD")] == seed

    def test_a_pinned_seed_outside_the_printable_range_is_refused(self, bank_dir, tmp_path):
        pub = make_publication(bank_dir, seeds={"A": 3})
        with pytest.raises(assemble_mod.AssemblyError, match="pinned"):
            self.build(bank_dir, tmp_path, publication=pub)

    def test_an_unknown_skill_names_the_student(self, bank_dir, tmp_path):
        r = roster_mod.Roster([roster_mod.Student(name="Ada", skills=["NOPE"])])
        with pytest.raises(assemble_mod.AssemblyError, match="Ada"):
            self.build(bank_dir, tmp_path, roster=r,
                       chart=chart_for(tmp_path, ["Ada", "Bo"]))

    def test_descriptions_are_generated_from_bank_xml(self, bank_dir, tmp_path):
        out, _ = self.build(bank_dir, tmp_path)
        text = open(os.path.join(out, "Skill Descriptions.tex"), encoding="utf-8").read()
        assert r"\setskilldesc{AD}{I can add two numbers.}" in text

    def test_preview_writes_nothing(self, bank_dir, tmp_path):
        out = str(tmp_path / "nothing")
        source, _ = theme.load(bank_dir)
        assemble_mod.assemble(make_publication(bank_dir), two_students(),
                              chart_for(tmp_path, ["Ada", "Bo"]), out, source,
                              rng=random.Random(1), dry_run=True)
        assert not os.path.exists(out)

    def test_an_outcome_without_a_print_template_renders_from_spatext(
            self, bank_dir, tmp_path):
        """The intended default: one template per outcome, not two. SU has no
        textemplate.tex, so it comes through latex.xsl."""
        out, _ = self.build(bank_dir, tmp_path)
        files = [f for f in os.listdir(os.path.join(out, "SU")) if f.endswith(".tex")]
        assert files
        body = open(os.path.join(out, "SU", files[0]), encoding="utf-8").read()
        assert r"\skillheader{SU}" in body, "no skill header"
        assert r"\setvseed{" in body, "no version stamp"
        assert "SpaTeXt Commands" not in body, "the per-file preamble was not stripped"
        assert r"\stxKnowl{" in body, "no rendered body"

    def test_the_spatext_route_still_carries_the_answer(self, bank_dir, tmp_path):
        """The outtro has to survive, or a key prints blank."""
        out, _ = self.build(bank_dir, tmp_path)
        files = [f for f in os.listdir(os.path.join(out, "SU")) if f.endswith(".tex")]
        body = open(os.path.join(out, "SU", files[0]), encoding="utf-8").read()
        assert r"\stxOuttro{" in body

    def test_main_tex_defines_the_spatext_commands(self, bank_dir, tmp_path):
        r"""Stripped from each skill file, so they must exist once in main.tex.

        \stxOuttro must obey anstoggle without using \ans: \ans wraps its
        argument in \textcolor, which is not long, and a rendered outtro
        routinely ends in a blank line. That combination fails to compile."""
        out, _ = self.build(bank_dir, tmp_path)
        main = open(os.path.join(out, "main.tex"), encoding="utf-8").read()
        assert r"\providecommand{\stxKnowl}" in main
        assert "ifanstoggle" in main, (
            "stxOuttro must not route through \\ans: \\textcolor is not long, "
            "and a rendered outtro routinely ends in a blank line")

    def test_the_theme_travels_with_the_output(self, bank_dir, tmp_path):
        out, _ = self.build(bank_dir, tmp_path)
        assert os.path.isfile(os.path.join(out, "skillcheckpoints.sty"))


# --------------------------------------------------- SpaTeXt in a field ----

class TestSpatextFields:
    """A generator's data fields can carry inline SpaTeXt.

    `template.xml` inserts them with triple braces, so the web renders them.
    `textemplate.tex` inserts them into LaTeX, where a tag is only text -- which
    is how `<glyphs font="egyptian">` once carried a hieroglyph into pdflatex.
    """

    def test_inline_maths_becomes_latex(self):
        assert spatext.to_latex("<m>91</m> is composite") == r"\(91\) is composite"

    def test_glyphs_use_the_latex_they_carry_not_their_unicode(self):
        """The Unicode is for the screen. `@latex` is the print form, and the
        stylesheet has always known to prefer it."""
        out = spatext.to_latex(
            '<glyphs font="egyptian" latex="\\Hone\\Hten">\U000133fa</glyphs>')
        assert out == r"\Hone\Hten"
        assert "\U000133fa" not in out

    def test_nobreak_survives_as_mbox(self):
        """The reason <nobreak> exists: a statement that must not break across
        lines. Losing it in print would be silent and would look fine."""
        assert spatext.to_latex("<nobreak><m>7 \\cdot 13</m></nobreak>") \
            == r"\mbox{\(7 \cdot 13\)}"

    def test_plain_latex_is_left_alone(self):
        """Most fields are bare LaTeX. Parsing them as XML would fail on
        characters that are perfectly good LaTeX, so they are not parsed."""
        for value in (r"3 < 5", r"x \frac{1}{2} y", "55,476", r"a & b"):
            assert spatext.to_latex(value) == value

    def test_markup_that_will_not_parse_names_the_field(self):
        with pytest.raises(spatext.SpatextError) as exc:
            spatext.to_latex("<m>1 & 2</m>", where="N2's answer")
        assert "N2's answer" in str(exc.value)

    def test_a_print_template_gets_rendered_fields(self, bank_dir, tmp_path):
        """End to end, with markup put into the bank's own data.

        The fixture's generator emits plain numbers, so this seeds the bank with
        what mat-106's generators actually produce and follows it to the .tex.
        """
        import json

        root = str(tmp_path / "bank")
        shutil.copytree(bank_dir, root)
        seeds_json = os.path.join(root, "assets", "AD", "generated", "seeds.json")
        with open(seeds_json, encoding="utf-8") as f:
            payload = json.load(f)
        for entry in payload["seeds"]:
            entry["data"]["answer"] = "<m>%s</m>" % entry["data"]["answer"]
        with open(seeds_json, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        out = str(tmp_path / "out")
        source, _ = theme.load(root)
        assemble_mod.assemble(make_publication(root), two_students(),
                              chart_for(tmp_path, ["Ada", "Bo"]), out, source,
                              rng=random.Random(1))
        for name in os.listdir(os.path.join(out, "AD")):
            body = open(os.path.join(out, "AD", name), encoding="utf-8").read()
            assert "<m>" not in body, "markup reached the LaTeX file"
            assert "\\(" in body, "the maths was dropped rather than rendered"


# --------------------------------------------------------------- figures ----

class TestFigures:
    """Figures are copied by scanning the written skill files.

    mat-106's R1 holds 38 hand-drawn PNGs directly in `assets/R1/`, and one quiz
    needs two of them. Copying `assets/<slug>/generated/` -- which is where the
    machine-made ones go -- missed every hand-drawn one, and the first real quiz
    failed on a `pemdas-1p.png` that was sitting in the bank all along.
    """

    def bank_with_figure(self, bank_dir, tmp_path, reference, on_disk=()):
        """A copy of the fixture bank whose AD template references `reference`."""
        root = str(tmp_path / "bank")
        shutil.copytree(bank_dir, root)
        for rel in on_disk:
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n")          # enough to exist
        tex = os.path.join(root, "outcomes", "AD", "textemplate.tex")
        with open(tex, encoding="utf-8") as f:
            body = f.read()
        with open(tex, "w", encoding="utf-8") as f:
            f.write(body + "\n\\includegraphics{%s}\n" % reference)
        return root

    def build(self, root, tmp_path):
        out = str(tmp_path / "out")
        source, _ = theme.load(root)
        assemble_mod.assemble(make_publication(root), two_students(),
                              chart_for(tmp_path, ["Ada", "Bo"]), out, source,
                              rng=random.Random(1))
        return out

    def test_a_hand_drawn_figure_beside_the_slug_is_copied(self, bank_dir, tmp_path):
        root = self.bank_with_figure(bank_dir, tmp_path, "assets/AD/pemdas-1p.png",
                                     on_disk=["assets/AD/pemdas-1p.png"])
        out = self.build(root, tmp_path)
        assert os.path.isfile(os.path.join(out, "assets", "AD", "pemdas-1p.png"))

    def test_only_what_is_referenced_travels(self, bank_dir, tmp_path):
        """38 PNGs in the bank, 2 in the quiz. The folder is meant to be
        archived, so it carries what it uses."""
        root = self.bank_with_figure(
            bank_dir, tmp_path, "assets/AD/wanted.png",
            on_disk=["assets/AD/wanted.png", "assets/AD/unused.png"])
        out = self.build(root, tmp_path)
        assert os.path.isfile(os.path.join(out, "assets", "AD", "wanted.png"))
        assert not os.path.exists(os.path.join(out, "assets", "AD", "unused.png"))

    def test_a_figure_the_bank_does_not_have_is_named(self, bank_dir, tmp_path):
        """Otherwise it surfaces as `using draft setting` a thousand log lines
        before pdflatex gives up."""
        root = self.bank_with_figure(bank_dir, tmp_path, "assets/AD/gone.png")
        with pytest.raises(assemble_mod.AssemblyError) as exc:
            self.build(root, tmp_path)
        assert "assets/AD/gone.png" in str(exc.value)

    def test_a_figure_outside_the_bank_is_refused(self, bank_dir, tmp_path):
        """Copying it would land the file outside the output folder, and the
        folder has to stand alone."""
        root = self.bank_with_figure(bank_dir, tmp_path, "../elsewhere.png")
        with pytest.raises(assemble_mod.AssemblyError):
            self.build(root, tmp_path)


# --------------------------------------------------------------- compile ----

class TestCompileLog:
    def test_a_byte_the_locale_cannot_decode_does_not_lose_the_log(self):
        """pdflatex echoes font and file names byte for byte. With text=True the
        locale decides the encoding, so on a cp1252 Windows console one 0x81
        killed the reader thread, left stdout as None, and turned a real LaTeX
        error into a TypeError six lines later."""
        result = subprocess.run(
            [sys.executable, "-c",
             r"import sys; sys.stdout.buffer.write(b'A\x81B')"],
            capture_output=True, **compile_mod.DECODING)
        assert result.stdout is not None
        assert result.stdout.startswith("A") and result.stdout.endswith("B")


# ---------------------------------------------------------- integration ----

pdflatex = shutil.which("pdflatex")


@pytest.mark.skipif(pdflatex is None, reason="pdflatex is not installed")
class TestTheOutputCompiles:
    def test_it_builds_somewhere_else_entirely(self, bank_dir, tmp_path):
        """The promise the whole output format exists for: the folder compiles
        with `pdflatex main.tex` and nothing else -- no tool, no bank, no
        TEXINPUTS. Copied elsewhere first, because compiling it where it was
        built would prove nothing about what it depends on."""
        out = str(tmp_path / "built")
        source, _ = theme.load(bank_dir)
        assemble_mod.assemble(make_publication(bank_dir), two_students(),
                              chart_for(tmp_path, ["Ada", "Bo"]), out, source,
                              rng=random.Random(1))

        moved = str(tmp_path / "moved")
        shutil.copytree(out, moved)

        for _ in range(2):
            subprocess.run([pdflatex, "-interaction=nonstopmode", "-halt-on-error",
                            "main.tex"], cwd=moved, capture_output=True, timeout=300)
        pdf = os.path.join(moved, "main.pdf")
        assert os.path.isfile(pdf), _why(moved)
        assert os.path.getsize(pdf) > 1000


def _why(directory):
    log = os.path.join(directory, "main.log")
    if not os.path.isfile(log):
        return "no PDF and no log"
    text = open(log, encoding="utf-8", errors="replace").read()
    for i, line in enumerate(text.splitlines()):
        if line.startswith("! "):
            return "\n".join(text.splitlines()[i:i + 8])
    return "no PDF; the log has no '!' line"
