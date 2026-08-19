#!/usr/bin/env python3
"""Unit tests for collect_descriptions.py."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import collect_descriptions as cd


def _write_skill(root: Path, dirname: str, frontmatter: str, body: str = "body\n") -> Path:
    d = root / dirname
    d.mkdir(parents=True, exist_ok=True)
    p = d / "SKILL.md"
    p.write_text(frontmatter + body, encoding="utf-8")
    return p


def _fm(name: str | None, description: str | None) -> str:
    lines = ["---"]
    if name is not None:
        lines.append(f"name: {name}")
    if description is not None:
        lines.append(f"description: {description}")
    lines.append("---\n")
    return "\n".join(lines)


class TestParseFrontmatter(unittest.TestCase):
    def test_extracts_name_and_description(self):
        text = _fm("foo", "Does foo. 「foo」で起動")
        fm = cd.parse_frontmatter(text)
        self.assertEqual(fm["name"], "foo")
        self.assertEqual(fm["description"], "Does foo. 「foo」で起動")

    def test_missing_description_returns_empty(self):
        text = _fm("foo", None)
        fm = cd.parse_frontmatter(text)
        self.assertEqual(fm["name"], "foo")
        self.assertEqual(fm["description"], "")

    def test_no_frontmatter_returns_none(self):
        self.assertIsNone(cd.parse_frontmatter("no frontmatter here\n"))

    def test_multiline_description_joined(self):
        text = "---\nname: foo\ndescription: line one\n  line two\n---\n"
        fm = cd.parse_frontmatter(text)
        self.assertEqual(fm["description"], "line one line two")


class TestNormalizeBareName(unittest.TestCase):
    def test_strips_plugin_prefix(self):
        self.assertEqual(cd.normalize_bare_name("claude-skills:trigger-eval"), "trigger-eval")

    def test_no_prefix_unchanged(self):
        self.assertEqual(cd.normalize_bare_name("trigger-eval"), "trigger-eval")


class TestCollectFromDir(unittest.TestCase):
    def test_normal_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_skill(root, "alpha", _fm("alpha", "Alpha. 「a」で起動"))
            _write_skill(root, "beta", _fm("beta", "Beta. 「b」で起動"))
            skills = cd.collect_from_dir(root)
            names = {s["name"] for s in skills}
            self.assertEqual(names, {"alpha", "beta"})

    def test_missing_description_included_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_skill(root, "alpha", _fm("alpha", None))
            skills = cd.collect_from_dir(root)
            self.assertEqual(len(skills), 1)
            self.assertEqual(skills[0]["description"], "")

    def test_non_skill_md_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_skill(root, "alpha", _fm("alpha", "Alpha. 「a」で起動"))
            (root / "alpha" / "README.md").write_text("---\nname: readme\n---\n")
            (root / "alpha" / "references").mkdir()
            (root / "alpha" / "references" / "guide.md").write_text("x")
            skills = cd.collect_from_dir(root)
            self.assertEqual([s["name"] for s in skills], ["alpha"])

    def test_plugin_prefix_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_skill(root, "alpha", _fm("claude-skills:alpha", "Alpha. 「a」で起動"))
            skills = cd.collect_from_dir(root)
            self.assertEqual(skills[0]["name"], "alpha")

    def test_bare_name_duplicate_fail_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_skill(root, "alpha", _fm("claude-skills:dup", "A. 「a」で起動"))
            _write_skill(root, "beta", _fm("wiki:dup", "B. 「b」で起動"))
            with self.assertRaises(cd.DuplicateSkillError):
                cd.collect_from_dir(root)

    def test_symlink_dir_not_followed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_skill(root, "alpha", _fm("alpha", "Alpha. 「a」で起動"))
            target = root / "alpha"
            link = root / "linked"
            try:
                os.symlink(target, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlink not supported")
            skills = cd.collect_from_dir(root)
            self.assertEqual([s["name"] for s in skills], ["alpha"])

    def test_symlinked_skill_md_not_followed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_skill(root, "alpha", _fm("alpha", "Alpha. 「a」で起動"))
            d = root / "beta"
            d.mkdir()
            try:
                os.symlink(root / "alpha" / "SKILL.md", d / "SKILL.md")
            except (OSError, NotImplementedError):
                self.skipTest("symlink not supported")
            skills = cd.collect_from_dir(root)
            self.assertEqual([s["name"] for s in skills], ["alpha"])

    def test_name_falls_back_to_dirname(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_skill(root, "alpha", _fm(None, "Alpha. 「a」で起動"))
            skills = cd.collect_from_dir(root)
            self.assertEqual(skills[0]["name"], "alpha")


class TestBuildResult(unittest.TestCase):
    def test_result_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_skill(root, "alpha", _fm("alpha", "Alpha. 「a」で起動"))
            result = cd.build_result(root)
            self.assertIn("skills", result)
            self.assertIn("count", result)
            self.assertEqual(result["count"], 1)
            # JSON serializable
            json.dumps(result)


if __name__ == "__main__":
    unittest.main()
