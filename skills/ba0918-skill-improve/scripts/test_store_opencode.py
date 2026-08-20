#!/usr/bin/env python3
"""Unit tests for store_opencode.py.

Every database these tests read is built in a temporary directory. The real one
holds the operator's own history beside its credentials, so reading it here would
put material no test may see in front of a test runner.

The fixture database carries the credential-holding tables as well, so a test that
finds no query against them is evidence about the adapter rather than an accident
of those tables being absent.
"""

import datetime
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import events
import store_opencode

SEPARATOR = "/"
NOW = datetime.datetime(2026, 8, 19, 12, 0, tzinfo=datetime.timezone.utc)
LONG_AGO = datetime.datetime(2026, 1, 1, 12, 0, tzinfo=datetime.timezone.utc)
CUTOFF = datetime.datetime(2026, 8, 1, tzinfo=datetime.timezone.utc)
WORKTREE = SEPARATOR + SEPARATOR.join(("w", "notes"))
WORKTREE_KEY = "-w-notes"

SCHEMA = """
CREATE TABLE project (id TEXT PRIMARY KEY, worktree TEXT, vcs TEXT, name TEXT,
                      time_created INTEGER);
CREATE TABLE session (id TEXT PRIMARY KEY, project_id TEXT, workspace_id TEXT,
                      parent_id TEXT, slug TEXT, directory TEXT, path TEXT, title TEXT,
                      version TEXT, agent TEXT, model TEXT, time_created INTEGER,
                      time_updated INTEGER);
CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER,
                      time_updated INTEGER, data TEXT);
CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT,
                   time_created INTEGER, time_updated INTEGER, data TEXT);
CREATE TABLE credential (id TEXT PRIMARY KEY, provider TEXT, value TEXT);
CREATE TABLE auth (id TEXT PRIMARY KEY, token TEXT);
CREATE TABLE account (id TEXT PRIMARY KEY, email TEXT);
CREATE TABLE permission (id TEXT PRIMARY KEY, scope TEXT);
"""

FORBIDDEN_TABLES = ("credential", "auth", "account", "permission")


def _milliseconds(when):
    return int(when.timestamp() * 1000)


class Database:
    """A database shaped like the real one, built row by row for one test."""

    def __init__(self, directory, name="opencode.db"):
        self.path = os.path.join(directory, name)
        self._connection = sqlite3.connect(self.path)
        self._connection.executescript(SCHEMA)
        self._connection.execute(
            "INSERT INTO credential (id, provider, value) VALUES (?, ?, ?)",
            ("c-1", "some-provider", "a-secret-value"),
        )
        self._connection.commit()

    def session(self, identifier="s-1", directory=WORKTREE, updated=NOW):
        self._connection.execute(
            "INSERT INTO session (id, directory, time_created, time_updated)"
            " VALUES (?, ?, ?, ?)",
            (identifier, directory, _milliseconds(updated), _milliseconds(updated)),
        )
        self._connection.commit()
        return self

    def message(self, identifier="m-1", session="s-1", role="user", when=NOW, **extra):
        body = {"role": role, "time": {"created": _milliseconds(when)}}
        body.update(extra)
        self._connection.execute(
            "INSERT INTO message (id, session_id, time_created, time_updated, data)"
            " VALUES (?, ?, ?, ?, ?)",
            (identifier, session, _milliseconds(when), _milliseconds(when),
             json.dumps(body)),
        )
        self._connection.commit()
        return self

    def part(self, identifier, message="m-1", session="s-1", when=NOW, **body):
        self._connection.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (identifier, message, session, _milliseconds(when), _milliseconds(when),
             json.dumps(body)),
        )
        self._connection.commit()
        return self

    def text_part(self, identifier, text, message="m-1", session="s-1", when=NOW):
        return self.part(identifier, message=message, session=session, when=when,
                         type="text", text=text, time={"start": _milliseconds(when)})

    def skill_part(self, identifier, skill, message="m-1", session="s-1", when=NOW):
        return self.part(
            identifier, message=message, session=session, when=when,
            type="tool", tool="skill", callID="call-" + identifier,
            state={"status": "completed", "input": {"name": skill},
                   "output": "done", "title": skill, "metadata": {},
                   "time": {"start": _milliseconds(when)}},
        )

    def failed_part(self, identifier, tool="bash", message="m-1", session="s-1", when=NOW):
        return self.part(
            identifier, message=message, session=session, when=when,
            type="tool", tool=tool, callID="call-" + identifier,
            state={"status": "error", "input": {}, "error": "it failed",
                   "metadata": {}, "time": {"start": _milliseconds(when)}},
        )

    def close(self):
        self._connection.close()


def _events_of(database, **kwargs):
    return list(store_opencode.OpenCodeStore(db_path=database.path, **kwargs).events())


def _of_kind(collected, kind):
    return [event for event in collected if isinstance(event, kind)]


class TestDeclaredCapabilities(unittest.TestCase):
    def test_the_store_reads_both_the_text_and_the_structural_route(self):
        with tempfile.TemporaryDirectory() as directory:
            store = store_opencode.OpenCodeStore(db_path=os.path.join(directory, "x.db"))
            self.assertTrue(store.capabilities.text)
            self.assertTrue(store.capabilities.structural)

    def test_the_store_declares_that_it_keeps_no_record_of_abandonment(self):
        with tempfile.TemporaryDirectory() as directory:
            store = store_opencode.OpenCodeStore(db_path=os.path.join(directory, "x.db"))
            self.assertFalse(store.capabilities.abandonment_signal)

    def test_the_store_satisfies_the_adapter_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            store = store_opencode.OpenCodeStore(db_path=os.path.join(directory, "x.db"))
            self.assertIsInstance(store, events.SessionStore)


class TestDefaultLocation(unittest.TestCase):
    def test_the_default_location_is_the_runtime_database_under_the_home(self):
        default = store_opencode.default_db_path()
        self.assertEqual(default.name, "opencode.db")
        self.assertEqual(default.parent.name, "opencode")
        self.assertTrue(default.is_relative_to(store_opencode.pathlib.Path.home()))


class TestReadOnlyAccess(unittest.TestCase):
    def test_the_database_is_opened_so_that_a_write_through_it_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(directory).session()
            database.close()
            connection = store_opencode.connect_readonly(database.path)
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute(
                    "INSERT INTO session (id, directory) VALUES ('s-2', 'x')"
                )
            connection.close()

    def test_a_name_reading_as_a_read_write_request_is_still_opened_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(directory, name="x.db?mode=rwc&").session()
            database.close()
            connection = store_opencode.connect_readonly(database.path)
            with self.assertRaises(sqlite3.OperationalError) as refused:
                connection.execute(
                    "INSERT INTO session (id, directory) VALUES ('s-2', 'x')"
                )
            connection.close()
            self.assertIn("readonly", str(refused.exception))
            self.assertFalse(os.path.exists(os.path.join(directory, "x.db")))

    def test_a_name_holding_a_fragment_marker_opens_that_file_and_creates_no_other(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(directory, name="x#1.db").session()
            database.close()
            found = _of_kind(_events_of(database), events.SessionIdentity)
            self.assertEqual([one.session_id for one in found], ["s-1"])
            self.assertFalse(os.path.exists(os.path.join(directory, "x")))

    def test_a_name_holding_a_percent_sign_opens_the_file_it_names(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(directory, name="a%2Fb.db").session()
            database.close()
            found = _of_kind(_events_of(database), events.SessionIdentity)
            self.assertEqual([one.session_id for one in found], ["s-1"])

    def test_a_database_that_is_not_there_is_read_as_an_empty_store(self):
        with tempfile.TemporaryDirectory() as directory:
            store = store_opencode.OpenCodeStore(db_path=os.path.join(directory, "absent.db"))
            self.assertEqual(list(store.events()), [])


class TestTablesItQueries(unittest.TestCase):
    def _statements_of_one_reading(self, database):
        recorded = []

        def watched(path):
            connection = store_opencode.connect_readonly(path)
            connection.set_trace_callback(recorded.append)
            return connection

        list(store_opencode.OpenCodeStore(db_path=database.path, connect=watched).events())
        return recorded

    def test_no_statement_it_runs_names_a_table_holding_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            database = (Database(directory).session()
                        .message().text_part("p-1", "hello"))
            database.close()
            statements = self._statements_of_one_reading(database)
            self.assertTrue(statements)
            for statement in statements:
                for forbidden in FORBIDDEN_TABLES:
                    self.assertNotIn(forbidden, statement.lower(), statement)

    def test_every_table_it_reads_is_one_of_the_four_it_declares(self):
        with tempfile.TemporaryDirectory() as directory:
            database = (Database(directory).session()
                        .message().text_part("p-1", "hello"))
            database.close()
            read = set()
            for statement in self._statements_of_one_reading(database):
                read.update(re.findall(r"(?:from|join)\s+([a-z_]+)", statement.lower()))
            self.assertTrue(read)
            self.assertTrue(read.issubset(set(store_opencode.TABLES_READ)), read)

    def test_the_declared_tables_are_the_four_that_hold_no_credentials(self):
        self.assertEqual(
            set(store_opencode.TABLES_READ), {"project", "session", "message", "part"}
        )


class TestStructuralRoute(unittest.TestCase):
    def test_a_skill_tool_part_is_detected_as_a_structural_invocation(self):
        with tempfile.TemporaryDirectory() as directory:
            database = (Database(directory).session()
                        .message(role="assistant").skill_part("p-1", "commit"))
            database.close()
            found = _of_kind(_events_of(database), events.SkillInvocation)
            self.assertEqual(
                found, [events.SkillInvocation(skill="commit", route=events.ROUTE_STRUCTURAL)]
            )

    def test_a_tool_part_that_is_not_a_skill_call_produces_no_invocation(self):
        with tempfile.TemporaryDirectory() as directory:
            database = (Database(directory).session()
                        .message(role="assistant").failed_part("p-1", tool="bash"))
            database.close()
            self.assertEqual(_of_kind(_events_of(database), events.SkillInvocation), [])


class TestToolErrors(unittest.TestCase):
    def test_a_tool_part_left_in_the_error_state_counts_as_a_tool_error(self):
        with tempfile.TemporaryDirectory() as directory:
            database = (Database(directory).session()
                        .message(role="assistant").failed_part("p-1", tool="bash"))
            database.close()
            failed = _of_kind(_events_of(database), events.ToolError)
            self.assertEqual(failed, [events.ToolError(tool="bash")])

    def test_a_tool_part_that_completed_is_not_a_tool_error(self):
        with tempfile.TemporaryDirectory() as directory:
            database = (Database(directory).session()
                        .message(role="assistant").skill_part("p-1", "commit"))
            database.close()
            self.assertEqual(_of_kind(_events_of(database), events.ToolError), [])


class TestUserUtterances(unittest.TestCase):
    def test_the_body_of_a_user_message_is_read_from_its_text_parts(self):
        with tempfile.TemporaryDirectory() as directory:
            database = (Database(directory).session().message(role="user")
                        .text_part("p-1", "first fragment")
                        .text_part("p-2", "second fragment"))
            database.close()
            said = _of_kind(_events_of(database), events.UserText)
            self.assertEqual([one.text for one in said], ["first fragment\nsecond fragment"])

    def test_what_the_agent_wrote_is_not_read_as_an_utterance(self):
        with tempfile.TemporaryDirectory() as directory:
            database = (Database(directory).session()
                        .message(role="assistant").text_part("p-1", "answering"))
            database.close()
            self.assertEqual(_of_kind(_events_of(database), events.UserText), [])

    def test_a_slash_command_in_an_utterance_is_detected_as_a_text_invocation(self):
        with tempfile.TemporaryDirectory() as directory:
            database = (Database(directory).session().message(role="user")
                        .text_part("p-1", "/claude-skills:commit please"))
            database.close()
            found = _of_kind(_events_of(database), events.SkillInvocation)
            self.assertEqual(
                found, [events.SkillInvocation(skill="commit", route=events.ROUTE_TEXT)]
            )


class TestTurns(unittest.TestCase):
    def test_a_message_by_either_side_is_one_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            database = (Database(directory).session()
                        .message(identifier="m-1", role="user")
                        .text_part("p-1", "ask", message="m-1")
                        .message(identifier="m-2", role="assistant")
                        .text_part("p-2", "answer", message="m-2"))
            database.close()
            turns = _of_kind(_events_of(database), events.Turn)
            self.assertEqual([one.role for one in turns], ["user", "assistant"])

    def test_a_message_in_neither_role_is_not_a_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            database = (Database(directory).session().message(role="system")
                        .text_part("p-1", "a system note"))
            database.close()
            self.assertEqual(_of_kind(_events_of(database), events.Turn), [])

    def test_a_message_built_only_of_tool_parts_is_not_a_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            database = (Database(directory).session().message(role="assistant")
                        .skill_part("p-1", "commit").failed_part("p-2"))
            database.close()
            self.assertEqual(_of_kind(_events_of(database), events.Turn), [])

    def test_a_message_with_no_parts_at_all_is_not_a_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(directory).session().message(role="user")
            database.close()
            self.assertEqual(_of_kind(_events_of(database), events.Turn), [])

    def test_a_tool_part_does_not_add_a_turn_of_its_own(self):
        with tempfile.TemporaryDirectory() as directory:
            database = (Database(directory).session().message(role="assistant")
                        .text_part("p-1", "running it now")
                        .skill_part("p-2", "commit").failed_part("p-3"))
            database.close()
            self.assertEqual(len(_of_kind(_events_of(database), events.Turn)), 1)


class TestSessionIdentity(unittest.TestCase):
    def test_the_working_directory_becomes_the_key_the_other_stores_meet_on(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(directory).session(directory=WORKTREE).message()
            database.close()
            identity = _of_kind(_events_of(database), events.SessionIdentity)
            self.assertEqual([one.project for one in identity], [WORKTREE_KEY])

    def test_the_session_is_named_by_its_own_identifier(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(directory).session(identifier="s-9").message(session="s-9")
            database.close()
            identity = _of_kind(_events_of(database), events.SessionIdentity)
            self.assertEqual([one.session_id for one in identity], ["s-9"])

    def test_the_identity_is_announced_before_the_events_it_covers(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(directory).session().message()
            database.close()
            self.assertIsInstance(_events_of(database)[0], events.SessionIdentity)


class TestProjectFilter(unittest.TestCase):
    def test_only_the_named_project_is_read(self):
        other = SEPARATOR + SEPARATOR.join(("w", "other"))
        with tempfile.TemporaryDirectory() as directory:
            database = (Database(directory)
                        .session(identifier="s-1", directory=WORKTREE)
                        .session(identifier="s-2", directory=other)
                        .message(identifier="m-1", session="s-1").text_part("p-1", "kept")
                        .message(identifier="m-2", session="s-2")
                        .text_part("p-2", "dropped", message="m-2", session="s-2"))
            database.close()
            said = _of_kind(_events_of(database, project=WORKTREE_KEY), events.UserText)
            self.assertEqual([one.text for one in said], ["kept"])

    def test_a_project_whose_key_merely_extends_the_filter_is_not_read(self):
        extended = SEPARATOR + SEPARATOR.join(("w", "notes", "archive"))
        with tempfile.TemporaryDirectory() as directory:
            database = (Database(directory)
                        .session(identifier="s-1", directory=WORKTREE)
                        .session(identifier="s-2", directory=extended)
                        .message(identifier="m-1", session="s-1").text_part("p-1", "kept")
                        .message(identifier="m-2", session="s-2")
                        .text_part("p-2", "dropped", message="m-2", session="s-2"))
            database.close()
            said = _of_kind(_events_of(database, project=WORKTREE_KEY), events.UserText)
            self.assertEqual([one.text for one in said], ["kept"])


class TestPeriod(unittest.TestCase):
    def test_a_time_is_read_as_milliseconds_rather_than_seconds(self):
        self.assertEqual(store_opencode.from_milliseconds(_milliseconds(NOW)), NOW)

    def test_a_message_written_before_the_period_is_left_out(self):
        with tempfile.TemporaryDirectory() as directory:
            database = (Database(directory).session()
                        .message(identifier="m-1", when=LONG_AGO)
                        .text_part("p-1", "old", when=LONG_AGO)
                        .message(identifier="m-2", when=NOW)
                        .text_part("p-2", "new", message="m-2", when=NOW))
            database.close()
            said = _of_kind(_events_of(database, since=CUTOFF), events.UserText)
            self.assertEqual([one.text for one in said], ["new"])

    def test_a_session_untouched_since_before_the_period_is_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            database = (Database(directory)
                        .session(identifier="s-old", updated=LONG_AGO)
                        .message(identifier="m-1", session="s-old", when=LONG_AGO))
            database.close()
            self.assertEqual(_events_of(database, since=CUTOFF), [])


class TestMalformedRows(unittest.TestCase):
    def test_a_row_whose_body_is_not_readable_does_not_stop_the_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(directory).session()
            connection = sqlite3.connect(database.path)
            connection.execute(
                "INSERT INTO message (id, session_id, time_created, time_updated, data)"
                " VALUES (?, ?, ?, ?, ?)",
                ("m-broken", "s-1", _milliseconds(NOW), _milliseconds(NOW), "{not json"),
            )
            connection.commit()
            connection.close()
            database.message(identifier="m-2", role="user").text_part(
                "p-1", "survived", message="m-2"
            )
            database.close()
            said = _of_kind(_events_of(database), events.UserText)
            self.assertEqual([one.text for one in said], ["survived"])


if __name__ == "__main__":
    unittest.main()
