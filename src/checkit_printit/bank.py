"""Reading a CheckIt bank: its outcomes, its pregenerated versions, its macros.

Printing never runs a generator. It reads `seeds.json`, which `checkit generate`
wrote, so a printed version is reproducible from its seed and needs no working
generator environment.
"""

import json
import os

from checkit import PUBLIC_SEEDS, BUNDLE_UNTIL
from checkit.bank import Bank as CheckItBank

#: Seeds at or above this are safe to print.
#:
#: 0 to PUBLIC_SEEDS-1 are what students browse. PUBLIC_SEEDS to BUNDLE_UNTIL-1
#: are published in `derived.json` **with their answers** -- a printed quiz drawn
#: from that range is a printed quiz whose answers are a fetch away. From
#: BUNDLE_UNTIL up, `checkit viewer` publishes nothing: `build_viewer` copies
#: `assets/` while ignoring `seeds.json`, so those versions exist in the bank and
#: nowhere else.
FIRST_PRINTABLE_SEED = BUNDLE_UNTIL


class BankError(Exception):
    pass


class Bank:
    """A CheckIt bank, as the print tool needs it."""

    def __init__(self, path):
        self.path = os.path.abspath(path)
        if not os.path.isfile(os.path.join(self.path, "bank.xml")):
            raise BankError(f"no bank.xml in {self.path!r}; is that a CheckIt bank?")
        self._checkit = CheckItBank(self.path)
        self._seeds = {}

    @property
    def title(self):
        return self._checkit.title

    def outcomes(self):
        return self._checkit.outcomes()

    def slugs(self):
        return [o.slug for o in self.outcomes()]

    def outcome(self, slug):
        for o in self.outcomes():
            if o.slug == slug:
                return o
        raise BankError(
            f"no outcome {slug!r} in this bank. Available: {', '.join(self.slugs())}"
        )

    def description(self, slug):
        return (self.outcome(slug).description or "").strip()

    # -- versions ---------------------------------------------------------

    def _load_seeds(self, slug):
        if slug not in self._seeds:
            path = os.path.join(self.path, "assets", slug, "generated", "seeds.json")
            if not os.path.isfile(path):
                raise BankError(
                    f"{slug} has no generated versions. Run `checkit generate` "
                    f"in {self.path!r} first."
                )
            with open(path, encoding="utf-8") as f:
                self._seeds[slug] = {e["seed"]: e["data"] for e in json.load(f)["seeds"]}
        return self._seeds[slug]

    def data(self, slug, seed):
        """One version's data, as the generator produced it."""
        seeds = self._load_seeds(slug)
        if seed not in seeds:
            raise BankError(
                f"{slug} has no seed {seed}. It has {min(seeds)}-{max(seeds)}; "
                f"raise --amount when generating if you need more."
            )
        return seeds[seed]

    def printable_seeds(self, slug):
        """Seeds safe to print: pregenerated, and published nowhere.

        Sorted, so a caller shuffling them controls its own randomness.
        """
        return sorted(s for s in self._load_seeds(slug) if s >= FIRST_PRINTABLE_SEED)

    def variant(self, slug, seed):
        """The variant label of one version, or None.

        `__variant__` is written by the wrapper for any generator declaring
        `variants`; it is how a print run asks for the case the course has
        reached.
        """
        return self.data(slug, seed).get("__variant__")

    def seeds_with_variant(self, slug, variant):
        if variant is None:
            return self.printable_seeds(slug)
        found = [s for s in self.printable_seeds(slug)
                 if self.variant(slug, s) == variant]
        if not found:
            labels = sorted({self.variant(slug, s) or "(none)"
                             for s in self.printable_seeds(slug)})
            raise BankError(
                f"{slug} has no printable version with variant {variant!r}. "
                f"It has: {', '.join(labels)}"
            )
        return found

    # -- files ------------------------------------------------------------

    def exercise(self, slug, seed):
        """One version as a checkit Exercise, for rendering its SpaTeXt.

        Indexed on first use: `Outcome.exercises()` returns every seed, and
        scanning a thousand of them per skill per student adds up.
        """
        cache = getattr(self, "_exercises", None)
        if cache is None:
            cache = self._exercises = {}
        if slug not in cache:
            cache[slug] = {e.seed: e for e in self.outcome(slug).exercises()}
        found = cache[slug].get(seed)
        if found is None:
            raise BankError(f"{slug} has no exercise at seed {seed}.")
        return found

    def print_template(self, slug):
        """The outcome's `textemplate.tex`, or None if it has none.

        Its absence is not an error: an outcome without one is rendered from its
        SpaTeXt instead. That path is not built yet, so for now the caller
        reports it.
        """
        path = os.path.join(self.outcome(slug).abspath(), "textemplate.tex")
        if not os.path.isfile(path):
            return None
        with open(path, encoding="utf-8") as f:
            return f.read()

    def helper_sty(self):
        """`bank_helpers.sty`, the macros this bank's content needs, or None."""
        path = os.path.join(self.path, "bank_helpers.sty")
        if not os.path.isfile(path):
            return None
        with open(path, encoding="utf-8") as f:
            return f.read()

    def asset_dir(self):
        return os.path.join(self.path, "assets")
