"""Running pdflatex over an assembled folder.

Shells out rather than using the `latex` PyPI package the original pipeline
depended on: that package is unmaintained, and "run a command in a directory"
does not need one.
"""

import os
import shutil
import subprocess


class CompileError(Exception):
    pass


#: Twice, because the theme uses `lastpage` -- "Page 3 of 12" is wrong on the
#: first run, when the label does not exist yet.
PASSES = 2

TIMEOUT = 600

#: The log is for reading, not for parsing, so a byte that decodes to nothing
#: sensible should cost one character and not the whole run.
DECODING = {"encoding": "utf-8", "errors": "replace"}


def find_pdflatex():
    found = shutil.which("pdflatex")
    if found is None:
        raise CompileError(
            "pdflatex is not on your PATH. Install a LaTeX distribution "
            "(TeX Live, MiKTeX, or MacTeX), or use --no-compile and build the "
            "generated folder yourself."
        )
    return found


def compile_pdf(out_dir, log_path=None):
    """Compile `main.tex`. Returns the path to the PDF.

    pdflatex exits non-zero on recoverable errors while still producing a valid
    PDF, so success is judged by whether the file appeared, not by the exit
    code. The log is kept either way: it is the only place the real error
    message lives, and it is far too long for a terminal.
    """
    pdflatex = find_pdflatex()
    main = os.path.join(out_dir, "main.tex")
    if not os.path.isfile(main):
        raise CompileError(f"no main.tex in {out_dir!r}; assemble first.")

    output = []
    for _ in range(PASSES):
        result = subprocess.run(
            [pdflatex, "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
            cwd=out_dir, capture_output=True, timeout=TIMEOUT,
            # Decode here rather than with text=True, which uses the locale
            # encoding. pdflatex echoes font and file names byte for byte, so on
            # a cp1252 Windows console a single 0x81 from a font the theme loads
            # kills the reader thread, leaves stdout as None, and turns a real
            # LaTeX error into a TypeError six lines later.
            **DECODING,
        )
        output.append(result.stdout + result.stderr)

    log_path = log_path or os.path.join(out_dir, "compile.log")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(output))

    pdf = os.path.join(out_dir, "main.pdf")
    if not os.path.isfile(pdf):
        raise CompileError(
            f"pdflatex produced no PDF. The full log is at {log_path}.\n"
            + _first_error(output[-1])
        )
    return pdf


def _first_error(log):
    """The first LaTeX error, which is usually the only one that matters.

    Everything after the first is often a cascade, and a thousand lines of it is
    how a real message gets lost.
    """
    lines = log.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("! "):
            return "\n".join(lines[i:i + 6])
    return "No line starting with '!' was found; the log may explain why."
