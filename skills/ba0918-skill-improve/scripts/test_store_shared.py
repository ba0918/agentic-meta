#!/usr/bin/env python3
"""Unit tests for store_shared.py.

Sample paths are assembled rather than written whole: the self-containment lint
reads a rooted home path in any file as an escape from the skill directory.
"""

import datetime
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import store_shared

CUTOFF = datetime.datetime(2026, 8, 1, tzinfo=datetime.timezone.utc)


def _touch(directory, name, written=None):
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("x")
    if written is not None:
        os.utime(path, (written, written))
    return pathlib.Path(path)


class TestContainment(unittest.TestCase):
    def test_a_path_inside_the_root_is_returned_resolved(self):
        with tempfile.TemporaryDirectory() as root:
            inside = _touch(root, "a.jsonl")
            self.assertEqual(
                store_shared.resolve_within(inside, pathlib.Path(root)), inside.resolve()
            )

    def test_a_path_linked_to_a_place_outside_the_root_is_refused(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            target = _touch(outside, "a.jsonl")
            link = os.path.join(root, "a.jsonl")
            os.symlink(target, link)
            self.assertIsNone(
                store_shared.resolve_within(pathlib.Path(link), pathlib.Path(root))
            )

    def test_a_directory_beside_the_root_is_not_read_as_part_of_it(self):
        with tempfile.TemporaryDirectory() as parent:
            root = os.path.join(parent, "projects")
            sibling = os.path.join(parent, "projects-backup")
            os.makedirs(root)
            os.makedirs(sibling)
            self.assertIsNone(
                store_shared.resolve_within(pathlib.Path(sibling), pathlib.Path(root))
            )

    def test_a_path_that_is_not_there_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            absent = pathlib.Path(os.path.join(root, "absent"))
            self.assertIsNone(store_shared.resolve_within(absent, pathlib.Path(root)))


class TestWriteTimeFilter(unittest.TestCase):
    def test_a_file_last_written_before_the_period_is_dropped_before_it_is_opened(self):
        with tempfile.TemporaryDirectory() as root:
            stale = _touch(root, "stale.jsonl", written=CUTOFF.timestamp() - 86400)
            fresh = _touch(root, "fresh.jsonl")
            kept = store_shared.files_written_since([stale, fresh], CUTOFF)
            self.assertEqual([one.name for one in kept], ["fresh.jsonl"])

    def test_a_file_whose_write_time_cannot_be_read_is_kept_for_the_later_filter(self):
        missing = pathlib.Path(os.path.join("no-such-place", "a.jsonl"))
        self.assertEqual(store_shared.files_written_since([missing], CUTOFF), [missing])

    def test_without_a_period_every_file_is_kept(self):
        with tempfile.TemporaryDirectory() as root:
            stale = _touch(root, "stale.jsonl", written=CUTOFF.timestamp() - 86400)
            self.assertEqual(store_shared.files_written_since([stale], None), [stale])


class TestWrittenTimes(unittest.TestCase):
    def test_a_time_written_with_a_zone_keeps_it(self):
        self.assertEqual(
            store_shared.zoned_time("2026-08-19T12:00:00.000Z"),
            datetime.datetime(2026, 8, 19, 12, 0, tzinfo=datetime.timezone.utc),
        )

    def test_a_time_written_without_a_zone_is_read_as_universal_time(self):
        self.assertEqual(
            store_shared.zoned_time("2026-08-19T12:00:00"),
            datetime.datetime(2026, 8, 19, 12, 0, tzinfo=datetime.timezone.utc),
        )

    def test_what_is_not_a_written_time_is_no_time_at_all(self):
        for written in ("not a time", "", None, 1755604800):
            self.assertIsNone(store_shared.zoned_time(written), written)


class TestSlashCommands(unittest.TestCase):
    def test_a_slash_command_names_the_skill_without_its_plugin_prefix(self):
        self.assertEqual(
            store_shared.slash_skill_in("please run /claude-skills:plan-create now"),
            "plan-create",
        )

    def test_text_carrying_no_slash_command_fires_nothing(self):
        self.assertIsNone(store_shared.slash_skill_in("please commit this"))

    def test_a_path_that_merely_looks_like_a_command_fires_nothing(self):
        self.assertIsNone(store_shared.slash_skill_in("read skills/ba0918-commit/SKILL.md"))


if __name__ == "__main__":
    unittest.main()
