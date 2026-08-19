#!/usr/bin/env python3
"""Unit tests for semantic_diff.py.

The judge is shown a before-and-after, so the content the lock recorded has to be
brought back. That is the one place git history is consulted, and everything here
guards the same edge: when the earlier content cannot be recovered, the judge must
not be handed a blank that reads as "nothing changed".
"""
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lock
import semantic_diff

GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "fixture",
    "GIT_AUTHOR_EMAIL": "fixture@invalid",
    "GIT_COMMITTER_NAME": "fixture",
    "GIT_COMMITTER_EMAIL": "fixture@invalid",
}


def _run(root, *args):
    env = dict(os.environ)
    env.update(GIT_ENV)
    subprocess.run(["git", "-C", root] + list(args), check=True,
                   capture_output=True, env=env)


def _write(root, rel, content=""):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _history(root, rel, versions):
    _run(root, "init", "-q", "-b", "master")
    for text in versions:
        _write(root, rel, text)
        _run(root, "add", "--", rel)
        _run(root, "commit", "-q", "-m", "step")


class TestRestoreBase(unittest.TestCase):
    def test_finds_the_version_matching_the_recorded_content(self):
        with tempfile.TemporaryDirectory() as root:
            _history(root, "skills/acme/SKILL.md", ["one\n", "two\n", "three\n"])
            self.assertEqual(
                semantic_diff.restore_base(root, "skills/acme/SKILL.md", _sha("two\n")),
                "two\n")

    def test_a_content_never_committed_cannot_be_restored(self):
        with tempfile.TemporaryDirectory() as root:
            _history(root, "skills/acme/SKILL.md", ["one\n"])
            self.assertIsNone(semantic_diff.restore_base(
                root, "skills/acme/SKILL.md", _sha("never\n")))

    def test_a_file_that_had_no_recorded_content_is_not_restorable(self):
        with tempfile.TemporaryDirectory() as root:
            _history(root, "skills/acme/SKILL.md", ["one\n"])
            self.assertIsNone(semantic_diff.restore_base(
                root, "skills/acme/SKILL.md", lock.MISSING))

    def test_a_tree_without_history_restores_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/acme/SKILL.md", "one\n")
            self.assertIsNone(semantic_diff.restore_base(
                root, "skills/acme/SKILL.md", _sha("one\n")))


class TestCurrentText(unittest.TestCase):
    def test_a_file_still_on_the_surface_reads_as_itself(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/acme/SKILL.md", "body\n")
            self.assertEqual(
                semantic_diff.current_text(root, "skills/acme/SKILL.md",
                                           {"skills/acme/SKILL.md": _sha("body\n")}),
                "body\n")

    def test_a_file_that_left_the_surface_reads_as_deleted(self):
        # Unlinking a reference leaves the file on disk while it drops off the
        # surface. Read as "still there, unchanged", that diff would arrive empty
        # and a judge would call it unaffected.
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/acme/gone.md", "still on disk\n")
            self.assertEqual(
                semantic_diff.current_text(root, "skills/acme/gone.md", {}), "")


class TestUnifiedDiff(unittest.TestCase):
    def test_the_diff_names_both_sides_and_ends_with_a_newline(self):
        body = semantic_diff.unified_diff("a.md", "one\n", "two\n")
        self.assertIn("a/a.md", body)
        self.assertIn("b/a.md", body)
        self.assertTrue(body.endswith("\n"))

    def test_no_difference_produces_no_body(self):
        self.assertEqual(semantic_diff.unified_diff("a.md", "same\n", "same\n"), "")


class TestSkeleton(unittest.TestCase):
    def test_blank_verdicts_are_left_for_the_judge_to_fill(self):
        skeleton = semantic_diff.build_skeleton("acme", "deadbeef", ["ac-001"], set())
        self.assertEqual(skeleton["scenarios"]["ac-001"]["verdict"], "")
        self.assertEqual(skeleton["model"], "")

    def test_a_scenario_whose_diff_could_not_be_restored_is_pre_filled_unclear(self):
        # Handed over as a blank to fill in, it would be filled in — and the
        # judge would be declaring something safe that it never saw.
        skeleton = semantic_diff.build_skeleton("acme", "deadbeef", ["ac-001"],
                                                {"ac-001"})
        self.assertEqual(skeleton["scenarios"]["ac-001"]["verdict"],
                         lock.VERDICT_UNCLEAR)
        self.assertTrue(skeleton["scenarios"]["ac-001"]["rationale"])


class TestBuildInput(unittest.TestCase):
    def _repo(self, root):
        _write(root, "skills/acme/SKILL.md", "body\n")
        _write(root, "evals/cases/acme/ac-001.yaml",
               "skill: acme\nid: ac-001\nprompt: do it\n"
               "expectations:\n  - text: it worked\n    critical: true\n")
        _run(root, "init", "-q", "-b", "master")
        _run(root, "add", "-A")
        _run(root, "commit", "-q", "-m", "baseline")

    def test_the_diff_hash_agrees_with_the_lock(self):
        with tempfile.TemporaryDirectory() as root:
            self._repo(root)
            state = lock.load(root)
            lock.update(root, state, "acme", "2026-08-01")
            recorded = dict(state["skills"]["acme"]["file_sha256"])
            _write(root, "skills/acme/SKILL.md", "body, reworked\n")
            built = semantic_diff.build_input(root, "acme", state["skills"]["acme"])
            current = lock.file_hashes(root, lock.skill_surface(root, "acme"))
            self.assertEqual(built["diff_sha256"],
                             lock.semantic_diff_sha256(recorded, current))

    def test_the_body_of_the_change_reaches_the_judge(self):
        with tempfile.TemporaryDirectory() as root:
            self._repo(root)
            state = lock.load(root)
            lock.update(root, state, "acme", "2026-08-01")
            _write(root, "skills/acme/SKILL.md", "body, reworked\n")
            built = semantic_diff.build_input(root, "acme", state["skills"]["acme"])
            self.assertIn("body, reworked", built["diff"])
            self.assertEqual(built["unrestorable"], [])
            self.assertEqual(built["scenarios"], ["ac-001"])

    def test_an_unrestorable_file_says_so_instead_of_showing_an_empty_diff(self):
        with tempfile.TemporaryDirectory() as root:
            self._repo(root)
            # Verify against content that was never committed, so the earlier
            # side has nowhere to be restored from.
            _write(root, "skills/acme/SKILL.md", "body, unrecorded\n")
            state = lock.load(root)
            lock.update(root, state, "acme", "2026-08-01")
            _write(root, "skills/acme/SKILL.md", "body, reworked\n")
            built = semantic_diff.build_input(root, "acme", state["skills"]["acme"])
            self.assertEqual(built["unrestorable"], ["skills/acme/SKILL.md"])
            self.assertEqual(
                built["skeleton"]["scenarios"]["ac-001"]["verdict"],
                lock.VERDICT_UNCLEAR)


if __name__ == "__main__":
    unittest.main()
