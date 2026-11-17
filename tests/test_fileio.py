"""Course state is replaced whole or not at all.

RV-10 of the 2026-11-16 review. Almost every file printit keeps was
written as

    with open(path, "w") as f:
        f.write(make_the_contents())

which empties the file *before* the contents are worked out. If that
work raises -- and `availability.set_values` raises on purpose -- the
file is left at zero bytes. One file in twenty-three was written safely
(`vault.save`). Now all course state goes through `fileio.atomic_write`.
"""

import os

import pytest

from checkit_printit import availability, fileio, roster as roster_mod, theme


def test_the_file_is_replaced_whole(tmp_path):
    path = tmp_path / "a.toml"
    path.write_text("old\n", encoding="utf-8")
    fileio.atomic_write(str(path), "new\n")
    assert path.read_text(encoding="utf-8") == "new\n"


def test_no_temporary_file_is_left_behind(tmp_path):
    path = tmp_path / "a.toml"
    fileio.atomic_write(str(path), "x")
    assert os.listdir(tmp_path) == ["a.toml"]


def test_a_failed_write_leaves_the_old_file_and_no_litter(tmp_path, monkeypatch):
    path = tmp_path / "a.toml"
    path.write_text("old\n", encoding="utf-8")

    def broken(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(fileio.os, "replace", broken)
    with pytest.raises(OSError):
        fileio.atomic_write(str(path), "new\n")
    assert path.read_text(encoding="utf-8") == "old\n"
    assert os.listdir(tmp_path) == ["a.toml"]


def test_the_newline_argument_is_honoured(tmp_path):
    path = tmp_path / "a.csv"
    fileio.atomic_write(str(path), "a\r\nb\r\n", newline="")
    assert path.read_bytes() == b"a\r\nb\r\n"


# ---------------------------------------------- the cases that reached it --

AVAILABILITY_WITHOUT_DUE = """\
[assessment]
name   = "Skill Checkpoint Redo"
date   = 2026-11-20
choose = 3
limit  = "at most"
skills = ["W1", "N2"]
"""


def test_skills_set_on_a_file_missing_a_key_does_not_empty_it(tmp_path):
    """`set_values` raises when a key has no line of its own -- after
    the file had already been emptied."""
    path = tmp_path / "availability.toml"
    path.write_text(AVAILABILITY_WITHOUT_DUE, encoding="utf-8")
    with pytest.raises(availability.AvailabilityError):
        availability.set_assessment(str(path), due="2026-11-19T23:59")
    assert path.read_text(encoding="utf-8") == AVAILABILITY_WITHOUT_DUE


def test_a_roster_survives_its_serialiser_failing(tmp_path, monkeypatch):
    path = tmp_path / "roster.toml"
    text = '[[student]]\nname = "Ada Byron"\nsid = "001"\nskills = []\n'
    path.write_text(text, encoding="utf-8")

    def broken(*a, **k):
        raise RuntimeError("serialiser failed")
    monkeypatch.setattr(roster_mod, "to_toml", broken)
    with pytest.raises(RuntimeError):
        roster_mod.set_dropped(str(path), "Ada Byron", True)
    assert path.read_text(encoding="utf-8") == text


# ------------------------------------------------- bank.xml keeps its endings --

BANK_XML = (
    '<?xml version="1.0"?>\r\n'
    '<bank xmlns="https://checkit.clontz.org" version="0.2">\r\n'
    '    <title>T</title>\r\n'
    '    <slug>t</slug>\r\n'
    '    <url>https://example.org/t</url>\r\n'
    '    <outcomes/>\r\n'
    '</bank>\r\n')


def test_declaring_the_theme_keeps_a_crlf_bank_xml_crlf(tmp_path):
    """It read the file in text mode and wrote it with newline="", so a
    CRLF bank.xml came back LF from top to bottom -- a whole-file diff in
    the bank's repository for a two-line change."""
    (tmp_path / "bank.xml").write_bytes(BANK_XML.encode("utf-8"))
    assert theme.declare(str(tmp_path)) is True
    raw = (tmp_path / "bank.xml").read_bytes()
    assert raw.count(b"\n") == raw.count(b"\r\n")
    assert b"<latex-support>" in raw


def test_an_lf_bank_xml_stays_lf(tmp_path):
    (tmp_path / "bank.xml").write_bytes(
        BANK_XML.replace("\r\n", "\n").encode("utf-8"))
    theme.declare(str(tmp_path))
    assert b"\r" not in (tmp_path / "bank.xml").read_bytes()
