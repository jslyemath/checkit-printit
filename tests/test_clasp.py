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
