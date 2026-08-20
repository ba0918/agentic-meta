#!/usr/bin/env python3
"""Unit tests for stores.py.

Every location these tests point a store at is assembled in a temporary directory,
for the same reason the adapters' own tests are: the real locations hold the
operator's history.
"""

import datetime
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import events
import store_claude
import store_codex
import store_opencode
import stores

SINCE = datetime.datetime(2026, 8, 1, tzinfo=datetime.timezone.utc)


def _named(readings):
    return [reading.name for reading in readings]


def _by_name(readings, name):
    return next(reading for reading in readings if reading.name == name)


def _claude_root(parent, project="-w-notes"):
    directory = os.path.join(parent, "claude", project)
    os.makedirs(directory)
    record = {
        "type": "user",
        "sessionId": "session-1",
        "timestamp": "2026-08-19T12:00:00.000Z",
        "message": {"role": "user", "content": "hello"},
    }
    with open(os.path.join(directory, "a.jsonl"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    return os.path.join(parent, "claude")


class TestWhichStoresAreSelected(unittest.TestCase):
    def test_asking_for_every_store_reads_all_three(self):
        self.assertEqual(
            stores.selected_names(stores.EVERY_STORE),
            (store_claude.NAME, store_opencode.NAME, store_codex.NAME),
        )

    def test_asking_for_one_store_reads_only_that_one(self):
        self.assertEqual(stores.selected_names(store_codex.NAME), (store_codex.NAME,))

    def test_a_name_no_store_answers_to_is_refused(self):
        with self.assertRaises(ValueError):
            stores.selected_names("mystery")

    def test_the_selectable_names_are_the_three_stores_and_the_word_for_all_of_them(self):
        self.assertEqual(
            stores.SELECTABLE,
            (store_claude.NAME, store_opencode.NAME, store_codex.NAME, stores.EVERY_STORE),
        )


class TestWhereEachStoreIsRead(unittest.TestCase):
    def test_a_store_given_no_location_is_read_at_its_own_default(self):
        built = stores.build_stores(stores.EVERY_STORE)
        self.assertEqual(_by_name(built, store_claude.NAME).location,
                         store_claude.default_root())
        self.assertEqual(_by_name(built, store_opencode.NAME).location,
                         store_opencode.default_db_path())
        self.assertEqual(_by_name(built, store_codex.NAME).location,
                         store_codex.default_root())

    def test_a_location_given_for_a_store_replaces_its_default(self):
        with tempfile.TemporaryDirectory() as parent:
            built = stores.build_stores(
                store_codex.NAME, {store_codex.NAME: parent}
            )
            self.assertEqual(str(_by_name(built, store_codex.NAME).location), parent)

    def test_a_location_given_for_a_store_that_was_not_selected_is_ignored(self):
        with tempfile.TemporaryDirectory() as parent:
            built = stores.build_stores(store_codex.NAME, {store_claude.NAME: parent})
            self.assertEqual(_named(built), [store_codex.NAME])

    def test_the_store_that_was_built_reads_the_location_it_was_given(self):
        with tempfile.TemporaryDirectory() as parent:
            built = stores.build_stores(
                store_claude.NAME, {store_claude.NAME: _claude_root(parent)}
            )
            said = [
                event.text
                for event in _by_name(built, store_claude.NAME).store.events()
                if isinstance(event, events.UserText)
            ]
            self.assertEqual(said, ["hello"])


class TestTheArgumentsThatPointAtEachStore(unittest.TestCase):
    def test_each_store_carries_the_argument_that_points_it_somewhere_else(self):
        self.assertEqual(
            [kind.location_flag for kind in stores.REGISTRY],
            ["--claude-root", "--opencode-db", "--codex-root"],
        )

    def test_a_location_given_on_the_command_line_is_read_under_its_store_name(self):
        class Given:
            claude_root = "somewhere"
            opencode_db = None
            codex_root = None

        self.assertEqual(
            stores.given_locations(Given()), {store_claude.NAME: "somewhere"}
        )

    def test_a_command_line_naming_no_location_leaves_every_store_at_its_default(self):
        class Given:
            claude_root = None
            opencode_db = None
            codex_root = None

        self.assertEqual(stores.given_locations(Given()), {})


class TestWhichProjectIsRead(unittest.TestCase):
    def test_the_working_directory_is_the_project_when_none_is_named(self):
        self.assertEqual(
            stores.chosen_project(None, False), events.project_slug(os.getcwd())
        )

    def test_a_named_project_is_read_instead_of_the_working_directory(self):
        self.assertEqual(stores.chosen_project("-w-notes", False), "-w-notes")

    def test_asking_for_every_project_reads_them_all(self):
        self.assertIsNone(stores.chosen_project("-w-notes", True))


class TestWhetherTheStoreIsThere(unittest.TestCase):
    def test_a_store_whose_location_does_not_exist_is_reported_absent_not_dropped(self):
        with tempfile.TemporaryDirectory() as parent:
            absent = os.path.join(parent, "nothing-here")
            built = stores.build_stores(store_codex.NAME, {store_codex.NAME: absent})
            self.assertEqual(_named(built), [store_codex.NAME])
            self.assertFalse(_by_name(built, store_codex.NAME).present)

    def test_a_store_whose_location_exists_is_reported_present(self):
        with tempfile.TemporaryDirectory() as parent:
            built = stores.build_stores(store_codex.NAME, {store_codex.NAME: parent})
            self.assertTrue(_by_name(built, store_codex.NAME).present)

    def test_a_store_kept_in_one_file_is_present_only_when_that_file_is_there(self):
        with tempfile.TemporaryDirectory() as parent:
            database = os.path.join(parent, "opencode.db")
            built = stores.build_stores(
                store_opencode.NAME, {store_opencode.NAME: database}
            )
            self.assertFalse(_by_name(built, store_opencode.NAME).present)
            with open(database, "w", encoding="utf-8") as handle:
                handle.write("")
            rebuilt = stores.build_stores(
                store_opencode.NAME, {store_opencode.NAME: database}
            )
            self.assertTrue(_by_name(rebuilt, store_opencode.NAME).present)

    def test_a_store_that_is_not_there_still_reads_as_an_empty_store(self):
        with tempfile.TemporaryDirectory() as parent:
            built = stores.build_stores(
                stores.EVERY_STORE,
                {
                    store_claude.NAME: os.path.join(parent, "absent"),
                    store_opencode.NAME: os.path.join(parent, "absent.db"),
                    store_codex.NAME: os.path.join(parent, "absent"),
                },
            )
            for reading in built:
                self.assertEqual(list(reading.store.events()), [], msg=reading.name)


class TestTheReadingEveryStoreIsBuiltFor(unittest.TestCase):
    def test_every_store_is_built_for_the_same_period_and_project(self):
        built = stores.build_stores(
            stores.EVERY_STORE, since=SINCE, project="-w-notes"
        )
        for reading in built:
            self.assertEqual(reading.store.since, SINCE, msg=reading.name)
            self.assertEqual(reading.store.project, "-w-notes", msg=reading.name)

    def test_every_store_built_satisfies_the_adapter_contract(self):
        for reading in stores.build_stores(stores.EVERY_STORE):
            self.assertIsInstance(reading.store, events.SessionStore, msg=reading.name)

    def test_each_store_is_built_under_the_name_its_adapter_declares(self):
        for reading in stores.build_stores(stores.EVERY_STORE):
            self.assertEqual(reading.name, reading.store.name)


if __name__ == "__main__":
    unittest.main()
