#!/usr/bin/env python3
"""Unit tests for store_claude.py.

Every session log these tests read is assembled in a temporary directory. The real
store holds the operator's own history, so reading it here would make the tests
depend on data no one can inspect and would put message bodies in front of a test
runner.

Sample paths are assembled rather than written whole: the self-containment lint
reads a rooted home path in any file as an escape from the skill directory.
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

SEPARATOR = "/"
NOW = "2026-08-19T12:00:00.000Z"
LONG_AGO = "2026-01-01T00:00:00.000Z"
CUTOFF = datetime.datetime(2026, 8, 1, tzinfo=datetime.timezone.utc)


def _message(role, content, timestamp=NOW, **extra):
    """A record of the kind the runtime writes for one message."""
    record = {
        "type": role,
        "sessionId": "session-1",
        "uuid": "u-1",
        "timestamp": timestamp,
        "message": {"role": role, "content": content},
    }
    record.update(extra)
    return record


def _write_session(root, project, filename, records):
    directory = os.path.join(root, project)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, filename)
    with open(path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    return path


def _events_of(root, **kwargs):
    return list(store_claude.ClaudeCodeStore(root=root, **kwargs).events())


def _of_kind(collected, kind):
    return [event for event in collected if isinstance(event, kind)]


class TestDeclaredCapabilities(unittest.TestCase):
    def test_the_store_reads_both_the_text_and_the_structural_route(self):
        with tempfile.TemporaryDirectory() as root:
            store = store_claude.ClaudeCodeStore(root=root)
            self.assertTrue(store.capabilities.text)
            self.assertTrue(store.capabilities.structural)

    def test_the_store_satisfies_the_adapter_contract(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertIsInstance(store_claude.ClaudeCodeStore(root=root), events.SessionStore)


class TestDefaultLocation(unittest.TestCase):
    def test_the_default_location_is_the_runtime_project_directory_under_the_home(self):
        default = store_claude.default_root()
        self.assertEqual(default.name, "projects")
        self.assertEqual(default.parent.name, "." + "claude")
        self.assertEqual(default.parent.parent, store_claude.pathlib.Path.home())


class TestStructuralRoute(unittest.TestCase):
    def test_a_skill_tool_call_is_detected_as_a_structural_invocation(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [
                _message("assistant", [
                    {"type": "tool_use", "name": "Skill", "input": {"skill": "commit"}},
                ]),
            ])
            found = _of_kind(_events_of(root), events.SkillInvocation)
            self.assertEqual(
                found, [events.SkillInvocation(skill="commit", route=events.ROUTE_STRUCTURAL)]
            )

    def test_a_plugin_prefixed_skill_is_recorded_under_its_bare_name(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [
                _message("assistant", [
                    {"type": "tool_use", "name": "Skill",
                     "input": {"skill": "claude-skills:plan-create"}},
                ]),
            ])
            found = _of_kind(_events_of(root), events.SkillInvocation)
            self.assertEqual([one.skill for one in found], ["plan-create"])

    def test_a_tool_call_that_is_not_a_skill_call_produces_no_invocation(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [
                _message("assistant", [
                    {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                ]),
            ])
            self.assertEqual(_of_kind(_events_of(root), events.SkillInvocation), [])

    def test_a_skill_name_that_does_not_fit_the_naming_pattern_is_recorded_as_written(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [
                _message("assistant", [
                    {"type": "tool_use", "name": "Skill", "input": {"skill": "Odd Name"}},
                ]),
            ])
            found = _of_kind(_events_of(root), events.SkillInvocation)
            self.assertEqual([one.skill for one in found], ["Odd Name"])

    def test_every_skill_call_in_one_message_is_recorded(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [
                _message("assistant", [
                    {"type": "tool_use", "name": "Skill", "input": {"skill": "commit"}},
                    {"type": "tool_use", "name": "Skill", "input": {"skill": "wiki:wiki-lint"}},
                ]),
            ])
            found = _of_kind(_events_of(root), events.SkillInvocation)
            self.assertEqual([one.skill for one in found], ["commit", "wiki-lint"])


class TestTextRoute(unittest.TestCase):
    def test_a_slash_command_in_an_utterance_is_detected_as_a_text_invocation(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [
                _message("user", [{"type": "text", "text": "/claude-skills:commit please"}]),
            ])
            found = _of_kind(_events_of(root), events.SkillInvocation)
            self.assertEqual(
                found, [events.SkillInvocation(skill="commit", route=events.ROUTE_TEXT)]
            )

    def test_a_slash_command_written_by_the_agent_is_not_taken_as_an_invocation(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [
                _message("assistant", [{"type": "text", "text": "run /wiki:wiki-lint next"}]),
            ])
            self.assertEqual(_of_kind(_events_of(root), events.SkillInvocation), [])


class TestUserUtterances(unittest.TestCase):
    def test_one_utterance_is_produced_per_user_message(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [
                _message("user", [
                    {"type": "text", "text": "first fragment"},
                    {"type": "text", "text": "second fragment"},
                ]),
            ])
            said = _of_kind(_events_of(root), events.UserText)
            self.assertEqual([one.text for one in said], ["first fragment\nsecond fragment"])

    def test_an_utterance_stored_as_a_plain_string_is_read(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [_message("user", "plain body")])
            said = _of_kind(_events_of(root), events.UserText)
            self.assertEqual([one.text for one in said], ["plain body"])

    def test_a_tool_result_carries_no_utterance_even_though_it_wears_the_user_role(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [
                _message("user", [
                    {"type": "tool_result", "tool_use_id": "t-1", "content": "ok"},
                ]),
            ])
            self.assertEqual(_of_kind(_events_of(root), events.UserText), [])

    def test_the_utterance_is_timed_by_the_record_that_carries_it(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [
                _message("user", "hello", timestamp="2026-08-19T12:00:00.000Z"),
            ])
            said = _of_kind(_events_of(root), events.UserText)
            self.assertEqual(
                said[0].at,
                datetime.datetime(2026, 8, 19, 12, 0, tzinfo=datetime.timezone.utc),
            )


class TestToolErrors(unittest.TestCase):
    def test_a_failed_tool_result_block_counts_as_a_tool_error(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [
                _message("user", [
                    {"type": "tool_result", "tool_use_id": "t-1", "is_error": True},
                ]),
            ])
            self.assertEqual(len(_of_kind(_events_of(root), events.ToolError)), 1)

    def test_a_failure_recorded_only_beside_the_message_counts_as_a_tool_error(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [
                _message("user", [{"type": "text", "text": "n/a"}],
                         toolUseResult={"is_error": True}),
            ])
            self.assertEqual(len(_of_kind(_events_of(root), events.ToolError)), 1)

    def test_one_failure_recorded_in_both_places_is_counted_once(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [
                _message("user", [
                    {"type": "tool_result", "tool_use_id": "t-1", "is_error": True},
                ], toolUseResult={"is_error": True}),
            ])
            self.assertEqual(len(_of_kind(_events_of(root), events.ToolError)), 1)

    def test_a_successful_tool_result_is_not_a_tool_error(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [
                _message("user", [
                    {"type": "tool_result", "tool_use_id": "t-1", "is_error": False},
                ]),
            ])
            self.assertEqual(_of_kind(_events_of(root), events.ToolError), [])

    def test_the_error_names_the_tool_whose_call_it_answers(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [
                _message("assistant", [
                    {"type": "tool_use", "id": "t-1", "name": "Bash", "input": {}},
                ]),
                _message("user", [
                    {"type": "tool_result", "tool_use_id": "t-1", "is_error": True},
                ]),
            ])
            failed = _of_kind(_events_of(root), events.ToolError)
            self.assertEqual([one.tool for one in failed], ["Bash"])

    def test_an_error_answering_no_recorded_call_is_still_counted(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [
                _message("user", [
                    {"type": "tool_result", "tool_use_id": "unseen", "is_error": True},
                ]),
            ])
            failed = _of_kind(_events_of(root), events.ToolError)
            self.assertEqual(len(failed), 1)
            self.assertEqual(failed[0].tool, store_claude.UNNAMED_TOOL)


class TestTurns(unittest.TestCase):
    def test_a_message_by_either_side_is_one_turn(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [
                _message("user", "ask"),
                _message("assistant", [{"type": "text", "text": "answer"}]),
            ])
            turns = _of_kind(_events_of(root), events.Turn)
            self.assertEqual([one.role for one in turns], ["user", "assistant"])

    def test_a_record_carrying_no_message_is_not_a_turn(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [
                {"type": "attachment", "timestamp": NOW, "sessionId": "session-1"},
                {"type": "system", "timestamp": NOW, "sessionId": "session-1"},
                {"type": "ai-title", "timestamp": NOW, "sessionId": "session-1"},
                {"type": "file-history-snapshot", "timestamp": NOW, "sessionId": "session-1"},
            ])
            self.assertEqual(_of_kind(_events_of(root), events.Turn), [])

    def test_a_record_holding_only_a_tool_answer_is_not_a_turn(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [
                _message("user", [
                    {"type": "tool_result", "tool_use_id": "t-1", "content": "ok"},
                ]),
            ])
            self.assertEqual(_of_kind(_events_of(root), events.Turn), [])

    def test_a_record_holding_only_a_tool_call_is_not_a_turn(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [
                _message("assistant", [
                    {"type": "tool_use", "id": "t-1", "name": "Bash", "input": {}},
                ]),
            ])
            self.assertEqual(_of_kind(_events_of(root), events.Turn), [])

    def test_a_record_holding_only_the_agents_own_thinking_is_not_a_turn(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [
                _message("assistant", [
                    {"type": "thinking", "thinking": "weighing it up", "signature": "s"},
                ]),
            ])
            self.assertEqual(_of_kind(_events_of(root), events.Turn), [])

    def test_a_record_that_speaks_alongside_a_tool_call_is_a_turn(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [
                _message("assistant", [
                    {"type": "text", "text": "running it now"},
                    {"type": "tool_use", "id": "t-1", "name": "Bash", "input": {}},
                ]),
            ])
            turns = _of_kind(_events_of(root), events.Turn)
            self.assertEqual([one.role for one in turns], ["assistant"])

    def test_the_turn_precedes_what_was_detected_inside_it(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [
                _message("assistant", [
                    {"type": "text", "text": "firing it"},
                    {"type": "tool_use", "name": "Skill", "input": {"skill": "commit"}},
                ]),
            ])
            collected = _events_of(root)
            kinds = [type(one) for one in collected]
            self.assertLess(kinds.index(events.Turn), kinds.index(events.SkillInvocation))


class TestSessionIdentity(unittest.TestCase):
    def test_the_project_is_the_directory_the_session_file_sits_in(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [_message("user", "hello")])
            identity = _of_kind(_events_of(root), events.SessionIdentity)
            self.assertEqual([one.project for one in identity], ["-w-notes"])

    def test_the_session_is_named_by_the_identifier_the_records_carry(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [_message("user", "hello")])
            identity = _of_kind(_events_of(root), events.SessionIdentity)
            self.assertEqual([one.session_id for one in identity], ["session-1"])

    def test_the_identity_is_announced_before_the_events_it_covers(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [_message("user", "hello")])
            collected = _events_of(root)
            self.assertIsInstance(collected[0], events.SessionIdentity)


class TestProjectFilter(unittest.TestCase):
    def test_only_the_named_project_is_read(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [_message("user", "kept")])
            _write_session(root, "-w-other", "a.jsonl", [_message("user", "dropped")])
            said = _of_kind(_events_of(root, project="-w-notes"), events.UserText)
            self.assertEqual([one.text for one in said], ["kept"])

    def test_a_project_whose_name_merely_extends_the_filter_is_not_read(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [_message("user", "kept")])
            _write_session(root, "-w-notes-archive", "a.jsonl", [_message("user", "dropped")])
            said = _of_kind(_events_of(root, project="-w-notes"), events.UserText)
            self.assertEqual([one.text for one in said], ["kept"])


class TestPeriod(unittest.TestCase):
    def test_a_record_written_before_the_period_is_left_out(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [
                _message("user", "old", timestamp=LONG_AGO),
                _message("user", "new", timestamp=NOW),
            ])
            said = _of_kind(_events_of(root, since=CUTOFF), events.UserText)
            self.assertEqual([one.text for one in said], ["new"])

    def test_a_file_left_out_by_its_write_time_contributes_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            stale = _write_session(root, "-w-notes", "stale.jsonl", [_message("user", "old")])
            stale_time = CUTOFF.timestamp() - 86400
            os.utime(stale, (stale_time, stale_time))
            self.assertEqual(_events_of(root, since=CUTOFF), [])


class TestUndatedRecords(unittest.TestCase):
    def test_a_record_that_cannot_be_dated_is_left_out_of_the_reading(self):
        with tempfile.TemporaryDirectory() as root:
            _write_session(root, "-w-notes", "a.jsonl", [
                {"type": "user", "sessionId": "session-1",
                 "message": {"role": "user", "content": "undated"}},
            ])
            collected = _events_of(root)
            self.assertEqual(_of_kind(collected, events.Turn), [])
            self.assertEqual(_of_kind(collected, events.UserText), [])


class TestMalformedInput(unittest.TestCase):
    def test_a_line_that_is_not_a_record_does_not_stop_the_reading(self):
        with tempfile.TemporaryDirectory() as root:
            directory = os.path.join(root, "-w-notes")
            os.makedirs(directory)
            with open(os.path.join(directory, "a.jsonl"), "w", encoding="utf-8") as handle:
                handle.write("{not json\n")
                handle.write("\n")
                handle.write(json.dumps(_message("user", "survived")) + "\n")
            said = _of_kind(_events_of(root), events.UserText)
            self.assertEqual([one.text for one in said], ["survived"])


class TestContainment(unittest.TestCase):
    def test_a_project_directory_linked_to_a_place_outside_the_root_is_refused(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            _write_session(outside, "-w-elsewhere", "a.jsonl", [_message("user", "leaked")])
            os.symlink(os.path.join(outside, "-w-elsewhere"), os.path.join(root, "-w-notes"))
            self.assertEqual(_events_of(root), [])

    def test_a_session_file_linked_to_a_place_outside_the_root_is_refused(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            leaked = _write_session(outside, "-w-elsewhere", "a.jsonl", [
                _message("user", "leaked"),
            ])
            directory = os.path.join(root, "-w-notes")
            os.makedirs(directory)
            os.symlink(leaked, os.path.join(directory, "a.jsonl"))
            self.assertEqual(_events_of(root), [])

    def test_a_missing_root_is_read_as_an_empty_store(self):
        with tempfile.TemporaryDirectory() as parent:
            self.assertEqual(_events_of(os.path.join(parent, "absent")), [])


if __name__ == "__main__":
    unittest.main()
