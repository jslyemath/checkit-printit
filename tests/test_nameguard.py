"""The name guard: a commit or push that adds a real student is refused.
DESIGN.md section 20.

Every person here is invented, and the home is a temporary one -- the
guard reads rosters, so a test that let it read the real home would test
against real students.
"""
import os
import pathlib
import shutil
import subprocess
import sys

import pytest
from click.testing import CliRunner

from checkit_printit import nameguard as ng
from checkit_printit.__main__ import main

SURNAME = "Quarrington"
FIRST = "Zebulon"
SID = "806111222"
EMAIL = "zquarr@example.edu"

ROSTER = (
    '[[student]]\n'
    f'name = "{FIRST} {SURNAME}"\n'
    f'sid = "{SID}"\n'
    f'email = "{EMAIL}"\n'
    'section = "820"\n'
    'skills = []\n'
)


@pytest.fixture
def home(tmp_path, monkeypatch):
    root = tmp_path / "home"
    (root / "courses" / "Real 101").mkdir(parents=True)
    (root / "courses" / "Real 101" / "roster.toml").write_text(ROSTER, encoding="utf-8")
    (root / "courses" / "Demo").mkdir(parents=True)
    (root / "courses" / "Demo" / "roster.toml").write_text(
        '[[student]]\nname = "Ottoline Brackwater"\nsid = "d01"\nskills = []\n',
        encoding="utf-8")
    (root / ng.CONFIG_NAME).write_text(
        'invented_courses = ["Demo"]\n'
        'fine_words = []\n'
        'names_fine_in = ["repo/wordlist.py"]\n', encoding="utf-8")
    monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(root))
    return root


def git(repo, *args, check=True, **kw):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, check=check, **kw)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "t@example.org")
    git(r, "config", "user.name", "T")
    (r / "README").write_text("start\n", encoding="utf-8")
    git(r, "add", "README")
    git(r, "commit", "-q", "-m", "start")
    return r


def loaded(home):
    allow = ng.load_allow(home)
    return ng.load_real(home, allow), allow


def stage(repo, name, text):
    (repo / name).write_text(text, encoding="utf-8")
    git(repo, "add", name)


def kinds(hits):
    return sorted(h.kind for h in hits)


# ------------------------------------------------------------ what counts --

def test_a_surname_an_id_and_an_address_are_each_refused(home, repo):
    real, allow = loaded(home)
    stage(repo, "notes.md",
          f"A chart says {SURNAME}.\nid {SID}\nmail {EMAIL.upper()}\n")
    hits = ng.staged(repo, real, allow)
    assert kinds(hits) == ["address", "id", "name"]
    assert [(h.line, h.column) for h in hits if h.kind == "name"] == [(1, 14)]


def test_a_preferred_first_and_last_name_are_each_refused(home, repo):
    """The names a student goes by are real too (DESIGN 22). The guard
    reads them through `Student.name_fields`, the one list every privacy
    path shares; a field missing from it would pass a commit."""
    (home / "courses" / "Real 101" / "roster.toml").write_text(
        ROSTER + f'first = "{FIRST}"\nlast = "{SURNAME}"\n'
                 'pref_first = "Tobiah"\npref_last = "Fenwright"\n',
        encoding="utf-8")
    real, allow = loaded(home)
    stage(repo, "notes.md", "Tobiah said so.\nAsk Fenwright.\n")
    hits = ng.staged(repo, real, allow)
    assert [(h.kind, h.line) for h in hits] == [("name", 1), ("name", 2)]


def test_a_refusal_never_shows_the_value(home, repo):
    real, allow = loaded(home)
    stage(repo, "notes.md", f"{FIRST} {SURNAME}, {SID}, {EMAIL}\n")
    shown = "\n".join(str(h) for h in ng.staged(repo, real, allow))
    assert shown and "####" in shown
    for value in (FIRST, SURNAME, SID, EMAIL):
        assert value not in shown


def test_capitals_count_lower_case_and_part_of_a_word_do_not(home, repo):
    real, allow = loaded(home)
    stage(repo, "notes.md",
          f"{SURNAME.upper()}\n{SURNAME.lower()}\n{SURNAME}ian\n")
    hits = ng.staged(repo, real, allow)
    assert [h.line for h in hits] == [1]


def test_only_added_lines_are_read(home, repo):
    real, allow = loaded(home)
    stage(repo, "notes.md", f"{SURNAME}\n")
    git(repo, "commit", "-q", "-m", "x", "--no-verify")
    (repo / "notes.md").write_text("", encoding="utf-8")
    git(repo, "add", "notes.md")
    assert ng.staged(repo, real, allow) == []


# ---------------------------------------------------------- the allowlist --

def test_a_fine_word_passes_anywhere(home, repo):
    (home / ng.CONFIG_NAME).write_text(
        f'invented_courses = ["Demo"]\nfine_words = ["{SURNAME}"]\n', encoding="utf-8")
    real, allow = loaded(home)
    stage(repo, "notes.md", f"{SURNAME} and {SURNAME.upper()}\n")
    assert ng.staged(repo, real, allow) == []


def test_an_id_or_an_address_can_never_be_a_fine_word(home):
    (home / ng.CONFIG_NAME).write_text(f'fine_words = ["{SID}"]\n', encoding="utf-8")
    with pytest.raises(ng.GuardError, match="never fine"):
        ng.load_allow(home)


def test_a_names_file_lets_names_through_but_not_ids(home, repo):
    real, allow = loaded(home)
    stage(repo, "wordlist.py", f"NAMES = ['{FIRST}', '{SURNAME}']  # {SID}\n")
    assert kinds(ng.staged(repo, real, allow)) == ["id"]


def test_an_invented_course_is_not_real(home, repo):
    real, allow = loaded(home)
    stage(repo, "notes.md", "Ottoline Brackwater, d01\n")
    assert ng.staged(repo, real, allow) == []


def test_a_course_not_listed_as_invented_is_real(home, repo):
    (home / ng.CONFIG_NAME).write_text("invented_courses = []\n", encoding="utf-8")
    real, allow = loaded(home)
    stage(repo, "notes.md", "Brackwater\n")
    assert kinds(ng.staged(repo, real, allow)) == ["name"]


def test_an_unknown_key_is_refused_rather_than_ignored(home):
    (home / ng.CONFIG_NAME).write_text('fine_word = ["x"]\n', encoding="utf-8")
    with pytest.raises(ng.GuardError, match="does not know"):
        ng.load_allow(home)


# -------------------------------------------------- the sources it reads --

def test_seating_charts_and_vaults_are_read_too(home, repo):
    shutil.rmtree(home / "courses" / "Real 101")
    job = home / "jobs" / "W1"
    job.mkdir(parents=True)
    (job / "seating.toml").write_text(
        'versions = ["A", "B"]\n[[group]]\nseats = ["Peregrine Ashdown"]\n',
        encoding="utf-8")
    real, allow = loaded(home)
    stage(repo, "notes.md", "Ashdown\n")
    assert kinds(ng.staged(repo, real, allow)) == ["name"]


def test_a_vaults_address_domain_is_not_a_name(home, repo):
    from checkit_printit import vault as vault_mod
    v = vault_mod.Vault(course="Real 101")
    person, _ = v.resolve({"first": "Imogen", "last": "Thackery",
                           "email": "ithack@example.edu"})
    v.mask("last", "Thackery", person)
    v.mask("email", "ithack@example.edu", person)
    v.save(str(home / "vaults" / "Real 101.json"))
    real, allow = loaded(home)
    assert "Thackery" in real.names
    assert "example" not in real.names and "edu" not in real.names


# ------------------------------------------------------- failing closed --

def test_no_roster_anywhere_is_a_refusal(home):
    shutil.rmtree(home / "courses" / "Real 101")
    with pytest.raises(ng.GuardError, match="nothing to check against"):
        loaded(home)


def test_an_unreadable_roster_is_a_refusal(home):
    (home / "courses" / "Real 101" / "roster.toml").write_text("[[student\n", encoding="utf-8")
    with pytest.raises(ng.GuardError, match="could not be read"):
        loaded(home)


def test_masking_on_does_not_write_a_vault(home, monkeypatch):
    monkeypatch.setenv("CHECKIT_PRINTIT_MASK_NAMES", "1")
    loaded(home)
    assert not (home / "vaults").exists()
    assert os.environ["CHECKIT_PRINTIT_MASK_NAMES"] == "1"


# ------------------------------------------------ pushes and the history --

def test_a_push_reads_every_commit_not_just_the_last(home, repo):
    real, allow = loaded(home)
    base = git(repo, "rev-parse", "HEAD").stdout.strip()
    stage(repo, "notes.md", f"{SURNAME}\n")
    git(repo, "commit", "-q", "-m", "add", "--no-verify")
    (repo / "notes.md").write_text("gone\n", encoding="utf-8")
    git(repo, "add", "notes.md")
    git(repo, "commit", "-q", "-m", "remove", "--no-verify")
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    refs = f"refs/heads/main {head} refs/heads/main {base}\n"
    assert kinds(ng.pushed(repo, refs, real, allow)) == ["name"]


def test_a_commit_message_is_read(home, repo):
    real, allow = loaded(home)
    git(repo, "commit", "-q", "--allow-empty", "--no-verify", "-m", f"for {SURNAME}")
    hits = ng.commits(repo, ["-1"], real, allow)
    assert [h.where for h in hits] == ["repo (commit message)"]


def test_the_history_reads_a_value_long_deleted(home, repo):
    real, allow = loaded(home)
    stage(repo, "old.md", f"{EMAIL}\n")
    git(repo, "commit", "-q", "-m", "add", "--no-verify")
    git(repo, "rm", "-q", "old.md")
    git(repo, "commit", "-q", "-m", "rm", "--no-verify")
    assert kinds(ng.history(repo, ["--branches"], real, allow)) == ["address"]
    assert ng.tree(repo, real, allow) == []


def test_a_mirror_is_named_without_its_dot_git(tmp_path):
    assert ng.repo_name(tmp_path / "repo.git") == "repo"
    assert ng.repo_name(tmp_path / "repo") == "repo"


# ------------------------------------------------------- the command line --

def test_the_command_refuses_and_names_no_one(home, repo):
    stage(repo, "notes.md", f"{FIRST} {SURNAME}\n")
    result = CliRunner().invoke(main, ["names", "check", "--staged", "--repo", str(repo)])
    assert result.exit_code == 1
    assert "Nothing was committed or pushed" in result.output
    assert SURNAME not in result.output and FIRST not in result.output


def test_the_command_says_what_it_checked_when_clean(home, repo):
    stage(repo, "notes.md", "nobody\n")
    result = CliRunner().invoke(main, ["names", "check", "--staged", "--repo", str(repo)])
    assert result.exit_code == 0
    assert "checked against" in result.output


def test_a_guard_that_cannot_check_refuses(home, repo):
    shutil.rmtree(home / "courses")
    result = CliRunner().invoke(main, ["names", "check", "--staged", "--repo", str(repo)])
    assert result.exit_code == 1
    assert "must not pass" in result.output


def test_a_message_file_is_checked_without_its_comment_lines(home, repo, tmp_path):
    msg = tmp_path / "MSG"
    msg.write_text(f"Fix the import\n# {SURNAME} in a comment git strips\n", encoding="utf-8")
    ok = CliRunner().invoke(main, ["names", "check", "--message", str(msg), "--repo", str(repo)])
    assert ok.exit_code == 0
    msg.write_text(f"Fix the import for {SURNAME}\n", encoding="utf-8")
    bad = CliRunner().invoke(main, ["names", "check", "--message", str(msg), "--repo", str(repo)])
    assert bad.exit_code == 1


# ------------------------------------------------- operate the control --

HOOKS = pathlib.Path(__file__).resolve().parent.parent / "githooks"
HOOK_PYTHON = pathlib.Path("C:/Users/slye/Projects/checkit-printit/.venv/Scripts/python.exe")


@pytest.mark.skipif(not HOOK_PYTHON.exists(), reason="the hooks name this machine's Python")
def test_git_itself_refuses_the_commit_and_the_message(home, repo):
    git(repo, "config", "core.hooksPath", str(HOOKS))
    env = {**os.environ, "CHECKIT_PRINTIT_HOME": str(home)}
    stage(repo, "notes.md", f"{SURNAME}\n")
    refused = git(repo, "commit", "-m", "notes", check=False, env=env)
    assert refused.returncode != 0
    assert "name guard" in refused.stderr and SURNAME not in refused.stderr
    assert git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "1"

    stage(repo, "notes.md", "nobody\n")
    refused = git(repo, "commit", "-m", f"notes on {SURNAME}", check=False, env=env)
    assert refused.returncode != 0
    accepted = git(repo, "commit", "-m", "notes", check=False, env=env)
    assert accepted.returncode == 0, accepted.stderr
