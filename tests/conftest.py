"""A tiny real CheckIt bank, built on disk, for the tests to print from.

Real rather than mocked: the tool's whole job is reading a bank's files, and a
mock would only prove the mock matches my assumptions. This builds one with
`checkit generate`, which is slow enough to be session-scoped and honest enough
to catch a wrong path.
"""

import os
import subprocess
import sys
import textwrap

import pytest

from checkit import BUNDLE_UNTIL

BANK_XML = """<?xml version='1.0' encoding='UTF-8'?>
<bank xmlns="https://checkit.clontz.org" version="0.2">
    <title>Print Test Bank</title>
    <slug>print-test</slug>
    <url>https://example.org</url>
    <outcomes>
        <outcome>
            <title>Adding</title>
            <slug>AD</slug>
            <path>outcomes/AD</path>
            <description>I can add two numbers.</description>
        </outcome>
        <outcome>
            <title>Subtracting</title>
            <slug>SU</slug>
            <path>outcomes/SU</path>
            <description>I can subtract two numbers.</description>
        </outcome>
    </outcomes>
</bank>
"""

GENERATOR = textwrap.dedent("""
    import random


    class Generator(BaseGenerator):
        variants = ["small", "large"]

        def data(self):
            top = 9 if self.variant == "small" else 99
            a, b = random.randint(1, top), random.randint(1, top)
            return {"a": a, "b": b, "answer": a + b}
""")

TEMPLATE = """<?xml version='1.0' encoding='UTF-8'?>
<knowl mode="exercise" xmlns="https://spatext.clontz.org" version="0.3">
    <content><p>Compute <m>{{a}} + {{b}}</m>.</p></content>
    <outtro><p><m>{{answer}}</m></p></outtro>
</knowl>
"""

# Uses \\VAR and \\ans, so it exercises the real delimiters and the real theme.
TEXTEMPLATE = r"""\setvseed{\VAR{seed}}
\skillheader{%s}

Compute the following.

\begin{enumerate}
    \item $\VAR{a} + \VAR{b} = $ \fillinblank[1in]{\VAR{answer}}
\end{enumerate}
"""


@pytest.fixture(scope="session")
def bank_dir(tmp_path_factory):
    root = tmp_path_factory.mktemp("bank")
    for slug in ("AD", "SU"):
        d = root / "outcomes" / slug
        d.mkdir(parents=True)
        (d / "generator.py").write_text(GENERATOR, encoding="utf-8")
        (d / "template.xml").write_text(TEMPLATE, encoding="utf-8")
        # AD has a print template; SU deliberately does not, so the SpaTeXt
        # fallback is exercised by every test that touches it. An outcome
        # needing only one template is the intended default.
        if slug == "AD":
            (d / "textemplate.tex").write_text(TEXTEMPLATE % slug, encoding="utf-8")
    (root / "bank.xml").write_text(BANK_XML, encoding="utf-8")

    # Enough seeds that some land above BUNDLE_UNTIL, or there is nothing
    # printable and every test would fail for the same uninteresting reason.
    amount = BUNDLE_UNTIL + 40
    subprocess.run(
        [sys.executable, "-m", "checkit", "generate", "-a", str(amount),
         "--no-precompute"],
        cwd=root, check=True, capture_output=True,
    )
    return str(root)
