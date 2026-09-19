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
from checkit_printit import manifest as manifest_mod
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

    def test_one_version_is_fine_when_nobody_shares_a_table(self, tmp_path):
        """A single-student makeup has no neighbour, so demanding a second
        version would mean inventing a paper nobody receives."""
        chart = seating.load(self.write(tmp_path, """
            versions = ["A"]
            [[group]]
            seats = ["A1"]
        """))
        assert [s.version for s in chart] == ["A"]
        assert chart.collisions() == []

    def test_one_version_is_refused_where_two_people_sit_together(self, tmp_path):
        with pytest.raises(seating.SeatingError, match="table 1 seats 2"):
            seating.load(self.write(tmp_path, """
                versions = ["A"]
                [[group]]
                seats = ["A1", "A2"]
            """))

    def test_the_refusal_names_the_table_that_is_actually_crowded(self, tmp_path):
        """A lone seat comes first, so naming table 1 would send the operator
        to the wrong line of the file."""
        with pytest.raises(seating.SeatingError, match="table 2 seats 3"):
            seating.load(self.write(tmp_path, """
                versions = ["A"]
                [[group]]
                seats = ["A1"]
                [[group]]
                seats = ["B1", "B2", "B3"]
            """))

    def test_an_empty_version_list_is_refused_rather_than_defaulted(self, tmp_path):
        """Leaving the key out takes the default. Writing an empty list is a
        mistake, and quietly supplying A and B would hide it."""
        with pytest.raises(seating.SeatingError, match="versions is empty"):
            seating.load(self.write(tmp_path, """
                versions = []
                [[group]]
                seats = ["A1"]
            """))

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


# -------------------------------------------------------------- manifest ----

class TestManifest:
    """A run seed repeats the draw; the manifest repeats the result. The
    difference matters the moment an input changes."""

    def build(self, bank_dir, tmp_path, name="out", publication=None,
              roster=None, run_seed=99, dry_run=False):
        publication = publication or make_publication(bank_dir)
        roster = roster or two_students()
        chart = chart_for(tmp_path, ["Ada", "Bo"])
        out = str(tmp_path / name)
        source, _ = theme.load(bank_dir)
        report = assemble_mod.assemble(
            publication, roster, chart, out, source, rng=random.Random(1),
            dry_run=dry_run, run_seed=run_seed)
        return out, report

    def test_a_build_writes_one(self, bank_dir, tmp_path):
        out, _ = self.build(bank_dir, tmp_path)
        assert os.path.isfile(os.path.join(out, manifest_mod.FILENAME))

    def test_a_preview_writes_nothing_at_all(self, bank_dir, tmp_path):
        out, _ = self.build(bank_dir, tmp_path, dry_run=True)
        assert not os.path.exists(os.path.join(out, manifest_mod.FILENAME))

    def test_every_printed_paper_is_recorded(self, bank_dir, tmp_path):
        out, report = self.build(bank_dir, tmp_path)
        raw = manifest_mod.load(out)
        recorded = {(p["skill"], p["version"]): p["seed"] for p in raw["paper"]}
        expected = {(slug, v): s for (v, slug), s in report["seeds"].items()
                    if slug in report["skills"]}
        assert recorded == expected

    def test_the_run_seed_is_recorded(self, bank_dir, tmp_path):
        out, _ = self.build(bank_dir, tmp_path, run_seed=4242)
        assert manifest_mod.load(out)["run"]["seed"] == 4242

    def test_replaying_reproduces_the_papers_under_a_different_draw(
            self, bank_dir, tmp_path):
        """The whole point: replay pins, so the lottery is irrelevant."""
        first, report = self.build(bank_dir, tmp_path, name="a")
        raw = manifest_mod.load(first)
        replayed = manifest_mod.apply(raw, make_publication(bank_dir))
        source, _ = theme.load(bank_dir)
        again = assemble_mod.assemble(
            replayed, two_students(), chart_for(tmp_path, ["Ada", "Bo"]),
            str(tmp_path / "b"), source,
            rng=random.Random(12345),      # a different lottery entirely
            run_seed=12345)
        printed = {k: v for k, v in report["seeds"].items()
                   if k[1] in report["skills"]}
        assert {k: again["seeds"][k] for k in printed} == printed

    def test_a_changed_variant_is_refused(self, bank_dir, tmp_path):
        out, _ = self.build(bank_dir, tmp_path)
        raw = manifest_mod.load(out)
        raw["paper"][0]["variant"] = "a_case_this_bank_never_had"
        refusals, _ = manifest_mod.check(
            raw, Bank(bank_dir), make_publication(bank_dir))
        assert refusals and "different paper" in refusals[0]

    def test_an_unchanged_bank_refuses_nothing(self, bank_dir, tmp_path):
        out, _ = self.build(bank_dir, tmp_path)
        refusals, _ = manifest_mod.check(
            manifest_mod.load(out), Bank(bank_dir), make_publication(bank_dir))
        assert refusals == []

    def test_a_changed_input_is_a_note_not_a_refusal(self, bank_dir, tmp_path):
        """Fixing a misspelt name must not redraw the class."""
        roster_file = tmp_path / "roster.toml"
        roster_file.write_text('[[student]]\nname = "Ada"\nskills = ["AD"]\n',
                               encoding="utf-8")
        pub = make_publication(bank_dir, roster_path=str(roster_file))
        out, _ = self.build(bank_dir, tmp_path, publication=pub)

        roster_file.write_text('[[student]]\nname = "Ada L"\nskills = ["AD"]\n',
                               encoding="utf-8")
        refusals, notes = manifest_mod.check(
            manifest_mod.load(out), Bank(bank_dir), pub)
        assert refusals == []
        assert any("roster has changed" in n for n in notes)

    def test_a_folder_without_one_says_so(self, tmp_path):
        with pytest.raises(manifest_mod.ManifestError, match="does not exist"):
            manifest_mod.load(str(tmp_path))


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

    def test_mixing_the_two_pin_forms_is_refused(self, tmp_path, bank_dir):
        """One letter pinned for everything and another pinned for one skill
        is not a shorthand for anything; guessing which wins would be worse."""
        p = tmp_path / "publication.toml"
        p.write_text(f"""
[bank]
path = {bank_dir!r}
[seeds]
A = 451
[seeds.AD]
B = 452
""", encoding="utf-8")
        with pytest.raises(pub_mod.PublicationError, match="Pick one form"):
            pub_mod.load(str(p))

    def test_the_two_pin_forms_are_read_apart(self, tmp_path, bank_dir):
        p = tmp_path / "publication.toml"
        p.write_text(f"""
[bank]
path = {bank_dir!r}
[seeds.AD]
A = 451
""", encoding="utf-8")
        pub = pub_mod.load(str(p))
        assert pub.seeds == {}
        assert pub.skill_seeds == {"AD": {"A": 451}}

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
        pub = make_publication(bank_dir, skill_seeds={"AD": {"A": seed, "B": seed}})
        out, report = self.build(bank_dir, tmp_path, publication=pub)
        assert report["seeds"][("A", "AD")] == seed

    def test_a_pinned_seed_outside_the_printable_range_is_refused(self, bank_dir, tmp_path):
        pub = make_publication(bank_dir, skill_seeds={"AD": {"A": 3}})
        with pytest.raises(assemble_mod.AssemblyError, match="pinned"):
            self.build(bank_dir, tmp_path, publication=pub)

    def test_pinning_one_skill_leaves_the_others_drawn(self, bank_dir, tmp_path):
        """The point of the per-skill form: name one paper, draw the rest."""
        bank = Bank(bank_dir)
        seed = bank.printable_seeds("AD")[0]
        pub = make_publication(bank_dir, skill_seeds={"AD": {"A": seed}})
        out, report = self.build(bank_dir, tmp_path, publication=pub)
        assert report["seeds"][("A", "AD")] == seed
        # SU was never pinned, so it drew from its own pool rather than
        # inheriting AD's number the way the flat form would have handed it.
        assert report["seeds"][("A", "SU")] in bank.printable_seeds("SU")

    def test_a_flat_pin_across_several_skills_is_refused(self, bank_dir, tmp_path):
        """A letter with no skill means every skill, which across more than one
        is silently three wrong papers and one right one."""
        seed = Bank(bank_dir).printable_seeds("AD")[0]
        pub = make_publication(bank_dir, seeds={"A": seed})
        with pytest.raises(assemble_mod.AssemblyError,
                           match="pins a letter across every skill"):
            self.build(bank_dir, tmp_path, publication=pub)

    def test_a_flat_pin_is_allowed_when_one_skill_is_printed(self, bank_dir, tmp_path):
        """With nothing to confuse it with, the short form still reads fine."""
        seed = Bank(bank_dir).printable_seeds("AD")[0]
        one = roster_mod.Roster(
            [roster_mod.Student(name="Ada", section="1", skills=["AD"])])
        pub = make_publication(bank_dir, seeds={"A": seed})
        out, report = self.build(bank_dir, tmp_path, publication=pub, roster=one,
                                 chart=chart_for(tmp_path, ["Ada"]))
        assert report["seeds"][("A", "AD")] == seed

    def test_the_same_run_seed_draws_the_same_papers(self, bank_dir, tmp_path):
        """What makes --seed worth reporting: the draw is a function of it."""
        source, _ = theme.load(bank_dir)
        def draw(n):
            return assemble_mod.assemble(
                make_publication(bank_dir), two_students(),
                chart_for(tmp_path, ["Ada", "Bo"]), str(tmp_path / f"out{n}"),
                source, rng=random.Random(n))["seeds"]
        assert draw(7) == draw(7)
        assert draw(7) != draw(8), "two seeds produced the same draw"

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
        assert os.path.isfile(os.path.join(out, "printit.sty"))


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
        r"""The Unicode is for the screen. `@latex` is the print form, and the
        stylesheet has always known to prefer it.

        Grouped, because a @latex value usually opens with a size switch and a
        switch is a declaration: unbraced, \Large ran to the end of the
        document and made every page after the first Egyptian numeral huge.
        """
        out = spatext.to_latex(
            '<glyphs font="egyptian" latex="\\Large\\Hone\\Hten">\U000133fa</glyphs>')
        assert out == r"{\Large\Hone\Hten}"
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

    def test_entities_resolve_even_with_no_markup(self):
        r"""A field bound for a {{{triple brace}}} slot arrives already escaped,
        or template.xml would not parse. N2's alignment ampersands are `&amp;`
        in the data: the web gets them back when the XML is parsed, but print
        parses nothing, so \begin{align*} received `&amp;=` and typeset a column
        break followed by the word `amp;`."""
        assert spatext.to_latex(r"467 \div 2 &amp;= 233") == r"467 \div 2 &= 233"
        assert spatext.to_latex("a &lt; b") == "a < b"

    def test_a_raw_ampersand_is_not_touched(self):
        """Unescaping has to be safe for a field that was never escaped: a bare
        & matches no entity, so it survives."""
        assert spatext.to_latex(r"x &= y \\ z &= w") == r"x &= y \\ z &= w"

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


# ---------------------------------------------------------------- colour ----

class TestColourMap:
    """`bank.xml` may colour each family of skills, and print ignored it.

    Every printed box came out in the theme's default blue, which is not what a
    bank declaring a colour map is asking for -- and it left no way to make one
    outcome stand apart from the rest.
    """

    def bank_with_map(self, bank_dir, tmp_path, entries):
        root = str(tmp_path / "bank")
        shutil.copytree(bank_dir, root)
        path = os.path.join(root, "bank.xml")
        with open(path, encoding="utf-8") as f:
            xml = f.read()
        rows = "".join(f'<category prefix="{p}" color="{c}" />'
                       for p, c in entries)
        xml = xml.replace("<outcomes>", f"<color_map>{rows}</color_map><outcomes>")
        with open(path, "w", encoding="utf-8") as f:
            f.write(xml)
        return root

    def test_a_prefix_colours_its_family(self, bank_dir, tmp_path):
        root = self.bank_with_map(bank_dir, tmp_path, [("A", "Violet")])
        assert Bank(root).color("AD") == "Violet"

    def test_no_map_means_no_colour(self, bank_dir, tmp_path):
        """An uncoloured bank keeps the theme's default rather than being given
        one, so nothing changes for a bank that never asked."""
        assert Bank(bank_dir).color("AD") is None

    def test_the_longest_prefix_wins(self, bank_dir, tmp_path):
        """How one outcome claims a colour of its own: FCP would otherwise take
        the fractions' colour, since F is the only other match."""
        root = self.bank_with_map(bank_dir, tmp_path,
                                  [("A", "teal"), ("AD", "Sepia")])
        assert Bank(root).color("AD") == "Sepia"
        assert Bank(root).color("AX") == "teal"

    def test_the_colour_reaches_the_descriptions_file(self, bank_dir, tmp_path):
        """Where it actually has to arrive: \\setskilldesc's optional argument."""
        root = self.bank_with_map(bank_dir, tmp_path, [("A", "Violet")])
        bank = Bank(root)
        written = assemble_mod.descriptions_tex(bank, ["AD", "SU"])
        assert r"\setskilldesc[Violet]{AD}" in written
        assert r"\setskilldesc{SU}" in written, "an unmapped slug gets no colour"


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


# ------------------------------------------------------------- the theme ----

class TestThemeInstall:
    """The theme belongs to this tool, and lives in the bank.

    It decides two things at once: how printed handouts look, and what the
    viewer's Assessment tab exports -- CheckIt publishes the installed file so
    a browser can read it. Before it was installed anywhere, a bank on the
    bundled default got themed handouts and a plain-looking web export, and
    nothing said why.
    """

    def test_install_writes_the_default_into_the_bank(self, bank_dir, tmp_path):
        root = str(tmp_path / "bank")
        shutil.copytree(bank_dir, root)

        path, action, _ = theme.install(root)

        assert action == "installed"
        assert path == os.path.join(root, "printit", "printit.sty")
        with open(path, encoding="utf-8") as f:
            assert r"\ProvidesPackage{printit}" in f.read()

    def test_install_keeps_an_existing_theme(self, bank_dir, tmp_path):
        """That file is the author's, and may be a term of layout work."""
        root = str(tmp_path / "bank")
        shutil.copytree(bank_dir, root)
        theme.install(root)
        mine = os.path.join(root, "printit", "printit.sty")
        with open(mine, "w", encoding="utf-8") as f:
            f.write("% mine\n")

        path, action, _ = theme.install(root)

        assert action == "kept"
        with open(path, encoding="utf-8") as f:
            assert f.read() == "% mine\n"

    def test_force_replaces_it(self, bank_dir, tmp_path):
        root = str(tmp_path / "bank")
        shutil.copytree(bank_dir, root)
        theme.install(root)
        mine = os.path.join(root, "printit", "printit.sty")
        with open(mine, "w", encoding="utf-8") as f:
            f.write("% mine\n")

        path, action, _ = theme.install(root, force=True)

        assert action == "replaced"
        with open(path, encoding="utf-8") as f:
            assert r"\ProvidesPackage{printit}" in f.read()

    def test_a_bank_on_the_old_layout_stops_with_instructions(self, bank_dir, tmp_path):
        """Installing beside the old file would leave the bank with two themes,
        print using the new one and hand-written .tex still loading the old."""
        root = str(tmp_path / "bank")
        shutil.copytree(bank_dir, root)
        legacy = os.path.join(root, "skillcheckpoints.sty")
        with open(legacy, "w", encoding="utf-8") as f:
            f.write(r"\ProvidesPackage{skillcheckpoints}" + "\n")

        with pytest.raises(theme.ThemeError) as caught:
            theme.install(root)

        assert "git mv" in str(caught.value)
        assert not os.path.exists(os.path.join(root, "printit", "printit.sty"))

    def test_loading_an_old_layout_refuses_rather_than_using_the_default(
            self, bank_dir, tmp_path):
        """Silently falling back would print a whole class set in a theme the
        author had already replaced."""
        root = str(tmp_path / "bank")
        shutil.copytree(bank_dir, root)
        with open(os.path.join(root, "skillcheckpoints.sty"), "w",
                  encoding="utf-8") as f:
            f.write("% old\n")

        with pytest.raises(theme.ThemeError):
            theme.load(root)

    def test_a_bank_without_one_gets_the_bundled_default(self, bank_dir):
        """Not a fault: printing works before anything is installed."""
        source, origin = theme.load(bank_dir)

        assert r"\ProvidesPackage{printit}" in source
        assert origin == theme.default_path()

    def test_an_installed_theme_is_the_one_used(self, bank_dir, tmp_path):
        root = str(tmp_path / "bank")
        shutil.copytree(bank_dir, root)
        theme.install(root)
        path = os.path.join(root, "printit", "printit.sty")
        with open(path, "w", encoding="utf-8") as f:
            f.write("% edited by the author\n")

        source, origin = theme.load(root)

        assert source == "% edited by the author\n"
        assert origin == path

    def test_install_declares_the_theme_in_the_manifest(self, bank_dir, tmp_path):
        """CheckIt publishes what a bank declares, and knows nothing about this
        tool -- so writing the declaration is this tool's job."""
        root = str(tmp_path / "bank")
        shutil.copytree(bank_dir, root)

        theme.install(root)

        with open(os.path.join(root, "bank.xml"), encoding="utf-8") as f:
            xml = f.read()
        assert "<latex-support>" in xml
        assert 'path="printit/printit.sty"' in xml
        assert 'role="theme"' in xml

    def test_declaring_twice_does_nothing(self, bank_dir, tmp_path):
        root = str(tmp_path / "bank")
        shutil.copytree(bank_dir, root)
        theme.install(root)
        manifest = os.path.join(root, "bank.xml")
        with open(manifest, encoding="utf-8") as f:
            once = f.read()

        assert theme.declare(root) is False

        with open(manifest, encoding="utf-8") as f:
            assert f.read() == once

    def test_a_hand_copied_theme_still_gets_declared(self, bank_dir, tmp_path):
        """`install` on a bank whose theme was copied in by hand adds the
        declaration, rather than reporting "kept" and publishing nothing."""
        root = str(tmp_path / "bank")
        shutil.copytree(bank_dir, root)
        os.makedirs(os.path.join(root, "printit"))
        with open(os.path.join(root, "printit", "printit.sty"), "w",
                  encoding="utf-8") as f:
            f.write("% copied in by hand\n")

        _, action, _ = theme.install(root)

        assert action == "kept"
        with open(os.path.join(root, "bank.xml"), encoding="utf-8") as f:
            assert 'path="printit/printit.sty"' in f.read()

    def test_the_manifest_keeps_its_comments(self, bank_dir, tmp_path):
        """bank.xml is hand-maintained. Re-serialising the XML would move or
        drop its comments, so the declaration is inserted as text."""
        root = str(tmp_path / "bank")
        shutil.copytree(bank_dir, root)
        manifest = os.path.join(root, "bank.xml")
        with open(manifest, encoding="utf-8") as f:
            before = f.read()

        theme.install(root)

        with open(manifest, encoding="utf-8") as f:
            after = f.read()
        # Unchanged apart from one insertion: cutting the added block back out
        # gives the original byte for byte. That catches a reformat, a dropped
        # comment and a moved element all at once.
        head, opened, tail = after.partition("    <latex-support>\n")
        block, closed, rest = tail.partition("    </latex-support>\n")
        assert opened and closed, "no <latex-support> block was added"
        assert 'path="printit/printit.sty"' in block
        assert head + rest == before

    def test_a_path_named_in_a_comment_is_not_a_declaration(self, bank_dir, tmp_path):
        """The bug this replaced: idempotence was a substring search, so the
        path written in a comment elsewhere in bank.xml counted as a
        declaration. The theme was then never published, and nothing said so.
        """
        root = str(tmp_path / "bank")
        shutil.copytree(bank_dir, root)
        manifest = os.path.join(root, "bank.xml")
        with open(manifest, encoding="utf-8") as f:
            xml = f.read()
        with open(manifest, "w", encoding="utf-8") as f:
            f.write(xml.replace(
                "<outcomes>",
                "<!-- see printit/printit.sty for the layout -->\n    <outcomes>",
                1))

        theme.install(root)

        with open(manifest, encoding="utf-8") as f:
            assert 'path="printit/printit.sty"' in f.read()


# ------------------------------------------------------- distinct versions ----

class TestVersionsAreDistinct:
    """Two version letters must never be the same paper.

    Seeds were drawn independently per letter, so they could collide. With ten
    versions out of six hundred printable seeds that is about one run in
    fourteen -- and the build still reported the full count of versions while
    two neighbours held identical sheets.
    """

    def publication(self, bank_dir, **kwargs):
        return pub_mod.Publication(
            bank_path=bank_dir, roster_path=None, seating_path=None,
            simply_print=("AD",), **kwargs)

    def test_every_version_gets_a_different_seed(self, bank_dir):
        versions = [chr(ord("A") + i) for i in range(10)]
        bank = Bank(bank_dir)
        # Many draws, because a collision is occasional rather than reliable.
        for attempt in range(60):
            chosen = assemble_mod.choose_seeds(
                bank, versions, self.publication(bank_dir),
                random.Random(attempt))
            seeds = [chosen[(v, "AD")] for v in versions]
            assert len(set(seeds)) == len(seeds), (
                f"attempt {attempt} repeated a seed: {seeds}")

    def test_a_pinned_seed_is_not_drawn_again(self, bank_dir):
        bank = Bank(bank_dir)
        printable = bank.printable_seeds("AD")
        pinned = printable[0]
        versions = ["A", "B", "C"]
        for attempt in range(40):
            chosen = assemble_mod.choose_seeds(
                bank, versions, self.publication(bank_dir, seeds={"A": pinned}),
                random.Random(attempt))
            assert chosen[("A", "AD")] == pinned
            others = [chosen[(v, "AD")] for v in ("B", "C")]
            assert pinned not in others, "an unpinned letter reproduced the pin"
            assert others[0] != others[1]

    def test_asking_for_more_versions_than_exist_is_refused(self, bank_dir):
        """Silently repeating would be worse: the report would claim versions
        that are not different."""
        bank = Bank(bank_dir)
        too_many = [f"V{i}" for i in range(len(bank.printable_seeds("AD")) + 1)]
        with pytest.raises(assemble_mod.AssemblyError, match="distinct"):
            assemble_mod.choose_seeds(
                bank, too_many, self.publication(bank_dir), random.Random(0))
