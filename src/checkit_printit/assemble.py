"""Turn a bank, a roster and a seating chart into a folder that compiles.

The output is the point. It must build with `pdflatex main.tex` and nothing
else -- no tool, no bank, no network -- so it can be archived, audited, and
fixed by hand the night before a quiz.
"""

import dataclasses
import os
import random
import re
import shutil

from . import manifest
from . import spatext
from . import theme as theme_mod
from .bank import Bank
from .jinja import make_env

# Re-exported from theme.py, so a caller writing the file into a
# build folder does not need a second import to learn its name.
THEME_FILENAME = theme_mod.THEME_FILENAME
DESCRIPTIONS_FILENAME = "Skill Descriptions.tex"


class AssemblyError(Exception):
    pass


@dataclasses.dataclass
class Handout:
    """One student's packet: who, and which version of which skills."""
    name: str
    section: str
    versions: list          # (slug, seed) in the order they print
    blank_name: bool = False


def choose_seeds(bank, versions, publication, rng):
    """One seed per (version, skill).

    A version letter means "everyone holding this letter gets the same paper",
    so the seed is chosen per letter and reused across every student holding it.
    That is what makes two neighbours differ and two rows apart match.

    `[seeds.<skill>]` pins a letter for one skill, which is how a single paper
    is forced onto a chosen version. Reproducing a whole run is a different
    job: that belongs to the run seed, not to a table of pins one per skill.

    Within one skill the letters draw *without replacement*, so two versions
    are never the same paper. Drawing each independently looked fine and was
    not: with ten versions out of six hundred printable seeds, about one run in
    fourteen handed two letters the same exercise -- and a report of "10
    versions" while two neighbours hold identical sheets is the one failure
    versioning exists to prevent.
    """
    chosen = {}
    for slug in publication_skills(publication, bank):
        wanted = publication.variants.get(slug)
        available = bank.seeds_with_variant(slug, wanted)
        # A per-skill table wins; the flat form is the single-skill shorthand.
        pins = publication.skill_seeds.get(slug) or publication.seeds

        pinned = {}
        for version in versions:
            seed = pins.get(version)
            if seed is None:
                continue
            if seed not in available:
                raise AssemblyError(
                    f"version {version} is pinned to seed {seed}, but {slug} "
                    f"has no printable version at that seed"
                    + (f" with variant {wanted!r}" if wanted else "")
                    + f". Printable seeds start at {available[0]}."
                )
            pinned[version] = seed

        free = [v for v in versions if v not in pinned]
        # A pinned seed is out of the pool, so an unpinned letter cannot
        # accidentally reproduce it.
        pool = [s for s in available if s not in set(pinned.values())]
        if len(pool) < len(free):
            raise AssemblyError(
                f"{slug} has {len(pool)} printable version(s) left to draw from"
                + (f" with variant {wanted!r}" if wanted else "")
                + f", but {len(free)} version letter(s) need a distinct one. "
                "Generate more seeds, or ask for fewer versions in seating.toml."
            )
        drawn = rng.sample(pool, len(free))

        for version in versions:
            chosen[(version, slug)] = (
                pinned[version] if version in pinned else drawn[free.index(version)]
            )
    return chosen


def publication_skills(publication, bank):
    """Every skill this run could need, so seeds are chosen once."""
    return bank.slugs()


def build_handouts(roster, chart, publication, seeds):
    """Students in seating order, each with their versions resolved."""
    ordered, unseated = chart.order(roster) if chart else (list(roster), [])
    handouts = []
    for student in ordered + unseated:
        version = student.version or (chart.versions[0] if chart else "A")
        versions = []
        for slug in student.skills:
            seed = seeds.get((version, slug))
            if seed is None:
                raise AssemblyError(
                    f"{student.name} asked for {slug!r}, which is not in the bank."
                )
            versions.append((slug, seed))
        handouts.append(Handout(
            name=student.name,
            section=student.section,
            versions=versions,
            blank_name=not publication.names,
        ))
    return handouts, unseated


def build_extras(publication, seeds, versions, rng):
    """Spare copies, appended at the end with a blank name line.

    Versions are shuffled among those available rather than cycled, so three
    extras of one skill are three different papers where possible.
    """
    extras = []
    for extra in publication.extras:
        pool = list(versions)
        rng.shuffle(pool)
        for i in range(extra.copies):
            version = pool[i % len(pool)]
            seed = seeds.get((version, extra.skill))
            if seed is None:
                raise AssemblyError(
                    f"extras ask for {extra.skill!r}, which is not in the bank."
                )
            extras.append(Handout(
                name="", section="", versions=[(extra.skill, seed)], blank_name=True,
            ))
    return extras


#: `Exercise.latex()` prefixes a block defining \stxKnowl and friends, and
#: ending with a rule of percent signs. We define those ourselves in main.tex,
#: pointed at the theme's answer machinery, so the per-file copy is dropped.
_SPATEXT_PREAMBLE_END = "%" * 28


def render_skill(bank, slug, seed, env):
    r"""One skill, one version, as a LaTeX file body.

    Two routes, and the first wins:

    1. `textemplate.tex` -- a LaTeX template using `\VAR{key}`. The escape
       hatch for layout no vocabulary would capture: true/false rows, blanks in
       a second column, figures with answers marked on them.
    2. Its SpaTeXt, rendered through `latex.xsl`. No second template to write,
       and the intended default for a new outcome.

    Either way the result is a skill file in the theme's own vocabulary --
    `\setvseed`, `\skillheader` -- so a generated file and a hand-written one
    are the same kind of thing.
    """
    template = bank.print_template(slug)
    if template is not None:
        # Fields carrying inline SpaTeXt go through latex.xsl first. Without
        # this a template pastes `<m>91</m>` into the document as those nine
        # characters, which is how a hieroglyph once reached pdflatex.
        data = spatext.render_fields(bank.data(slug, seed), slug)
        data["seed"] = seed
        return env.from_string(template).render(data)
    return render_from_spatext(bank, slug, seed)


def render_from_spatext(bank, slug, seed):
    """A skill file built from the outcome's SpaTeXt.

    Rendered here rather than read from `derived.json`, because that stops at
    BUNDLE_UNTIL and printable seeds start there. Rendering also means a
    stylesheet fix reaches print without regenerating the bank.
    """
    latex = bank.exercise(slug, seed).latex()
    if _SPATEXT_PREAMBLE_END in latex:
        latex = latex.split(_SPATEXT_PREAMBLE_END, 1)[1]
    return (
        f"\\setvseed{{{seed}}}\n"
        f"\\skillheader{{{slug}}}\n\n"
        + latex.strip() + "\n"
    )


def descriptions_tex(bank, slugs):
    """`Skill Descriptions.tex`, kept in step with bank.xml.

    The theme's `\\skillheader` looks a slug up in this dictionary. Generating it
    from the manifest is what keeps a printed header honest; a hand-authored
    bank writes the same file itself.
    """
    lines = ["% Generated from bank.xml. Do not edit -- edit the bank.", ""]
    for slug in slugs:
        desc = bank.description(slug).replace("\n", " ")
        # The optional argument is the box colour, from the bank's <color_map>.
        # Omitting it left every printed skill in the theme's default blue,
        # which is not what a bank declaring a colour map is asking for.
        color = bank.color(slug)
        prefix = f"\\setskilldesc[{color}]" if color else "\\setskilldesc"
        lines.append(f"{prefix}{{{slug}}}{{{desc}}}")
    return "\n".join(lines) + "\n"


def main_tex(publication, handouts, extras, keys, load_helpers=False):
    """The document that pulls the skill files together."""
    out = [
        r"\documentclass[12pt,twoside]{article}",
        r"\usepackage[utf8]{inputenc}",
        r"\usepackage{printit}",
        # The bank's own macros, after the theme so they may build on it.
        *([r"\usepackage{bank_helpers}"] if load_helpers else []),
        "",
        "% Skills rendered from SpaTeXt arrive wrapped in these.",
        "%",
        "% stxOuttro uses \\color inside a group rather than the theme's",
        "% \\ans, which wraps its argument in \\textcolor -- and \\textcolor is not",
        "% long, so an answer ending in a blank line ends the paragraph before",
        "% the command completes. Rendered outtros routinely do.",
        "%",
        "% \\providecommand throughout, so a theme defining these wins.",
        r"\providecommand{\stxKnowl}[1]{#1}",
        r"\providecommand{\stxTitle}[1]{#1}",
        r"\providecommand{\stxOuttro}[1]{\ifanstoggle{\color{scCOLOR}#1}\fi}",
        "",
        f"\\acadclass{{{publication.course}}}",
        f"\\date{{{publication.semester}}}",
        f"\\author{{{publication.professor}}}",
        f"\\title{{{publication.full_title}}}",
        "",
        r"\begin{document}",
        "",
        "% ---- student copies",
    ]

    def emit(handout):
        name = "Blank" if handout.blank_name or not handout.name else handout.name
        out.append(f"\\setname{{{name}}}")
        out.append(f"\\setsect{{{handout.section or 'Blank'}}}")
        for slug, seed in handout.versions:
            out.append(f"\\skillpage{{{slug}/{slug} v{seed}}}")
        out.append(r"\preparefornextstudent")
        out.append("")

    for handout in handouts:
        emit(handout)

    if extras:
        out.append("% ---- extras")
        for handout in extras:
            emit(handout)

    if keys:
        out.append("% ---- answer keys")
        out.append(r"\setboolean{anstoggle}{true}")
        out.append(r"\setname{Key}")
        out.append(r"\setsect{Blank}")
        for _ in range(keys["copies"]):
            for slug, seed in keys["versions"]:
                out.append(f"\\skillpage{{{slug}/{slug} v{seed}}}")
            out.append(r"\preparefornextstudent")
        out.append("")

    out.append(r"\end{document}")
    return "\n".join(out) + "\n"


def key_versions(handouts, extras, bank):
    """Every distinct version actually handed out, in bank order.

    Deduplicated, because printing one key per student would be a stack of
    duplicates; ordered by the bank so a key can be checked against a handout
    without hunting.
    """
    used = {v for h in list(handouts) + list(extras) for v in h.versions}
    order = {slug: i for i, slug in enumerate(bank.slugs())}
    return sorted(used, key=lambda v: (order.get(v[0], 10**6), v[1]))


def check_flat_pins(publication, roster):
    """`[seeds]` names a letter but no skill, so it means every skill at once.

    Across more than one that is silently wrong: pinning A = 755 to reproduce
    one paper gives every other skill seed 755 as well, and the seeds are all
    printable, so nothing complains. Refuse it where it cannot mean what it
    says, and point at the per-skill form.
    """
    if not publication.seeds:
        return
    printed = {slug for student in roster for slug in student.skills}
    printed |= {extra.skill for extra in publication.extras}
    if len(printed) > 1:
        letter, seed = next(iter(publication.seeds.items()))
        names = ", ".join(sorted(printed))
        raise AssemblyError(
            f"[seeds] pins a letter across every skill, so {letter} = {seed} "
            f"asks all {len(printed)} of {names} for seed {seed}. Write one "
            f"table per skill instead: [seeds.{sorted(printed)[0]}]"
        )


def check_dropped_are_unseated(roster, chart):
    """A dropped student must not still hold a seat.

    Printing works off the seating chart, so there is deliberately no filter
    at print time -- dropping a student empties their seat, and what you see
    in the chart is what comes out of the printer. That only holds if the two
    files agree, and hand-editing `dropped = true` without touching the chart
    would quietly put a paper in a departed student's hands. So it is checked
    rather than filtered: a filter would hide the divergence, a check names it.
    """
    if chart is None:
        return
    seated = {seat.name for seat in chart}
    still = sorted(s.name for s in roster if s.dropped and s.name in seated)
    if still:
        raise AssemblyError(
            f"{len(still)} student(s) marked dropped are still in the seating "
            f"chart: {', '.join(still)}. Dropping is meant to empty the seat "
            f"as well -- run `checkit-printit roster drop <name>`, or restore "
            f"them."
        )


def assemble(publication, roster, chart, out_dir, theme, rng=None,
             dry_run=False, run_seed=None):
    """Write a complete, compilable folder. Returns a short report."""
    rng = rng or random.Random()
    bank = Bank(publication.bank_path)
    check_flat_pins(publication, roster)
    check_dropped_are_unseated(roster, chart)
    missing = {}
    env_misses = set()
    env = make_env(missing=env_misses)

    versions = list(chart.versions) if chart else ["A"]
    seeds = choose_seeds(bank, versions, publication, rng)

    handouts, unseated = build_handouts(roster, chart, publication, seeds)
    extras = build_extras(publication, seeds, versions, rng)

    keys = None
    if publication.keys:
        keys = {"copies": publication.key_copies,
                "versions": key_versions(handouts, extras, bank)}

    written = set()
    if dry_run:
        # Everything the report needs is already decided; writing is all that
        # is left. Return before touching the filesystem -- a preview that
        # leaves a folder behind is a preview that lied.
        for handout in list(handouts) + list(extras):
            written.update(handout.versions)
        return _report_dict(handouts, extras, keys, written, unseated, chart,
                            seeds, {})

    # -- write ------------------------------------------------------------
    os.makedirs(out_dir, exist_ok=True)
    # Skill files sit beside main.tex, one folder per slug, because the theme's
    # \skillpage does a plain \input relative to the main document. Putting
    # them under skills/ would need TEXINPUTS set, and the folder is supposed to
    # build with `pdflatex main.tex` and nothing else.
    skills_dir = out_dir

    for handout in list(handouts) + list(extras):
        for slug, seed in handout.versions:
            if (slug, seed) in written:
                continue
            before = set(env_misses)
            body = render_skill(bank, slug, seed, env)
            new = env_misses - before
            if new:
                missing.setdefault(slug, set()).update(new)
            d = os.path.join(skills_dir, slug)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, f"{slug} v{seed}.tex"), "w", encoding="utf-8") as f:
                f.write(body)
            written.add((slug, seed))

    with open(os.path.join(out_dir, THEME_FILENAME), "w", encoding="utf-8") as f:
        f.write(theme)

    # printit.sty requires this, so the folder does not compile without it.
    # Resolved here rather than passed in: it is a dependency of the theme, not
    # a second choice the caller makes.
    figures, _origin = theme_mod.figures_source(bank.path)
    with open(os.path.join(out_dir, theme_mod.FIGURES_FILENAME), "w",
              encoding="utf-8") as f:
        f.write(figures)

    helper = bank.helper_sty()
    if helper:
        with open(os.path.join(out_dir, "bank_helpers.sty"), "w", encoding="utf-8") as f:
            f.write(helper)

    slugs_used = sorted({slug for slug, _ in written})
    with open(os.path.join(out_dir, DESCRIPTIONS_FILENAME), "w", encoding="utf-8") as f:
        f.write(descriptions_tex(bank, slugs_used))

    with open(os.path.join(out_dir, "main.tex"), "w", encoding="utf-8") as f:
        f.write(main_tex(publication, handouts, extras, keys,
                         load_helpers=helper is not None))

    _copy_assets(bank, out_dir, written)

    # Written last, so a folder only claims to be reproducible once it is
    # complete. A run with no seed recorded cannot be replayed, so the caller
    # has to supply one rather than have a default invented here.
    if run_seed is not None:
        manifest.write(out_dir, publication, run_seed, seeds, bank, slugs_used)

    return _report_dict(handouts, extras, keys, written, unseated, chart,
                        seeds, missing)


def _report_dict(handouts, extras, keys, written, unseated, chart, seeds, missing):
    return {
        "students": len(handouts),
        "extras": len(extras),
        "skills": sorted({slug for slug, _ in written}),
        "versions": len(written),
        "keys": len(keys["versions"]) * keys["copies"] if keys else 0,
        "unseated": [s.name for s in unseated],
        "collisions": chart.collisions() if chart else [],
        "seeds": seeds,
        "missing_fields": {k: sorted(v) for k, v in sorted(missing.items())},
    }


#: How latex.xsl emits a figure: `\includegraphics{path}` for a bitmap,
#: `\input{path.tikz}` for a TikZ picture. Both take the path verbatim from the
#: template's `source` attribute, which is relative to the bank root.
_FIGURE_RE = re.compile(
    r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}"
    r"|\\input\s*\{([^}]+\.tikz)\}"
)

#: `\includegraphics{x}` compiles when `x.png` exists, so a template may leave
#: the extension off. Try what LaTeX would try before calling a figure missing.
_FIGURE_EXTENSIONS = ("", ".png", ".pdf", ".jpg", ".jpeg")


def _copy_assets(bank, out_dir, written):
    """Copy every figure the written skill files actually reference.

    Scanning the files beats copying `assets/` wholesale twice over. The output
    folder stays small: mat-106's R1 holds 38 hand-drawn PNGs and one quiz needs
    two of them. And a reference the bank cannot satisfy is caught here, by
    name, rather than as a pdflatex log that says `using draft setting` and then
    fails a thousand lines further down.

    Copied rather than linked, because the folder has to survive the bank moving
    or the tool being uninstalled.
    """
    missing = {}
    for slug, seed in sorted(written):
        path = os.path.join(out_dir, slug, f"{slug} v{seed}.tex")
        with open(path, encoding="utf-8") as f:
            body = f.read()
        for match in _FIGURE_RE.finditer(body):
            ref = (match.group(1) or match.group(2)).strip()
            found = _resolve_figure(bank.path, ref)
            if found is None:
                missing.setdefault(ref, []).append(f"{slug} v{seed}")
                continue
            src, rel = found
            dst = os.path.join(out_dir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)

    if missing:
        raise AssemblyError(
            "These figures are referenced but not in the bank:\n"
            + "\n".join(f"  {ref}  (used by {', '.join(where)})"
                        for ref, where in sorted(missing.items()))
            + f"\n\nLooked under {bank.path}. Fix the source path in the "
              "outcome's template, or generate the images, then build again."
        )


def _resolve_figure(bank_root, ref):
    """(file to copy, path relative to the bank root), or None if absent.

    A path leading outside the bank counts as absent: copying it would land the
    figure outside the output folder, and the folder has to stand alone.
    """
    if os.path.isabs(ref) or ref.startswith(".."):
        return None
    for ext in _FIGURE_EXTENSIONS:
        candidate = os.path.join(bank_root, ref + ext)
        if os.path.isfile(candidate):
            return candidate, ref + ext
    return None
