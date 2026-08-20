#!/usr/bin/env python3
"""Unit tests for apply_fixes.py (applying the fixes a check decided are automatic)."""

import importlib.util
import os
import unittest


def _load(module_name: str, filename: str):
    """Load a script sitting beside this file under a name unique to this skill.

    Not a plain `import` of the basename: another skill in this repository carries a
    script of the same name, and one test session keeps only the first module bound to
    a given name, so the plain form would hand one skill's tests the other skill's
    module. Loading from the file path lets each skill name its own copy.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


af = _load("ba0918_context_audit_apply_fixes", "apply_fixes.py")


def reference_fix(path, old, new):
    return {"id": "CA-S001", "action": "AUTO_FIX",
            "fix_action": {"path": path, "old": old, "new": new}}


def frontmatter_fix(path, old, new):
    return {"id": "CA-M001", "action": "AUTO_FIX",
            "fix_action": {"path": path, "old": old, "new": new}}


class TestReferenceReplacement(unittest.TestCase):
    def test_a_reference_written_as_a_link_is_replaced(self):
        content = "see [foo](references/foow.md) end"
        out = af.apply_fixes(
            content, [reference_fix("f.md", "references/foow.md", "references/foo.md")])
        self.assertIn("(references/foo.md)", out)
        self.assertNotIn("foow.md", out)

    def test_a_reference_written_inside_a_code_span_is_replaced(self):
        content = "the `references/foow.md` file"
        out = af.apply_fixes(
            content, [reference_fix("f.md", "references/foow.md", "references/foo.md")])
        self.assertIn("`references/foo.md`", out)

    def test_replacing_a_reference_a_second_time_changes_nothing_further(self):
        content = "see [foo](references/foow.md) end"
        fixes = [reference_fix("f.md", "references/foow.md", "references/foo.md")]
        once = af.apply_fixes(content, fixes)
        self.assertEqual(af.apply_fixes(once, fixes), once)

    def test_several_fixes_are_applied_in_one_pass(self):
        content = "[a](references/foow.md) and `references/barr.md`"
        out = af.apply_fixes(content, [
            reference_fix("f.md", "references/foow.md", "references/foo.md"),
            reference_fix("f.md", "references/barr.md", "references/bar.md"),
        ])
        self.assertIn("references/foo.md", out)
        self.assertIn("references/bar.md", out)


class TestFrontmatterNormalisation(unittest.TestCase):
    def test_a_key_written_without_the_canonical_spacing_is_normalised(self):
        content = "---\nname:note\ndescription: d\n---\nbody text"
        out = af.apply_fixes(content, [frontmatter_fix("n.md", "name:note", "name: note")])
        self.assertIn("name: note", out)

    def test_normalising_a_key_leaves_every_byte_of_the_body_as_it_was(self):
        content = "---\nname:note\ndescription: d\n---\nbody `name:note` text"
        out = af.apply_fixes(content, [frontmatter_fix("n.md", "name:note", "name: note")])
        self.assertEqual(content.split("---", 2)[2], out.split("---", 2)[2])

    def test_normalising_a_key_a_second_time_changes_nothing_further(self):
        content = "---\nname:note\ndescription: d\n---\nbody"
        fixes = [frontmatter_fix("n.md", "name:note", "name: note")]
        once = af.apply_fixes(content, fixes)
        self.assertEqual(af.apply_fixes(once, fixes), once)

    def test_a_file_whose_lines_end_in_carriage_returns_keeps_those_endings(self):
        content = "---\r\nname:note\r\ndescription: d\r\n---\r\nbody"
        out = af.apply_fixes(content, [frontmatter_fix("n.md", "name:note", "name: note")])
        self.assertIn("name: note\r\n", out)
        self.assertTrue(out.endswith("body"))

    def test_a_file_with_no_closed_frontmatter_block_is_left_alone(self):
        content = "name:note\nbody"
        out = af.apply_fixes(content, [frontmatter_fix("n.md", "name:note", "name: note")])
        self.assertEqual(out, content)


class TestWhatIsLeftUntouched(unittest.TestCase):
    def test_a_finding_left_to_a_human_changes_nothing(self):
        content = "see [x](nope/gone.md) end"
        finding = {"id": "CA-S001", "action": "NEEDS_JUDGMENT", "fix_action": None}
        self.assertEqual(af.apply_fixes(content, [finding]), content)

    def test_a_finding_that_only_reports_changes_nothing(self):
        content = "some content"
        finding = {"id": "CA-U001", "action": "REPORT_ONLY", "fix_action": None}
        self.assertEqual(af.apply_fixes(content, [finding]), content)

    def test_a_fix_whose_replacement_equals_the_original_changes_nothing(self):
        content = "see [foo](references/foo.md) end"
        out = af.apply_fixes(
            content, [reference_fix("f.md", "references/foo.md", "references/foo.md")])
        self.assertEqual(out, content)


class TestGroupingByFile(unittest.TestCase):
    def test_automatic_fixes_are_grouped_under_the_file_they_open(self):
        groups = af.group_by_path([
            reference_fix("a.md", "x/1.md", "x/2.md"),
            reference_fix("a.md", "x/3.md", "x/4.md"),
            reference_fix("b.md", "x/5.md", "x/6.md"),
        ])
        self.assertEqual(sorted(groups), ["a.md", "b.md"])
        self.assertEqual(len(groups["a.md"]), 2)

    def test_a_finding_offering_no_automatic_fix_is_not_grouped(self):
        groups = af.group_by_path([
            {"id": "CA-U001", "action": "REPORT_ONLY", "fix_action": None},
        ])
        self.assertEqual(groups, {})


if __name__ == "__main__":
    unittest.main()
