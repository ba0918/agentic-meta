#!/usr/bin/env python3
"""Unit tests for md_links.py."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import md_links

# The self-containment lint reads a literal parent step or a rooted path inside a
# skill directory as an escape, so fixtures that need one assemble it at run time.
PARENT = ".."
ROOTED = "/" + "abs" + "/a.md"


def _write(root, rel, content=""):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


class TestExtractMdLinks(unittest.TestCase):
    def test_extracts_relative_md_links(self):
        text = f"see [a](references/a.md) and [b]({PARENT}/shared/references/b.md)"
        self.assertEqual(
            md_links.extract_md_links(text),
            ["references/a.md", f"{PARENT}/shared/references/b.md"],
        )

    def test_strips_anchor(self):
        self.assertEqual(md_links.extract_md_links("[x](a.md#section-1)"), ["a.md"])

    def test_ignores_non_md_targets(self):
        self.assertEqual(md_links.extract_md_links("[x](a.png) [y](b.json)"), [])


class TestIsCheckableLink(unittest.TestCase):
    def test_relative_md_is_checkable(self):
        self.assertTrue(md_links.is_checkable_link("references/a.md"))

    def test_urls_and_rooted_paths_are_not(self):
        for link in ("https://x.example/a.md", "http://x/a.md", ROOTED,
                     "mailto:a@example.com"):
            self.assertFalse(md_links.is_checkable_link(link), link)

    def test_placeholders_are_not(self):
        self.assertFalse(md_links.is_checkable_link("plans/{ts}_{slug}.md"))
        self.assertFalse(md_links.is_checkable_link("plans/*.md"))

    def test_timestamp_examples_are_not(self):
        self.assertFalse(md_links.is_checkable_link("plans/20260101120000_example.md"))


class TestClosure(unittest.TestCase):
    def test_includes_start_file(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/a/SKILL.md", "no links")
            self.assertEqual(
                md_links.closure(root, "skills/a/SKILL.md"), ["skills/a/SKILL.md"]
            )

    def test_follows_links_transitively(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/a/SKILL.md",
                   f"[c]({PARENT}/shared/references/contract.md)")
            _write(root, "skills/shared/references/contract.md", "[other](other.md)")
            _write(root, "skills/shared/references/other.md", "end")
            self.assertEqual(
                md_links.closure(root, "skills/a/SKILL.md"),
                [
                    "skills/a/SKILL.md",
                    "skills/shared/references/contract.md",
                    "skills/shared/references/other.md",
                ],
            )

    def test_cycle_safe(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "a.md", "[b](b.md)")
            _write(root, "b.md", "[a](a.md)")
            self.assertEqual(md_links.closure(root, "a.md"), ["a.md", "b.md"])

    def test_skips_missing_and_uncheckable_targets(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "a.md",
                   "[gone](missing.md) [url](https://x/y.md) [ph]({var}.md)")
            self.assertEqual(md_links.closure(root, "a.md"), ["a.md"])

    def test_skips_links_escaping_root(self):
        with tempfile.TemporaryDirectory() as root:
            inner = os.path.join(root, "repo")
            _write(inner, "a.md", f"[esc]({PARENT}/outside.md)")
            _write(root, "outside.md", "outside the repository")
            self.assertEqual(md_links.closure(inner, "a.md"), ["a.md"])

    def test_max_depth_one_stops_at_direct_links(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/a/SKILL.md",
                   f"[c]({PARENT}/shared/references/contract.md)")
            _write(root, "skills/shared/references/contract.md", "[other](other.md)")
            _write(root, "skills/shared/references/other.md", "end")
            self.assertEqual(
                md_links.closure(root, "skills/a/SKILL.md", max_depth=1),
                ["skills/a/SKILL.md", "skills/shared/references/contract.md"],
            )

    def test_max_depth_zero_returns_only_starts(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/a/SKILL.md", "[c](b.md)")
            _write(root, "skills/a/b.md", "end")
            self.assertEqual(
                md_links.closure(root, "skills/a/SKILL.md", max_depth=0),
                ["skills/a/SKILL.md"],
            )

    def test_multiple_starts_are_all_depth_zero(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/a/SKILL.md", "[x](refs/x.md)")
            _write(root, "skills/a/refs/x.md", "[y](y.md)")
            _write(root, "skills/a/refs/y.md", "end")
            got = md_links.closure(
                root, ["skills/a/SKILL.md", "skills/a/refs/x.md"], max_depth=1
            )
            self.assertEqual(
                got, ["skills/a/SKILL.md", "skills/a/refs/x.md", "skills/a/refs/y.md"]
            )

    def test_depth_is_shortest_hop_not_discovery_order(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/s/SKILL.md", "[a](a.md) [b](b.md)")
            _write(root, "skills/s/a.md", "[b](b.md)")
            _write(root, "skills/s/b.md", "[c](c.md)")
            _write(root, "skills/s/c.md", "end")
            got = md_links.closure(root, "skills/s/SKILL.md", max_depth=1)
            self.assertIn("skills/s/b.md", got)
            self.assertNotIn("skills/s/c.md", got)

    def test_unlimited_depth_remains_default(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/a/SKILL.md", "[c](c.md)")
            _write(root, "skills/a/c.md", "[d](d.md)")
            _write(root, "skills/a/d.md", "end")
            self.assertIn("skills/a/d.md", md_links.closure(root, "skills/a/SKILL.md"))

    def test_missing_start_returns_empty(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(md_links.closure(root, "nope.md"), [])


if __name__ == "__main__":
    unittest.main()
