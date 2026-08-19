#!/usr/bin/env python3
"""Unit tests for yaml_subset.py.

The reader accepts the block subset a scenario declaration needs and refuses
everything else. Refusing loudly is the point: a construct read wrongly would
silently change what a scenario declares, and a scenario nobody can read is
exactly what this format exists to prevent.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yaml_subset


def _load(text):
    return yaml_subset.load(text)


class TestScalars(unittest.TestCase):
    def test_plain_string(self):
        self.assertEqual(_load("id: te-001\n"), {"id": "te-001"})

    def test_integer(self):
        self.assertEqual(_load("offset: -3600\n"), {"offset": -3600})

    def test_booleans(self):
        self.assertEqual(_load("critical: true\nskip: false\n"),
                         {"critical": True, "skip": False})

    def test_empty_value_is_null(self):
        self.assertEqual(_load("notes:\n"), {"notes": None})

    def test_single_quoted_keeps_special_characters(self):
        self.assertEqual(_load("title: 'a: b #c'\n"), {"title": "a: b #c"})

    def test_double_quoted_keeps_special_characters(self):
        self.assertEqual(_load('title: "a: b #c"\n'), {"title": "a: b #c"})

    def test_quoted_digits_stay_a_string(self):
        self.assertEqual(_load("id: '2026'\n"), {"id": "2026"})

    def test_comment_line_and_trailing_comment_are_dropped(self):
        self.assertEqual(_load("# leading\nid: x  # trailing\n"), {"id": "x"})

    def test_hash_without_leading_space_is_not_a_comment(self):
        self.assertEqual(_load("id: a#b\n"), {"id": "a#b"})


class TestBlockScalars(unittest.TestCase):
    def test_literal_block_keeps_line_breaks(self):
        text = "prompt: |\n  first line\n  second line\n"
        self.assertEqual(_load(text), {"prompt": "first line\nsecond line\n"})

    def test_literal_block_strip_drops_the_final_newline(self):
        text = "prompt: |-\n  only line\n"
        self.assertEqual(_load(text), {"prompt": "only line"})

    def test_literal_block_keeps_inner_blank_lines_and_indentation(self):
        text = "prompt: |\n  a\n\n    indented\n  b\n"
        self.assertEqual(_load(text), {"prompt": "a\n\n  indented\nb\n"})

    def test_literal_block_does_not_swallow_the_next_key(self):
        text = "prompt: |\n  body\nid: x\n"
        self.assertEqual(_load(text), {"prompt": "body\n", "id": "x"})

    def test_block_content_is_not_reinterpreted(self):
        text = "prompt: |\n  - not a list\n  key: not a mapping\n"
        self.assertEqual(_load(text),
                         {"prompt": "- not a list\nkey: not a mapping\n"})


class TestNesting(unittest.TestCase):
    def test_nested_mapping(self):
        text = "git:\n  init: true\n  branch: master\n"
        self.assertEqual(_load(text), {"git": {"init": True, "branch": "master"}})

    def test_sequence_of_scalars(self):
        text = "files:\n  - a/one.md\n  - a/two.md\n"
        self.assertEqual(_load(text), {"files": ["a/one.md", "a/two.md"]})

    def test_sequence_of_mappings(self):
        text = ("expectations:\n"
                "  - text: first\n"
                "    critical: true\n"
                "  - text: second\n"
                "    critical: false\n")
        self.assertEqual(_load(text), {"expectations": [
            {"text": "first", "critical": True},
            {"text": "second", "critical": False},
        ]})

    def test_mapping_inside_sequence_inside_mapping(self):
        text = ("git:\n"
                "  commits:\n"
                "    - files:\n"
                "        - a/one.md\n"
                "      message: initial\n")
        self.assertEqual(_load(text), {"git": {"commits": [
            {"files": ["a/one.md"], "message": "initial"},
        ]}})

    def test_block_scalar_inside_sequence_of_mappings(self):
        text = ("expectations:\n"
                "  - text: |\n"
                "      long one\n"
                "      continued\n"
                "    critical: true\n")
        self.assertEqual(_load(text), {"expectations": [
            {"text": "long one\ncontinued\n", "critical": True},
        ]})

    def test_keys_with_slashes_are_allowed(self):
        text = "mtimes:\n  project/README.md: -60\n"
        self.assertEqual(_load(text), {"mtimes": {"project/README.md": -60}})


class TestRefusals(unittest.TestCase):
    def _refused(self, text):
        with self.assertRaises(yaml_subset.YamlSubsetError):
            _load(text)

    def test_flow_mapping_is_refused(self):
        self._refused("git: {init: true}\n")

    def test_flow_sequence_is_refused(self):
        self._refused("files: [a.md, b.md]\n")

    def test_anchor_is_refused(self):
        self._refused("base: &anchor\n  init: true\n")

    def test_alias_is_refused(self):
        self._refused("git: *anchor\n")

    def test_tag_is_refused(self):
        self._refused("value: !!python/object:os.system\n")

    def test_document_separator_is_refused(self):
        self._refused("id: a\n---\nid: b\n")

    def test_merge_key_is_refused(self):
        self._refused("<<: base\n")

    def test_tab_indentation_is_refused(self):
        self._refused("git:\n\tinit: true\n")

    def test_duplicate_key_is_refused(self):
        self._refused("id: a\nid: b\n")

    def test_folded_block_scalar_is_refused(self):
        # Folding rewrites line breaks, so a prompt would not survive as written.
        self._refused("prompt: >\n  folded\n")

    def test_line_without_a_key_is_refused(self):
        self._refused("id: a\njust some prose\n")

    def test_inconsistent_indentation_is_refused(self):
        self._refused("git:\n  init: true\n   branch: master\n")

    def test_top_level_sequence_is_refused(self):
        # A scenario file declares one scenario, which is a mapping.
        self._refused("- one\n- two\n")

    def test_empty_document_is_refused(self):
        self._refused("\n#  only a comment\n")


class TestLineNumbersInErrors(unittest.TestCase):
    def test_error_names_the_line(self):
        with self.assertRaises(yaml_subset.YamlSubsetError) as ctx:
            _load("id: a\nfiles: [x]\n")
        self.assertIn("line 2", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
