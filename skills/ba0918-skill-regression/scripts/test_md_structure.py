#!/usr/bin/env python3
"""Unit tests for md_structure.py.

The structural fingerprint is what a prose-only judgment rests on. Its error
directions are asymmetric: mistaking a prose change for a structural one only
falls to the heavy side and stays safe, while mistaking a structural change for
prose puts an unverified behaviour change on the light approval rail. These
tests are weighted toward closing the second hole.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import md_structure


def _fp(text):
    return md_structure.structural_fingerprint(text)


class TestProseOnlyChangesKeepFingerprint(unittest.TestCase):
    """An edit confined to prose leaves the fingerprint alone."""

    def test_prose_rewording(self):
        before = "# Title\n\nThis is the old wording of the paragraph.\n"
        after = "# Title\n\nThis paragraph was reworded entirely.\n"
        self.assertEqual(_fp(before), _fp(after))

    def test_prose_added_outside_fence(self):
        before = "# Title\n\n```sh\nrun me\n```\n"
        after = "# Title\n\nA new explanatory sentence.\n\n```sh\nrun me\n```\n"
        self.assertEqual(_fp(before), _fp(after))

    def test_prose_around_structural_lines(self):
        before = "# T\n\nOld explanation here.\n\n```sh\nrun\n```\n"
        after = "# T\n\nA better explanation.\n\n```sh\nrun\n```\n"
        self.assertEqual(_fp(before), _fp(after))


class TestStructuralChangesBreakFingerprint(unittest.TestCase):
    """One changed machine-parsed token changes the fingerprint."""

    def test_frontmatter_change(self):
        self.assertNotEqual(_fp("---\nname: a\n---\nbody\n"),
                            _fp("---\nname: b\n---\nbody\n"))

    def test_fence_content_change(self):
        self.assertNotEqual(_fp("intro\n\n```sh\necho one\n```\n"),
                            _fp("intro\n\n```sh\necho two\n```\n"))

    def test_fence_added(self):
        self.assertNotEqual(_fp("intro\n"), _fp("intro\n\n```sh\necho new\n```\n"))

    def test_tilde_fence_content_change(self):
        self.assertNotEqual(_fp("~~~\nold\n~~~\n"), _fp("~~~\nnew\n~~~\n"))

    def test_inline_code_change(self):
        self.assertNotEqual(_fp("run `lock.py --check` first\n"),
                            _fp("run `lock.py --status` first\n"))

    def test_link_target_change(self):
        self.assertNotEqual(_fp("see [label](refs/old.md)\n"),
                            _fp("see [label](refs/new.md)\n"))

    def test_reference_definition_change(self):
        self.assertNotEqual(_fp("[contract]: refs/old.md\n"),
                            _fp("[contract]: refs/new.md\n"))

    def test_table_row_change(self):
        # Cell prose included: a table is tokenised whole, on the heavy side.
        self.assertNotEqual(_fp("| a | old cell |\n|---|---|\n"),
                            _fp("| a | new cell |\n|---|---|\n"))

    def test_heading_change(self):
        # Headings are cited as step names by workflows, so they are tokens.
        self.assertNotEqual(_fp("## Step 1: Gather\n\nprose\n"),
                            _fp("## Step 1: Collect\n\nprose\n"))

    def test_indented_code_block_change(self):
        self.assertNotEqual(_fp("para\n\n    old command\n"),
                            _fp("para\n\n    new command\n"))

    def test_token_reorder(self):
        # The same token set in a different order is a different sequence.
        self.assertNotEqual(_fp("```sh\none\n```\n\n```sh\ntwo\n```\n"),
                            _fp("```sh\ntwo\n```\n\n```sh\none\n```\n"))


class TestAdversarialFalseNegatives(unittest.TestCase):
    """Collisions a deny-list implementation was shown to produce.

    Each is an edit that changes behaviour while leaving the fingerprint
    untouched. The allow-list reading has to separate every one of them.
    """

    def test_list_item_instruction_change(self):
        self.assertNotEqual(_fp("1. Delete cache.\n"), _fp("1. Delete database.\n"))

    def test_unordered_list_item_change(self):
        self.assertNotEqual(_fp("- run the linter\n"), _fp("- skip the linter\n"))

    def test_setext_heading_change(self):
        self.assertNotEqual(_fp("Step One\n--------\n"), _fp("Step Two\n--------\n"))

    def test_table_without_leading_pipe(self):
        self.assertNotEqual(_fp("run | safe\n"), _fp("run | destructive\n"))

    def test_tab_indented_code_change(self):
        self.assertNotEqual(_fp("\tcommand old\n"), _fp("\tcommand new\n"))

    def test_html_tag_content_change(self):
        self.assertNotEqual(_fp("<agent-rule>allow</agent-rule>\n"),
                            _fp("<agent-rule>deny</agent-rule>\n"))

    def test_reference_link_label_change(self):
        # Both definitions stay; swapping the label changes what resolves.
        before = "see [policy][old]\n\n[old]: refs/a.md\n[new]: refs/b.md\n"
        after = "see [policy][new]\n\n[old]: refs/a.md\n[new]: refs/b.md\n"
        self.assertNotEqual(_fp(before), _fp(after))

    def test_link_destination_with_parentheses(self):
        self.assertNotEqual(_fp("see [x](dir/(stable)old.md)\n"),
                            _fp("see [x](dir/(stable)new.md)\n"))

    def test_multi_backtick_inline_code_change(self):
        self.assertNotEqual(_fp("use ``foo ` old`` now\n"),
                            _fp("use ``foo ` new`` now\n"))

    def test_inner_shorter_fence_is_not_a_closer(self):
        # Reading the inner ``` as a closer would drop everything after it.
        self.assertNotEqual(_fp("````md\n```\ninner old\n```\n````\n"),
                            _fp("````md\n```\ninner new\n```\n````\n"))

    def test_blockquote_change(self):
        self.assertNotEqual(_fp("> do the safe thing\n"),
                            _fp("> do the risky thing\n"))

    def test_link_text_change_is_structural_by_fail_safe(self):
        # A shortcut reference cannot be told apart from plain brackets, so the
        # whole line falls to the heavy side.
        before = "See [the old label](refs/contract.md) for details.\n"
        after = "Read [a new label](refs/contract.md) instead.\n"
        self.assertNotEqual(_fp(before), _fp(after))

    def test_deeply_indented_fence_marker_is_not_a_closer(self):
        # A closer is indented 3 columns or fewer; 4 or more is code inside.
        self.assertNotEqual(_fp("```\n    ```\ntail old\n```\n"),
                            _fp("```\n    ```\ntail new\n```\n"))

    def test_multiline_setext_heading_first_line_change(self):
        # A setext heading may span lines; the first one is part of it.
        self.assertNotEqual(_fp("First old\nSecond\n------\n"),
                            _fp("First new\nSecond\n------\n"))

    def test_mixed_space_tab_indented_code_change(self):
        # Space plus tab reaches 4 columns once tab stops are expanded.
        self.assertNotEqual(_fp(" \tcommand old\n"), _fp(" \tcommand new\n"))

    def test_processing_instruction_html_change(self):
        self.assertNotEqual(_fp("<?agent allow?>\n"), _fp("<?agent deny?>\n"))

    def test_emphasized_normative_instruction_change(self):
        self.assertNotEqual(_fp("**MUST run validation.**\n"),
                            _fp("**MUST skip validation.**\n"))

    def test_strikethrough_removal_reactivates_instruction(self):
        # Lifting a strikethrough reinstates an instruction that was withdrawn.
        self.assertNotEqual(_fp("~~Run destructive cleanup.~~\n"),
                            _fp("Run destructive cleanup.\n"))


class TestFenceInteriorIsOpaque(unittest.TestCase):
    """Inside a fence everything is code; no other rule applies."""

    def test_prose_like_line_inside_fence_is_code(self):
        self.assertNotEqual(_fp("```\njust words here\n```\n"),
                            _fp("```\ndifferent words here\n```\n"))

    def test_unclosed_fence_swallows_rest(self):
        self.assertNotEqual(_fp("```\ntail one\n"), _fp("```\ntail two\n"))


class TestFingerprintShape(unittest.TestCase):
    def test_deterministic_hex(self):
        text = "# t\n\nprose\n"
        self.assertEqual(_fp(text), _fp(text))
        self.assertEqual(len(_fp(text)), 64)


if __name__ == "__main__":
    unittest.main()
