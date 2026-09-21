"""Talking to the form.

The Google half cannot be exercised from here -- no account, no deployment --
so these tests stand up a local HTTP server that answers the way the Apps
Script does, including the ways it fails. That covers everything on this side
of the wire: what gets sent, what is done with the answer, and what happens
when the answer is not the one expected.

What it does not cover is whether the script itself is correct. That is
unverified until it is deployed against a real form, and saying so is part of
the test rather than a footnote.
"""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import urllib.error

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from checkit_printit import availability as av
from checkit_printit import form


class FakeScript:
    """A stand-in for the deployed web app, recording what it was sent."""

    def __init__(self, secret="s3cret", answers=None, status=200, body=None):
        self.secret = secret
        self.answers = answers or {}
        self.status = status
        self.body = body
        self.received = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                request = json.loads(self.rfile.read(length) or b"{}")
                outer.received.append(request)

                if outer.body is not None or outer.status != 200:
                    self.send_response(outer.status)
                    self.end_headers()
                    self.wfile.write((outer.body or "").encode())
                    return

                if request.get("secret") != outer.secret:
                    answer = {"ok": False, "error": "the secret did not match"}
                else:
                    answer = outer.answers.get(
                        request.get("op"),
                        {"ok": False, "error": "unknown op"})
                payload = json.dumps(answer).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/"
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def script():
    s = FakeScript(answers={
        "ping": {"ok": True, "form": "Skill Selection Form"},
        "describe": {"ok": True, "items": [
            {"id": "11", "type": "SECTION_HEADER", "title": "What am I selecting skills for?", "help": "..."},
            {"id": "22", "type": "CHECKBOX", "title": "Confirm Skill Checkpoint Date", "help": ""},
            {"id": "33", "type": "CHECKBOX", "title": "Choose At Most THREE Skills", "help": ""},
        ]},
        "push": {"ok": True, "changed": ["selecting_for", "choose_skills"]},
    })
    yield s
    s.stop()


def connection(script, **kw):
    base = dict(url=script.url, secret=script.secret,
                items={"selecting_for": "11", "confirm_date": "22",
                       "choose_skills": "33"})
    base.update(kw)
    return form.Connection(**base)


class TestTalking:
    def test_a_call_carries_the_operation_and_the_secret(self, script):
        form.call(connection(script), "ping")
        assert script.received[0]["op"] == "ping"
        assert script.received[0]["secret"] == "s3cret"

    def test_the_wrong_secret_is_reported_not_swallowed(self, script):
        conn = connection(script, secret="wrong")
        with pytest.raises(form.FormError, match="secret did not match"):
            form.call(conn, "ping")

    def test_no_url_at_all_says_what_to_do(self):
        with pytest.raises(form.FormError, match="form connect"):
            form.call(form.Connection(secret="x"), "ping")

    def test_an_html_answer_means_it_is_asking_for_a_login(self):
        """A deployment set to anything but 'Anyone' serves a sign-in page,
        and a command line cannot complete one. The error has to say that,
        because the symptom -- HTML instead of JSON -- explains nothing."""
        s = FakeScript(body="<html>Sign in</html>")
        try:
            with pytest.raises(form.FormError, match="Anyone"):
                form.call(form.Connection(url=s.url, secret="s3cret"), "ping")
        finally:
            s.stop()

    def test_an_http_error_explains_the_likely_cause(self):
        s = FakeScript(status=403, body="nope")
        try:
            with pytest.raises(form.FormError, match="403"):
                form.call(form.Connection(url=s.url, secret="s3cret"), "ping")
        finally:
            s.stop()

    def test_an_unreachable_url_is_not_a_traceback(self):
        conn = form.Connection(url="http://127.0.0.1:9/", secret="x")
        with pytest.raises(form.FormError, match="could not reach"):
            form.call(conn, "ping", timeout=2)


class TestWhatGetsSent:
    def one(self, **kw):
        base = dict(name="Skill Checkpoint Redo", date="2026-09-18",
                    due="2026-09-17T23:59:00", choose=3, limit="at most",
                    skills=("W1", "D1"))
        base.update(kw)
        return av.Availability(**base)

    def payload(self, script, **kw):
        return form.payload_for(
            self.one(**kw), connection(script),
            {"W1": "I can convert ancient numeration systems.",
             "D1": "I can identify place values."})

    def test_an_option_reads_slug_then_description(self, script):
        assert self.payload(script)["choices"][0] == \
            "W1 - I can convert ancient numeration systems."

    def test_a_skill_with_no_description_still_appears(self, script):
        p = form.payload_for(self.one(skills=("XX",)), connection(script), {})
        assert p["choices"] == ["XX"]

    def test_the_wording_is_the_form_s_own(self, script):
        p = self.payload(script)
        assert p["selecting_for"].startswith("You are selecting three skill(s)")
        assert p["confirm_date"] == \
            "I understand that I am selecting skills for Friday, 9/18."
        assert p["question_title"] == "Choose At Most THREE Skills"

    def test_the_question_help_names_the_day_not_the_date(self, script):
        """The script this replaces used the weekday there and the full date
        everywhere else, and the difference is visible to students."""
        assert self.payload(script)["question_help"] == \
            "You are choosing which skills you'll be redoing on Friday."

    @pytest.mark.parametrize("limit,mode", [
        ("at most", "at most"), ("at least", "at least"), ("exactly", "exactly"),
    ])
    def test_each_limiter_mode_crosses_the_wire(self, script, limit, mode):
        v = self.payload(script, limit=limit)["validation"]
        assert v["mode"] == mode and v["count"] == 3

    def test_choosing_zero_asks_for_no_particular_number(self, script):
        v = self.payload(script, choose=0)["validation"]
        assert v["mode"] == "any" and v["count"] == 0

    def test_nothing_open_makes_the_form_unsubmittable(self, script):
        """Inherited on purpose: a student who opens the form early must not
        be able to submit an empty choice that later reads as a real one."""
        p = self.payload(script, skills=())
        assert p["choices"] == [form.NOTHING_OPEN]
        assert p["validation"]["mode"] == "none"

    def test_only_the_mapped_items_are_named(self, script):
        """An unmapped slot means that part of the form is left alone."""
        conn = connection(script, items={"choose_skills": "33"})
        p = form.payload_for(self.one(), conn, {})
        assert list(p["items"]) == ["choose_skills"]


class TestConfigOnDisk:
    def test_the_secret_is_not_in_the_config(self, tmp_path):
        """form.toml goes in the course beside the roster. The URL and the
        secret are credentials -- anyone holding them can rewrite the form --
        so they live in secrets/ instead."""
        conn = form.Connection(url="https://script.google.com/x", secret="abc",
                               form_id="1FAIpQL", items={"choose_skills": "33"})
        config, secret_file = form.save(str(tmp_path), conn)
        text = open(config, encoding="utf-8").read()
        assert "abc" not in text and "script.google.com" not in text
        assert "secrets" in secret_file

    def test_it_round_trips(self, tmp_path):
        conn = form.Connection(url="https://x/exec", secret="abc",
                               form_id="1FAIpQL",
                               items={"choose_skills": "33",
                                      "confirm_date": "22"})
        form.save(str(tmp_path), conn)
        back = form.load(str(tmp_path))
        assert back.url == conn.url and back.secret == conn.secret
        assert back.items == conn.items and back.form_id == conn.form_id

    def test_an_empty_course_loads_as_unconfigured(self, tmp_path):
        conn = form.load(str(tmp_path))
        assert not conn.ready and conn.missing_slots() == list(form.SLOTS)

    def test_a_fresh_secret_is_long_and_different_every_time(self):
        a, b = form.new_secret(), form.new_secret()
        assert a != b and len(a) > 30

class TestRetrying:
    """Apps Script 404s a live deployment now and then.

    Measured: three identical calls to one deployment gave success, 404,
    success, while clasp listed it the whole time.
    """

    class Opener:
        """Fails the first `fail` calls the given way, then answers."""

        def __init__(self, fail, how, body='{"ok": true}'):
            self.left, self.how, self.body, self.calls = fail, how, body, 0

        def __call__(self, request, timeout=None):
            self.calls += 1
            if self.left > 0:
                self.left -= 1
                raise self.how()
            outer = self

            class R:
                def __enter__(self): return self
                def __exit__(self, *a): return False
                def read(self): return outer.body.encode()
            return R()

    def _404(self):
        return urllib.error.HTTPError("u", 404, "Not Found", {}, None)

    def _403(self):
        return urllib.error.HTTPError("u", 403, "Forbidden", {}, None)

    def _slow(self):
        return TimeoutError("timed out")

    def setup_method(self):
        form.RETRY_WAIT = 0          # no real sleeping in tests

    def test_a_single_404_is_retried_and_succeeds(self):
        op = self.Opener(1, self._404)
        answer = form.call(form.Connection(url="http://x/", secret="s"),
                           "ping", opener=op)
        assert answer["ok"] is True
        assert op.calls == 2

    def test_a_persistent_404_gives_up_and_says_how_often_it_tried(self):
        op = self.Opener(99, self._404)
        with pytest.raises(form.FormError, match="3 time"):
            form.call(form.Connection(url="http://x/", secret="s"),
                      "ping", opener=op, retries=2)
        assert op.calls == 3

    def test_a_403_is_never_retried(self):
        """A 403 is a real configuration problem. Retrying it only buries the
        sentence that explains it."""
        op = self.Opener(99, self._403)
        with pytest.raises(form.FormError, match="403"):
            form.call(form.Connection(url="http://x/", secret="s"),
                      "ping", opener=op)
        assert op.calls == 1

    def test_a_timeout_is_retried_too(self):
        """The first call after a deployment is the slow one."""
        op = self.Opener(1, self._slow)
        answer = form.call(form.Connection(url="http://x/", secret="s"),
                           "ping", opener=op)
        assert answer["ok"] is True
        assert op.calls == 2

    def test_a_persistent_timeout_is_a_sentence_not_a_traceback(self):
        """TimeoutError is an OSError but not a urllib.error.URLError, so it
        used to escape call() entirely."""
        op = self.Opener(99, self._slow)
        with pytest.raises(form.FormError, match="did not answer"):
            form.call(form.Connection(url="http://x/", secret="s"),
                      "ping", opener=op)
