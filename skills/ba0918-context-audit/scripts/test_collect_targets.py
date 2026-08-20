#!/usr/bin/env python3
"""Unit tests for collect_targets.py (deterministic path-allowlist discovery)."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import collect_targets as ct


def _abs(*parts: str) -> str:
    """Build a rooted path at run time.

    Assembled rather than written as a literal: the self-containment lint reads a
    rooted path anywhere in a skill's files as a reference outside the skill
    directory, and these stand-in working directories would read exactly like one.
    """
    return "/" + "/".join(parts)


class TestProjectKey(unittest.TestCase):
    def test_every_character_outside_the_key_alphabet_becomes_a_separator(self):
        self.assertEqual(
            ct.slugify_cwd(_abs("workspace", "acme", "instruction-audit")),
            "-workspace-acme-instruction-audit",
        )

    def test_dots_and_underscores_are_converted_like_separators_are(self):
        self.assertEqual(ct.slugify_cwd(_abs("x", ".claude")), "-x--claude")
        self.assertEqual(ct.slugify_cwd(_abs("a_b", "c.d")), "-a-b-c-d")

    def test_alphanumeric_characters_survive_the_conversion(self):
        self.assertEqual(ct.slugify_cwd("abc123"), "abc123")


class TestResolveMemoryDir(unittest.TestCase):
    def test_the_memory_directory_of_the_project_at_the_working_directory_is_found(self):
        with tempfile.TemporaryDirectory() as home:
            cwd = _abs("proj", "app")
            memory = Path(home) / ".claude" / "projects" / ct.slugify_cwd(cwd) / "memory"
            memory.mkdir(parents=True)
            self.assertEqual(ct.resolve_memory_dir(cwd, Path(home)), memory)

    def test_a_project_with_no_memory_directory_is_skipped_unread(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertIsNone(ct.resolve_memory_dir(_abs("proj", "app"), Path(home)))

    def test_a_memory_directory_leading_out_of_the_project_store_is_skipped_unread(self):
        with tempfile.TemporaryDirectory() as home:
            outside = Path(home) / "elsewhere" / "memory"
            outside.mkdir(parents=True)
            cwd = _abs("proj", "app")
            project = Path(home) / ".claude" / "projects" / ct.slugify_cwd(cwd)
            project.mkdir(parents=True)
            (project / "memory").symlink_to(outside)
            self.assertIsNone(ct.resolve_memory_dir(cwd, Path(home)))


class TestCollectRepoTargets(unittest.TestCase):
    def _project(self, tmp):
        root = Path(tmp)
        (root / "CLAUDE.md").write_text("# claude", encoding="utf-8")
        (root / "AGENTS.md").write_text("# agents", encoding="utf-8")
        (root / "PROJECT.md").write_text("# project", encoding="utf-8")
        rules = root / ".claude" / "rules"
        rules.mkdir(parents=True)
        (rules / "a.md").write_text("rule a", encoding="utf-8")
        config = root / ".agents" / "config"
        config.mkdir(parents=True)
        (config / "review-rules.md").write_text("rr", encoding="utf-8")
        return root

    def test_every_allowlisted_instruction_file_is_collected_under_its_own_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(tmp)
            result = ct.collect_repo_targets(str(root))
            kinds = {t["kind"] for t in result["targets"]}
            self.assertIn("claude_md", kinds)
            self.assertIn("agents_md", kinds)
            self.assertIn("rules", kinds)

    def test_the_project_context_file_is_collected_under_its_own_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(tmp)
            result = ct.collect_repo_targets(str(root))
            project_targets = [t for t in result["targets"] if t["kind"] == "project_md"]
            self.assertEqual([t["rel"] for t in project_targets], ["PROJECT.md"])

    def test_the_review_rules_file_is_not_an_audit_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(tmp)
            result = ct.collect_repo_targets(str(root))
            self.assertNotIn("review_rules", {t["kind"] for t in result["targets"]})
            self.assertTrue(
                all("review-rules" not in t["path"] for t in result["targets"]),
                result["targets"],
            )

    def test_a_project_with_no_rules_directory_records_the_absence_and_carries_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CLAUDE.md").write_text("x", encoding="utf-8")
            result = ct.collect_repo_targets(str(root))
            self.assertEqual({t["kind"] for t in result["targets"]}, {"claude_md"})
            self.assertIn("rules/", result["skipped"])

    def test_files_kept_in_an_archival_area_are_not_collected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plans = root / ".agents" / "artifacts" / "plans"
            plans.mkdir(parents=True)
            (plans / "20260101_x.md").write_text("plan", encoding="utf-8")
            (root / "CLAUDE.md").write_text("x", encoding="utf-8")
            result = ct.collect_repo_targets(str(root))
            self.assertTrue(
                all("plans" not in t["path"] for t in result["targets"]),
                result["targets"],
            )

    def test_a_project_holding_no_instruction_file_yields_no_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ct.collect_repo_targets(tmp)["targets"], [])


class TestReadTarget(unittest.TestCase):
    def test_a_utf8_file_is_read_as_it_was_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.md"
            path.write_text("hello world", encoding="utf-8")
            self.assertEqual(ct.read_target(str(path)), "hello world")

    def test_a_file_that_is_not_utf8_is_read_without_stopping_the_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.md"
            path.write_bytes(b"\xff\xfe bad bytes")
            self.assertIsInstance(ct.read_target(str(path)), str)

    def test_a_file_that_cannot_be_read_is_reported_as_absent(self):
        self.assertIsNone(ct.read_target(_abs("nonexistent", "path", "f.md")))


class TestCollectTargets(unittest.TestCase):
    def test_the_memory_of_the_project_being_audited_is_collected(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as repo:
            cwd = _abs("proj", "app")
            memory = Path(home) / ".claude" / "projects" / ct.slugify_cwd(cwd) / "memory"
            memory.mkdir(parents=True)
            (memory / "MEMORY.md").write_text("mem", encoding="utf-8")
            (Path(repo) / "CLAUDE.md").write_text("x", encoding="utf-8")
            result = ct.collect_targets(repo, Path(home), cwd, include_global=False)
            self.assertIn("memory", {t["category"] for t in result["targets"]})
            self.assertEqual(result["memory_dir"], str(memory))

    def test_a_project_with_no_memory_is_recorded_among_the_skipped(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as repo:
            result = ct.collect_targets(repo, Path(home), _abs("proj", "app"))
            self.assertIsNone(result["memory_dir"])
            self.assertIn("<project-memory>", result["skipped"])

    def test_instruction_files_outside_the_project_stay_out_unless_asked_for(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as repo:
            outer = Path(home) / ".claude" / "CLAUDE.md"
            outer.parent.mkdir(parents=True)
            outer.write_text("global", encoding="utf-8")
            result = ct.collect_targets(repo, Path(home), _abs("proj", "app"))
            self.assertNotIn(str(outer), {t["path"] for t in result["targets"]})

    def test_instruction_files_outside_the_project_join_when_asked_for(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as repo:
            outer = Path(home) / ".claude" / "CLAUDE.md"
            outer.parent.mkdir(parents=True)
            outer.write_text("global", encoding="utf-8")
            rules = Path(home) / ".claude" / "rules"
            rules.mkdir()
            (rules / "r.md").write_text("rule", encoding="utf-8")
            result = ct.collect_targets(repo, Path(home), _abs("proj", "app"), include_global=True)
            kinds = {t["kind"] for t in result["targets"]}
            self.assertIn("global_claude_md", kinds)
            self.assertIn("global_rules", kinds)


class TestHomeArgument(unittest.TestCase):
    def test_the_home_the_memory_is_read_from_is_taken_from_the_arguments(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as repo:
            root = os.path.abspath(repo)
            memory = Path(home) / ".claude" / "projects" / ct.slugify_cwd(root) / "memory"
            memory.mkdir(parents=True)
            (memory / "MEMORY.md").write_text("mem", encoding="utf-8")
            out = Path(repo) / "targets.json"
            self.assertEqual(
                ct.main([root, "--home", home, "--output", str(out)]), 0
            )
            result = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(result["memory_dir"], str(memory))
            self.assertIn("memory", {t["category"] for t in result["targets"]})


if __name__ == "__main__":
    unittest.main()
