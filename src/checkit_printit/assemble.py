"""Turn a bank, a roster and a seating chart into a folder that compiles.

The output is the point. It must build with `pdflatex main.tex` and nothing
else -- no tool, no bank, no network -- so it can be archived, audited, and
fixed by hand the night before a quiz.
"""

import dataclasses
import os
import random
import shutil

from .bank import Bank
from .jinja import make_env

THEME_FILENAME = "skillcheckpoints.sty"
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

    `[seeds]` in the publication pins a letter outright, which is how a reprint
    reproduces what was handed out.
    """
    chosen = {}
    for version in versions:
        pinned = publication.seeds.get(version)
        for slug in publication_skills(publication, bank):
            wanted = publication.variants.get(slug)
            available = bank.seeds_with_variant(slug, wanted)
            if pinned is not None:
                if pinned not in available:
                    raise AssemblyError(
                        f"version {version} is pinned to seed {pinned}, but {slug} "
                        f"has no printable version at that seed"
                        + (f" with variant {wanted!r}" if wanted else "")
                        + f". Printable seeds start at {available[0]}."
                    )
                chosen[(version, slug)] = pinned
            else:
                chosen[(version, slug)] = rng.choice(available)
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
        data = dict(bank.data(slug, seed))
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
        lines.append(f"\\setskilldesc{{{slug}}}{{{desc}}}")
    return "\n".join(lines) + "\n"


def main_tex(publication, handouts, extras, keys, load_helpers=False):
    """The document that pulls the skill files together."""
    out = [
        r"\documentclass[12pt,twoside]{article}",
        r"\usepackage[utf8]{inputenc}",
        r"\usepackage{skillcheckpoints}",
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


def assemble(publication, roster, chart, out_dir, theme, rng=None, dry_run=False):
    """Write a complete, compilable folder. Returns a short report."""
    rng = rng or random.Random()
    bank = Bank(publication.bank_path)
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

    _copy_assets(bank, out_dir, slugs_used)

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


def _copy_assets(bank, out_dir, slugs):
    """Figures the skills reference.

    Copied rather than linked, because the folder has to survive the bank
    moving or the tool being uninstalled.
    """
    src_root = bank.asset_dir()
    for slug in slugs:
        src = os.path.join(src_root, slug, "generated")
        if not os.path.isdir(src):
            continue
        dst = os.path.join(out_dir, "assets", slug, "generated")
        shutil.copytree(
            src, dst, dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("seeds.json", "derived.json"),
        )
