"""CHECKIT_PRINTIT_MASK_NAMES: pseudonyms in everything the CLI prints.

The point is an assistant reading printit's output never sees a real
name. So each test runs a real command through the CLI's entry point with
an invented student in a real course folder, and looks for her name in
what came out. Every name here is invented.
"""

import os

import pytest
from click.testing import CliRunner

from checkit_printit import course as course_mod
from checkit_printit import privacy
from checkit_printit import roster as roster_mod
from checkit_printit import vault as vault_mod
from checkit_printit.__main__ import main

ROSTER = '''
[[student]]
name    = "Philippa Quarrington"
first   = "Philippa"
last    = "Quarrington"
sid     = "806000111"
email   = "pquarrington@example.edu"
skills  = []

[[student]]
name    = "Ottoline Vexley"
first   = "Ottoline"
last    = "Vexley"
sid     = "806000222"
skills  = []
'''

REAL = ("Philippa", "Quarrington", "Ottoline", "Vexley", "806000111",
        "pquarrington")


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    """No vault carried over from another test's home."""
    monkeypatch.setattr(privacy, "_open", {})


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
    course_mod.init("P")
    path = course_mod.file_in("P", "roster")
    with open(path, "w", encoding="utf-8") as f:
        f.write(ROSTER)
    return tmp_path


def run(*args, masked=True):
    env = {privacy.ENV: "1" if masked else ""}
    return CliRunner(env=env).invoke(main, list(args), catch_exceptions=False)


def leaked(text):
    """The real values in `text`. Refuses withheld output, which would
    pass trivially: nothing shown, nothing leaked."""
    assert "withheld" not in text, text
    return [r for r in REAL if r.lower() in text.lower()]


class TestOff:
    def test_nothing_changes_and_no_vault_is_made(self, home):
        got = run("record", "student", "Philippa Quarrington", "-c", "P",
                  masked=False)
        assert "Philippa Quarrington" in got.output
        assert not os.path.exists(vault_mod.path_for("P"))


class TestOn:
    def test_a_report_line_carries_the_pseudonym(self, home):
        got = run("record", "student", "Philippa Quarrington", "-c", "P")
        assert got.exit_code == 0, got.output
        assert leaked(got.output) == []

    def test_the_pseudonym_unmasks_back(self, home):
        got = run("record", "student", "806000111", "-c", "P")
        assert leaked(got.output) == []
        store = vault_mod.Vault.load(vault_mod.path_for("P"))
        back, count = store.unmask_text(got.output)
        assert count and "Philippa Quarrington" in back

    def test_one_pseudonym_per_person_across_commands(self, home):
        first = run("record", "student", "806000222", "-c", "P").output
        again = run("record", "student", "806000222", "-c", "P").output
        assert first == again

    def test_an_error_message_is_masked_too(self, home):
        # A name in an exception, raised far from any print site.
        first = run("roster", "drop", "Philippa Quarrington",
                    "-r", course_mod.file_in("P", "roster"),
                    "-s", os.path.join(home, "nowhere.toml"))
        assert leaked(first.output) == []
        got = run("roster", "drop", "Philippa Quarrington",
                  "-r", course_mod.file_in("P", "roster"),
                  "-s", os.path.join(home, "nowhere.toml"))
        assert "already dropped" in got.output
        assert leaked(got.output) == []

    def test_a_class_list_names_people_before_the_roster_has_them(
            self, home, tmp_path):
        listing = tmp_path / "list.csv"
        listing.write_text("Last,First,Student ID\nVexley,Ottoline,806000222\n"
                           "Ashgrove,Cressida,806000999\n", encoding="utf-8")
        got = run("roster", "import", str(listing),
                  "-o", course_mod.file_in("P", "roster"), "--dry-run")
        assert got.exit_code == 0, got.output
        assert "Cressida" not in got.output and "Ashgrove" not in got.output

    def test_a_seat_holding_a_name_no_roster_has(self, home, monkeypatch):
        monkeypatch.setenv(privacy.ENV, "1")
        path = course_mod.file_in("P", "seating")
        with open(path, "w", encoding="utf-8") as f:
            f.write('[[group]]\nseats = ["Wilhelmina Strake"]\n')
        from checkit_printit import seating
        seating.load(path)
        assert "Strake" not in privacy.mask("seat: Wilhelmina Strake")

    def test_a_file_outside_any_course_goes_to_unfiled(self, home, tmp_path):
        loose = tmp_path / "elsewhere" / "roster.toml"
        loose.parent.mkdir()
        loose.write_text(ROSTER, encoding="utf-8")
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv(privacy.ENV, "1")
            roster_mod.load(str(loose))
            assert privacy.course_of(str(loose)) == privacy.UNFILED
            assert os.path.exists(vault_mod.path_for(privacy.UNFILED))
            assert "Vexley" not in privacy.mask("Ottoline Vexley")


class TestALongProcessDoesNotLoseOtherPseudonyms:
    """The web app is one long process. A vault it read in the morning and
    saved in the afternoon would discard what `vault mask` added since."""

    def test(self, home, monkeypatch):
        monkeypatch.setenv(privacy.ENV, "1")
        roster_mod.load(course_mod.file_in("P", "roster"))   # held from here
        path = vault_mod.path_for("P")
        other = vault_mod.Vault.load(path)                    # another process
        other.resolve({"first": "Leocadia", "last": "Brunt"})
        other.save(path)
        privacy.saw_names(["Severin Toll"], course_mod.file_in("P", "seating"))
        names = {p.real.get("last") for p in vault_mod.Vault.load(path).people}
        assert {"Brunt", "Quarrington"} <= names


class TestItFailsClosed:
    def test_an_unreadable_vault_stops_the_command(self, home):
        path = vault_mod.path_for("P")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("{ this is not a vault")
        got = CliRunner(env={privacy.ENV: "1"}).invoke(
            main, ["record", "student", "Philippa Quarrington", "-c", "P"])
        assert got.exit_code != 0
        assert "could not be opened" in got.output
        assert [r for r in REAL if r.lower() in got.output.lower()] == []

    def test_output_that_cannot_be_masked_is_withheld(self, monkeypatch):
        import io
        sink = io.StringIO()
        stream = privacy._Masked(sink)

        def broken(text):
            raise RuntimeError("no")
        monkeypatch.setattr(privacy, "mask", broken)
        stream.write("Philippa Quarrington\n")
        assert "Philippa" not in sink.getvalue()
        assert "withheld" in sink.getvalue()


class TestTheStreamHasNoBackDoor:
    def test_no_buffer(self):
        import io
        assert not hasattr(privacy._Masked(io.StringIO()), "buffer")
