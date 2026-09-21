"""A course, and a job that names one instead of copying it.

The problem this fixes was measured, not imagined: three job folders on one
machine each held their own copy of the same forty-eight students, because a
job resolves its roster relative to itself. A student who dropped had to be
remembered and re-applied at the next copy.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from checkit_printit import publication as pub_mod
from checkit_printit import course as ws


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def job(home):
    """A job folder shaped like a real one: its own roster and seating."""
    d = home / "jobs" / "D1 2026-09-13"
    d.mkdir(parents=True)
    (d / "roster.toml").write_text(
        '[[student]]\nname = "Ada Lovelace"\nsection = "820"\nskills = ["W1"]\n',
        encoding="utf-8")
    (d / "seating.toml").write_text(
        'versions = ["A", "B"]\n[[group]]\nseats = ["Ada Lovelace"]\n',
        encoding="utf-8")
    return d


class TestNaming:
    def test_a_course_is_a_directory_under_the_root(self, home):
        assert ws.path_for("MAT 106").startswith(str(home))
        assert ws.path_for("MAT 106").endswith("MAT 106")

    @pytest.mark.parametrize("bad", ["", "  ", ".", "..", "a/b", "a\\b"])
    def test_a_name_that_would_escape_its_directory_is_refused(self, home, bad):
        with pytest.raises(ws.CourseError):
            ws.path_for(bad)

    def test_the_home_variable_moves_the_root(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path / "elsewhere"))
        assert str(tmp_path / "elsewhere") in ws.path_for("X")


class TestInit:
    def test_it_creates_what_a_course_needs(self, home):
        path, _ = ws.init("MAT 106", bank="/banks/mat106")
        assert os.path.isfile(os.path.join(path, ws.CONFIG))
        assert os.path.isfile(os.path.join(path, "availability.toml"))
        assert os.path.isdir(os.path.join(path, ws.SECRETS))
        assert ws.exists("MAT 106")

    def test_it_will_not_overwrite_one(self, home):
        ws.init("MAT 106")
        with pytest.raises(ws.CourseError, match="already exists"):
            ws.init("MAT 106")

    def test_adopting_copies_the_roster_and_the_seating(self, home, job):
        path, notes = ws.init("MAT 106", adopt=str(job))
        assert os.path.isfile(os.path.join(path, "roster.toml"))
        assert os.path.isfile(os.path.join(path, "seating.toml"))
        copied = [n for n in notes if n.startswith("adopted ")]
        assert len(copied) == 2, copied

    def test_adopting_warns_that_the_roster_has_no_ids(self, home, job):
        """An adopted roster carries display names only, so the class list
        imported next has to reconcile against those names."""
        _, notes = ws.init("MAT 106", adopt=str(job))
        assert any("no student ids" in n for n in notes)

    def test_the_newest_job_is_the_one_offered(self, home, job):
        older = home / "jobs" / "W1 2026-09-10"
        older.mkdir(parents=True)
        (older / "roster.toml").write_text("[[student]]\nname = \"X\"\nskills = []\n",
                                           encoding="utf-8")
        os.utime(older, (1, 1))
        assert ws.newest_job().endswith("D1 2026-09-13")

    def test_no_jobs_at_all_offers_nothing(self, home):
        assert ws.newest_job() is None


class TestAJobThatNamesACourse:
    def publication(self, tmp_path, body):
        d = tmp_path / "job"
        d.mkdir(exist_ok=True)
        p = d / "publication.toml"
        p.write_text(body, encoding="utf-8")
        return str(p)

    def test_the_roster_comes_from_the_course(self, home, job, bank_dir):
        ws.init("MAT 106", adopt=str(job))
        pub = pub_mod.load(self.publication(home, f'''
[course]
folder = "MAT 106"
[bank]
path = {bank_dir!r}
'''))
        assert pub.course_folder == "MAT 106"
        assert pub.roster_path == ws.file_in("MAT 106", "roster")
        assert pub.seating_path == ws.file_in("MAT 106", "seating")

    def test_an_explicit_path_still_wins(self, home, job, bank_dir):
        """Every job folder written before courses existed keeps working."""
        ws.init("MAT 106", adopt=str(job))
        (home / "job").mkdir(exist_ok=True)
        (home / "job" / "own.toml").write_text(
            '[[student]]\nname = "B"\nskills = []\n', encoding="utf-8")
        pub = pub_mod.load(self.publication(home, f'''
[course]
folder = "MAT 106"
[bank]
path = {bank_dir!r}
[roster]
path = "own.toml"
'''))
        assert pub.roster_path.endswith("own.toml")

    def test_the_bank_can_come_from_the_course(self, home, job, bank_dir):
        ws.init("MAT 106", bank=str(bank_dir), adopt=str(job))
        pub = pub_mod.load(self.publication(home, '''
[course]
folder = "MAT 106"
'''))
        assert os.path.normpath(pub.bank_path) == os.path.normpath(str(bank_dir))

    def test_naming_a_course_that_does_not_exist_says_where(self, home, bank_dir):
        with pytest.raises(pub_mod.PublicationError, match="does not exist"):
            pub_mod.load(self.publication(home, f'''
[course]
folder = "Nope"
[bank]
path = {bank_dir!r}
'''))

    def test_the_header_name_is_not_a_folder(self, home, job, bank_dir):
        """`name` prints; `folder` resolves. They are never the same field.

        Every job folder written before courses existed says
        `[course] name = "MAT 106"` and means the printed header. Reading that
        as a directory would silently pull in a roster nobody asked for -- and
        a course called "MAT 106" is exactly what an instructor would make.
        """
        ws.init("MAT 106", adopt=str(job))
        pub = pub_mod.load(self.publication(home, f'''
[course]
name = "MAT 106"
[bank]
path = {bank_dir!r}
[roster]
path = "own.toml"
'''))
        assert pub.course == "MAT 106"
        assert pub.course_folder == ""
        assert pub.roster_path != ws.file_in("MAT 106", "roster")
