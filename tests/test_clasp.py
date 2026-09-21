"""Driving clasp.

The Google side cannot be exercised from here, so these cover the parts that
are ours: how clasp is found, how its output is read, and that a failure
becomes a sentence rather than a traceback.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from checkit_printit import clasp


class TestFindingIt:
    def test_an_installed_clasp_is_preferred(self, monkeypatch):
        monkeypatch.setattr(clasp.shutil, "which",
                            lambda n: "/bin/clasp" if n == "clasp" else None)
        assert clasp.command() == ["/bin/clasp"]

    def test_otherwise_npx_runs_it_without_installing_anything(self, monkeypatch):
        """A Python virtual environment cannot hold a Node program, and asking
        someone to install one globally to print a quiz is a poor trade."""
        monkeypatch.setattr(clasp.shutil, "which",
                            lambda n: "/bin/npx" if n == "npx" else None)
        assert clasp.command() == ["/bin/npx", "--yes", clasp.PACKAGE]

    def test_no_node_at_all_says_what_to_install(self, monkeypatch):
        monkeypatch.setattr(clasp.shutil, "which", lambda n: None)
        with pytest.raises(clasp.ClaspError, match="nodejs.org"):
            clasp.command()


class TestReadingTheOutput:
    def test_a_deployment_id_is_found_by_shape(self):
        """Matched on shape rather than position, because the sentence around
        it has changed between clasp versions."""
        out = "Created version 1.\n- AKfycbwK9m2PqR7xY3tNvL8sD4hG6jF0aB1cE5dZ @1."
        assert clasp._deployment_id(out) == "AKfycbwK9m2PqR7xY3tNvL8sD4hG6jF0aB1cE5dZ"

    def test_punctuation_around_it_is_stripped(self):
        out = "Deployed (AKfycbwK9m2PqR7xY3tNvL8sD4hG6jF0aB1cE5dZ)."
        assert clasp._deployment_id(out).startswith("AKfycb")

    def test_no_id_in_the_output_is_an_error_with_the_output_in_it(self):
        with pytest.raises(clasp.ClaspError, match="Permission denied"):
            clasp._deployment_id("Error: Permission denied")

    def test_a_short_lookalike_is_not_mistaken_for_one(self):
        with pytest.raises(clasp.ClaspError):
            clasp._deployment_id("AKfycb")

    def test_the_web_app_url_is_built_from_the_id(self):
        assert clasp.web_app_url("AKfycbXYZ").endswith("/AKfycbXYZ/exec")

class TestNotTrustingTheExitCode:
    """clasp 3.4.1 refuses some input, says so, and exits 0 anyway.

    Verified by hand:

        $ clasp create-script --type bogus --title x
        Invalid script type "bogus". Valid types are: standalone, webapp,
        api, docs, forms, sheets, slides.
        $ echo $?
        0

    Without this, the refusal surfaced downstream as "no .clasp.json, so
    clasp did not leave a project behind" -- true, and pointing at the wrong
    thing entirely.
    """

    def _fake(self, monkeypatch, stdout, code=0):
        import subprocess

        class Done:
            returncode = code
            stderr = ""
        Done.stdout = stdout
        monkeypatch.setattr(clasp.shutil, "which",
                            lambda n: "/bin/clasp" if n == "clasp" else None)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())

    def test_an_invalid_type_is_an_error_despite_exit_zero(self, monkeypatch):
        self._fake(monkeypatch, 'Invalid script type "bogus". Valid types '
                                'are: standalone, webapp, api, docs, forms.')
        with pytest.raises(clasp.ClaspError, match="invalid script type"):
            clasp.run(["create-script", "--type", "bogus"])

    def test_an_unknown_command_is_an_error_despite_exit_zero(self, monkeypatch):
        """clasp answers an unknown command with its global help, which reads
        a great deal like success."""
        self._fake(monkeypatch, 'Unknown command "clasp push-files"\n'
                                'Usage: clasp <command> [options]')
        with pytest.raises(clasp.ClaspError, match="unknown command"):
            clasp.run(["push-files"])

    def test_the_error_says_the_exit_code_was_zero(self, monkeypatch):
        self._fake(monkeypatch, 'Unknown command "clasp nope"')
        with pytest.raises(clasp.ClaspError, match="exit 0"):
            clasp.run(["nope"])

    def test_ordinary_output_still_passes(self, monkeypatch):
        self._fake(monkeypatch, "Created new Apps Script project.")
        code, out = clasp.run(["create-script"])
        assert code == 0 and "Created" in out


class TestTheCommandNamesClaspActuallyHas:
    """Pinned against `clasp --help` on 3.4.1. Both of these were wrong and
    no test noticed, because nothing asserted on the argv."""

    def _record(self, monkeypatch):
        seen = []

        def fake_run(args, **kwargs):
            seen.append(list(args))
            return 0, ""
        monkeypatch.setattr(clasp, "run", fake_run)
        return seen

    def test_a_form_script_asks_for_the_plural_type(self, monkeypatch, tmp_path):
        """`forms`. The singular is rejected -- with exit 0."""
        seen = self._record(monkeypatch)
        monkeypatch.setattr(clasp, "script_id", lambda d: "sid")
        clasp.create_form("Title", str(tmp_path))
        assert seen[0][:3] == ["create-script", "--type", "forms"]

    def test_pushing_uses_push(self, monkeypatch, tmp_path):
        """`push`, not `push-files`, which is not a command at all."""
        seen = self._record(monkeypatch)
        clasp.push(str(tmp_path))
        assert seen[0][0] == "push"

    def test_deploying_uses_create_deployment(self, monkeypatch, tmp_path):
        seen = self._record(monkeypatch)
        monkeypatch.setattr(clasp, "_deployment_id", lambda o: "AKfycb" + "x" * 30)
        clasp.deploy(str(tmp_path))
        assert seen[0][0] == "create-deployment"
