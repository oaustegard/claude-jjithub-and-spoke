"""Tests for ghi.

Run: python3 -m pytest tests/ -q     (or)     python3 tests/test_ghi.py

No third-party deps required when run as `python3 tests/test_ghi.py` — falls
back to unittest if pytest isn't installed.

Live integration tests (LiveAuthStatusTests, LiveIssueRoundTripTests) are
gated on $GH_TOKEN and $GHI_TEST_REPO. To run them end-to-end against a
sacrificial public repo, set:

    GH_TOKEN=ghp_...        (a classic PAT with `repo` scope)
    GHI_TEST_REPO=oaustegard/ghi-test

Otherwise the live tests skip themselves and only the unit + parser
tests run.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent


def _load_ghi():
    # ghi has no .py extension, so we must pass an explicit SourceFileLoader.
    path = str(ROOT / "bin" / "ghi")
    loader = importlib.machinery.SourceFileLoader("ghi", path)
    spec = importlib.util.spec_from_loader("ghi", loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ghi"] = mod
    loader.exec_module(mod)
    return mod


ghi = _load_ghi()


# ─── Pure unit tests ─────────────────────────────────────────────────────────

class SplitRepoTests(unittest.TestCase):
    def test_owner_and_name(self):
        self.assertEqual(ghi._split_repo("foo/bar"), ("foo", "bar"))

    def test_rejects_bare(self):
        with self.assertRaises(SystemExit):
            ghi._split_repo("nope")

    def test_keeps_slashes_after_first(self):
        # GitHub repo names can't contain slashes, but splitting on first /
        # is the right behavior in case someone passes an unexpected value.
        self.assertEqual(ghi._split_repo("a/b/c"), ("a", "b/c"))


class SplitCsvTests(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(ghi._split_csv("a,b,c"), ["a", "b", "c"])

    def test_strips_whitespace(self):
        self.assertEqual(ghi._split_csv(" a , b ,c "), ["a", "b", "c"])

    def test_drops_empties(self):
        self.assertEqual(ghi._split_csv("a,,b,"), ["a", "b"])

    def test_none(self):
        self.assertEqual(ghi._split_csv(None), [])

    def test_empty(self):
        self.assertEqual(ghi._split_csv(""), [])


class FormatIssueLineTests(unittest.TestCase):
    def test_no_labels(self):
        line = ghi._format_issue_line({
            "number": 1, "title": "Hi", "state": "open",
            "user": {"login": "alice"}, "labels": [],
            "html_url": "https://github.com/o/r/issues/1",
        })
        self.assertIn("#1", line)
        self.assertIn("open", line)
        self.assertIn("Hi", line)
        self.assertIn("by alice", line)
        self.assertIn("labels: (none)", line)

    def test_with_labels(self):
        line = ghi._format_issue_line({
            "number": 7, "title": "Bug", "state": "closed",
            "user": {"login": "bob"},
            "labels": [{"name": "bug"}, {"name": "p1"}],
            "html_url": "https://github.com/o/r/issues/7",
        })
        self.assertIn("labels: bug,p1", line)


# ─── _request: header + payload contract ────────────────────────────────────

class RequestHeadersTests(unittest.TestCase):
    """Every API call must carry UA + token + Accept. GitHub returns 401
    without User-Agent before it returns 401 for a bad token — see memory
    e4a22d24 and the github-procedures doc."""

    def _capture(self, *, method="GET", path="/user", body=None, env=None):
        seen: dict = {}
        env = env if env is not None else {"GH_TOKEN": "ghp_test"}

        class FakeResp:
            def __init__(self, payload=b'{"ok":true}'):
                self._payload = payload

            def read(self):
                return self._payload

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["headers"] = {k.lower(): v for k, v in req.header_items()}
            seen["data"] = req.data
            return FakeResp()

        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(ghi.urllib.request, "urlopen",
                               side_effect=fake_urlopen):
            ghi._request(method, path, body=body)
        return seen

    def test_mandatory_headers_present(self):
        seen = self._capture()
        self.assertTrue(seen["headers"]["user-agent"].startswith("ghi/"))
        self.assertEqual(seen["headers"]["authorization"], "token ghp_test")
        self.assertEqual(seen["headers"]["accept"],
                         "application/vnd.github+json")
        self.assertEqual(seen["url"], "https://api.github.com/user")
        self.assertEqual(seen["method"], "GET")

    def test_body_sets_content_type_and_payload(self):
        seen = self._capture(method="POST", path="/repos/o/r/issues",
                             body={"title": "x"})
        self.assertEqual(seen["headers"]["content-type"], "application/json")
        self.assertEqual(json.loads(seen["data"]), {"title": "x"})

    def test_no_body_no_content_type(self):
        seen = self._capture(method="GET", path="/user", body=None)
        self.assertNotIn("content-type", seen["headers"])
        self.assertIsNone(seen["data"])

    def test_no_token_exits(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             self.assertRaises(SystemExit):
            ghi._request("GET", "/user")


# ─── Command logic, fully mocked ────────────────────────────────────────────

class IssueListMockTests(unittest.TestCase):
    def test_filters_out_pull_requests(self):
        fake = [
            {"number": 1, "title": "Issue 1", "state": "open",
             "user": {"login": "alice"}, "labels": [],
             "html_url": "https://github.com/o/r/issues/1"},
            {"number": 2, "title": "PR 2", "state": "open",
             "user": {"login": "bob"}, "labels": [],
             "html_url": "https://github.com/o/r/pull/2",
             "pull_request": {"url": "..."}},
            {"number": 3, "title": "Issue 3", "state": "open",
             "user": {"login": "carol"}, "labels": [{"name": "bug"}],
             "html_url": "https://github.com/o/r/issues/3"},
        ]
        with mock.patch.object(ghi, "_request", return_value=fake), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            ghi.cmd_issue_list(argparse.Namespace(
                repo="o/r", state="open", label=None, author=None,
                limit=30, json=False))
        text = out.getvalue()
        self.assertIn("Issue 1", text)
        self.assertNotIn("PR 2", text)
        self.assertIn("Issue 3", text)

    def test_passes_label_and_author_params(self):
        captured: dict = {}

        def fake_request(method, path, *, params=None, body=None):
            captured["params"] = params
            return []

        with mock.patch.object(ghi, "_request", side_effect=fake_request), \
             contextlib.redirect_stdout(io.StringIO()):
            ghi.cmd_issue_list(argparse.Namespace(
                repo="o/r", state="closed", label="bug,enhancement",
                author="alice", limit=10, json=False))
        self.assertEqual(captured["params"]["labels"], "bug,enhancement")
        self.assertEqual(captured["params"]["creator"], "alice")
        self.assertEqual(captured["params"]["state"], "closed")
        self.assertEqual(captured["params"]["per_page"], 10)

    def test_json_output_is_filtered_array(self):
        fake = [
            {"number": 1, "title": "I", "state": "open",
             "user": {"login": "a"}, "labels": [],
             "html_url": "https://x/1"},
            {"number": 2, "title": "P", "state": "open",
             "user": {"login": "b"}, "labels": [],
             "html_url": "https://x/2",
             "pull_request": {"url": "..."}},
        ]
        with mock.patch.object(ghi, "_request", return_value=fake), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            ghi.cmd_issue_list(argparse.Namespace(
                repo="o/r", state="open", label=None, author=None,
                limit=30, json=True))
        items = json.loads(out.getvalue())
        self.assertEqual([i["number"] for i in items], [1])


class IssueCreateMockTests(unittest.TestCase):
    def test_packs_full_payload(self):
        captured: dict = {}

        def fake_request(method, path, *, params=None, body=None):
            captured.update(method=method, path=path, body=body)
            return {"number": 7, "html_url": "https://x/7"}

        with mock.patch.object(ghi, "_request", side_effect=fake_request), \
             mock.patch.object(sys.stdin, "isatty", return_value=True), \
             contextlib.redirect_stdout(io.StringIO()):
            ghi.cmd_issue_create(argparse.Namespace(
                repo="foo/bar", title="x", body="b", label="a,b",
                assignee="alice"))
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["path"], "/repos/foo/bar/issues")
        self.assertEqual(captured["body"]["title"], "x")
        self.assertEqual(captured["body"]["body"], "b")
        self.assertEqual(captured["body"]["labels"], ["a", "b"])
        self.assertEqual(captured["body"]["assignees"], ["alice"])

    def test_omits_optional_fields_when_unset(self):
        captured: dict = {}

        def fake_request(method, path, *, params=None, body=None):
            captured["body"] = body
            return {"number": 7, "html_url": "https://x/7"}

        with mock.patch.object(ghi, "_request", side_effect=fake_request), \
             mock.patch.object(sys.stdin, "isatty", return_value=True), \
             contextlib.redirect_stdout(io.StringIO()):
            ghi.cmd_issue_create(argparse.Namespace(
                repo="foo/bar", title="only-title", body=None,
                label=None, assignee=None))
        self.assertEqual(captured["body"], {"title": "only-title"})


class IssueCloseMockTests(unittest.TestCase):
    def test_sets_state_and_reason(self):
        captured: dict = {}

        def fake_request(method, path, *, params=None, body=None):
            captured.update(method=method, path=path, body=body)
            return {"number": 1, "html_url": "https://x/1"}

        with mock.patch.object(ghi, "_request", side_effect=fake_request), \
             contextlib.redirect_stdout(io.StringIO()):
            ghi.cmd_issue_close(argparse.Namespace(
                repo="o/r", number=1, reason="not_planned"))
        self.assertEqual(captured["method"], "PATCH")
        self.assertEqual(captured["path"], "/repos/o/r/issues/1")
        self.assertEqual(captured["body"]["state"], "closed")
        self.assertEqual(captured["body"]["state_reason"], "not_planned")

    def test_omits_reason_when_absent(self):
        captured: dict = {}

        def fake_request(method, path, *, params=None, body=None):
            captured["body"] = body
            return {"number": 1, "html_url": "https://x/1"}

        with mock.patch.object(ghi, "_request", side_effect=fake_request), \
             contextlib.redirect_stdout(io.StringIO()):
            ghi.cmd_issue_close(argparse.Namespace(
                repo="o/r", number=1, reason=None))
        self.assertEqual(captured["body"], {"state": "closed"})


class IssueReopenMockTests(unittest.TestCase):
    def test_sets_state_open_and_reopen_reason(self):
        captured: dict = {}

        def fake_request(method, path, *, params=None, body=None):
            captured.update(method=method, body=body)
            return {"number": 1, "html_url": "https://x/1"}

        with mock.patch.object(ghi, "_request", side_effect=fake_request), \
             contextlib.redirect_stdout(io.StringIO()):
            ghi.cmd_issue_reopen(argparse.Namespace(repo="o/r", number=1))
        self.assertEqual(captured["method"], "PATCH")
        self.assertEqual(captured["body"]["state"], "open")
        self.assertEqual(captured["body"]["state_reason"], "reopened")


class IssueEditMockTests(unittest.TestCase):
    def test_partial_edit_only_patches_provided_fields(self):
        calls: list = []

        def fake_request(method, path, *, params=None, body=None):
            calls.append((method, path, body))
            if method == "PATCH":
                return {"number": 1, "html_url": "https://x/1"}
            return {}

        with mock.patch.object(ghi, "_request", side_effect=fake_request), \
             contextlib.redirect_stdout(io.StringIO()):
            ghi.cmd_issue_edit(argparse.Namespace(
                repo="o/r", number=1, title="new", body=None,
                add_label=None, remove_label=None))
        patches = [c for c in calls if c[0] == "PATCH"]
        self.assertEqual(len(patches), 1)
        self.assertEqual(patches[0][2], {"title": "new"})

    def test_add_label_uses_dedicated_endpoint(self):
        calls: list = []

        def fake_request(method, path, *, params=None, body=None):
            calls.append((method, path, body))
            if path == "/repos/o/r/issues/1" and method == "GET":
                return {"number": 1, "html_url": "https://x/1"}
            return {}

        with mock.patch.object(ghi, "_request", side_effect=fake_request), \
             contextlib.redirect_stdout(io.StringIO()):
            ghi.cmd_issue_edit(argparse.Namespace(
                repo="o/r", number=1, title=None, body=None,
                add_label="bug,p1", remove_label=None))
        adds = [c for c in calls
                if c[0] == "POST" and c[1].endswith("/labels")]
        self.assertEqual(len(adds), 1)
        self.assertEqual(adds[0][2], {"labels": ["bug", "p1"]})

    def test_remove_label_tolerates_404(self):
        calls: list = []

        def fake_request(method, path, *, params=None, body=None):
            calls.append((method, path))
            if method == "DELETE":
                raise ghi.GHError(404, "label not found")
            if method == "GET":
                return {"number": 1, "html_url": "https://x/1"}
            return {}

        with mock.patch.object(ghi, "_request", side_effect=fake_request), \
             contextlib.redirect_stdout(io.StringIO()):
            # Should NOT raise even though DELETE returns 404
            ghi.cmd_issue_edit(argparse.Namespace(
                repo="o/r", number=1, title=None, body=None,
                add_label=None, remove_label="missing"))
        deletes = [c for c in calls if c[0] == "DELETE"]
        self.assertEqual(len(deletes), 1)


class IssueCommentMockTests(unittest.TestCase):
    def test_requires_body(self):
        with mock.patch.object(sys.stdin, "isatty", return_value=True), \
             self.assertRaises(SystemExit):
            ghi.cmd_issue_comment(argparse.Namespace(
                repo="o/r", number=1, body=None))

    def test_posts_body(self):
        captured: dict = {}

        def fake_request(method, path, *, params=None, body=None):
            captured.update(method=method, path=path, body=body)
            return {"html_url": "https://x/c"}

        with mock.patch.object(ghi, "_request", side_effect=fake_request), \
             contextlib.redirect_stdout(io.StringIO()):
            ghi.cmd_issue_comment(argparse.Namespace(
                repo="o/r", number=1, body="hi"))
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["path"], "/repos/o/r/issues/1/comments")
        self.assertEqual(captured["body"], {"body": "hi"})


class AuthStatusMockTests(unittest.TestCase):
    def test_prints_login_first_line(self):
        with mock.patch.object(ghi, "_request",
                               return_value={"login": "octocat", "id": 1,
                                             "html_url": "https://x/u"}), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            ghi.cmd_auth_status(argparse.Namespace())
        first_line = out.getvalue().splitlines()[0]
        # boot.sh's sanity probe parses this with `awk '{print $NF}'` — so
        # the login MUST be the last whitespace-separated token on line 1.
        self.assertEqual(first_line, "Logged in as octocat")
        self.assertEqual(first_line.split()[-1], "octocat")


# ─── argparse surface ────────────────────────────────────────────────────────

class ParserSmokeTests(unittest.TestCase):
    """The CLI surface must parse without exceptions."""

    def test_all_subcommand_help(self):
        parser = ghi.build_parser()
        sink = io.StringIO()
        for argv in [
            ["auth", "status", "--help"],
            ["issue", "list", "--help"],
            ["issue", "view", "--help"],
            ["issue", "create", "--help"],
            ["issue", "comment", "--help"],
            ["issue", "close", "--help"],
            ["issue", "reopen", "--help"],
            ["issue", "edit", "--help"],
        ]:
            with self.subTest(argv=argv), \
                 contextlib.redirect_stdout(sink), \
                 contextlib.redirect_stderr(sink), \
                 self.assertRaises(SystemExit) as cm:
                parser.parse_args(argv)
            self.assertEqual(cm.exception.code, 0,
                             f"{argv} → {cm.exception.code}")

    def test_missing_repo_errors(self):
        parser = ghi.build_parser()
        sink = io.StringIO()
        with contextlib.redirect_stderr(sink), \
             self.assertRaises(SystemExit):
            parser.parse_args(["issue", "list"])


# ─── Live integration (gated on env) ────────────────────────────────────────

def _run_ghi(*args, input_=None, timeout=30):
    """Invoke `python3 bin/ghi <args>` as a subprocess. Inherits env."""
    return subprocess.run(
        [sys.executable, str(ROOT / "bin" / "ghi"), *args],
        input=input_, capture_output=True, text=True,
        env={**os.environ}, timeout=timeout,
    )


def _need_token(test):
    if not os.environ.get("GH_TOKEN"):
        test.skipTest("GH_TOKEN not set")


def _need_repo(test):
    if not os.environ.get("GHI_TEST_REPO"):
        test.skipTest("GHI_TEST_REPO not set (e.g. oaustegard/ghi-test)")


class LiveAuthStatusTests(unittest.TestCase):
    def setUp(self):
        _need_token(self)

    def test_returns_login(self):
        r = _run_ghi("auth", "status")
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr}")
        self.assertIn("Logged in as", r.stdout)
        # Boot probe contract: awk '{print $NF}' on line 1 == login.
        first = r.stdout.splitlines()[0]
        self.assertTrue(first.startswith("Logged in as "))
        self.assertTrue(first.split()[-1])  # non-empty login


class LiveIssueRoundTripTests(unittest.TestCase):
    """End-to-end happy path on a sacrificial repo: create → comment →
    view → edit (label) → close. Cleans up its own issue at the end."""

    def setUp(self):
        _need_token(self)
        _need_repo(self)
        self.repo = os.environ["GHI_TEST_REPO"]
        self.numbers_to_clean: list[int] = []

    def tearDown(self):
        for n in self.numbers_to_clean:
            try:
                _run_ghi("issue", "close", "--repo", self.repo, str(n),
                         "--reason", "not_planned")
            except Exception:
                pass

    @staticmethod
    def _last_created_number(r: subprocess.CompletedProcess) -> int:
        # "Created #42: https://..."
        first = r.stdout.strip().splitlines()[0]
        return int(first.split("#", 1)[1].split(":", 1)[0])

    def test_full_round_trip(self):
        title = f"ghi smoke test {os.getpid()}"

        r = _run_ghi("issue", "create", "--repo", self.repo,
                     "--title", title, "--body", "auto-created by tests")
        self.assertEqual(r.returncode, 0, r.stderr)
        number = self._last_created_number(r)
        self.numbers_to_clean.append(number)

        r = _run_ghi("issue", "comment", "--repo", self.repo, str(number),
                     "--body", "test comment from ghi")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"#{number}", r.stdout)

        r = _run_ghi("issue", "view", "--repo", self.repo, str(number),
                     "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        payload = json.loads(r.stdout)
        self.assertEqual(payload["issue"]["title"], title)
        self.assertGreaterEqual(len(payload["comments"]), 1)

        r = _run_ghi("issue", "close", "--repo", self.repo, str(number),
                     "--reason", "completed")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.numbers_to_clean.remove(number)

    def test_list_excludes_prs(self):
        r = _run_ghi("issue", "list", "--repo", self.repo,
                     "--state", "all", "--limit", "20", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        items = json.loads(r.stdout)
        for i in items:
            self.assertNotIn("pull_request", i,
                             f"PR leaked into issue list: #{i.get('number')}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
