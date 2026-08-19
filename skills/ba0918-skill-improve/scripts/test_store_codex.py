#!/usr/bin/env python3
"""Unit tests for store_codex.py.

Every rollout log these tests read is assembled in a temporary directory, for the
same reason the other adapters' tests are: the real store holds the operator's own
history.

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
import store_codex

SEPARATOR = "/"
NOW = "2026-08-19T12:00:00.000Z"
LONG_AGO = "2026-01-01T00:00:00.000Z"
CUTOFF = datetime.datetime(2026, 8, 1, tzinfo=datetime.timezone.utc)
WORKTREE = SEPARATOR + SEPARATOR.join(("w", "notes"))
WORKTREE_KEY = "-w-notes"
DATED = ("2026", "08", "19")
ROLLOUT = "rollout-2026-08-19T12-00-00-0000.jsonl"


def _record(kind, payload, timestamp=NOW):
    return {"timestamp": timestamp, "type": kind, "payload": payload}


def _session_meta(cwd=WORKTREE, identifier="rollout-1", timestamp=NOW):
    return _record("session_meta", {
        "id": identifier,
        "session_id": identifier,
        "cwd": cwd,
        "cli_version": "1.0.0",
        "originator": "cli",
        "source": "cli",
        "timestamp": timestamp,
    }, timestamp=timestamp)


def _typed_user_message(text, timestamp=NOW):
    return _record("event_msg", {"type": "user_message", "message": text},
                   timestamp=timestamp)


def _agent_message(text, timestamp=NOW):
    return _record("event_msg", {"type": "agent_message", "message": text},
                   timestamp=timestamp)


def _item_message(role, text, timestamp=NOW, block="input_text"):
    return _record("response_item", {
        "type": "message",
        "role": role,
        "content": [{"type": block, "text": text}],
    }, timestamp=timestamp)


def _function_call(name, call_id="call-1", timestamp=NOW):
    return _record("response_item", {
        "type": "function_call",
        "name": name,
        "call_id": call_id,
        "arguments": "{}",
    }, timestamp=timestamp)


def _command_end(exit_code, call_id="call-1", command=("ls",), timestamp=NOW):
    return _record("event_msg", {
        "type": "exec_command_end",
        "call_id": call_id,
        "command": list(command),
        "cwd": WORKTREE,
        "duration": 1,
        "exit_code": exit_code,
        "formatted_output": "",
        "parsed_cmd": [],
        "process_id": 1,
        "source": "exec",
        "status": "completed" if exit_code == 0 else "failed",
        "stderr": "",
        "stdout": "",
        "turn_id": "t-1",
    }, timestamp=timestamp)


def _write_rollout(root, records, dated=DATED, filename=ROLLOUT):
    directory = os.path.join(root, *dated)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, filename)
    with open(path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    return path


def _events_of(root, **kwargs):
    return list(store_codex.CodexStore(root=root, **kwargs).events())


def _of_kind(collected, kind):
    return [event for event in collected if isinstance(event, kind)]


class TestDeclaredCapabilities(unittest.TestCase):
    def test_the_store_reads_the_text_route(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertTrue(store_codex.CodexStore(root=root).capabilities.text)

    def test_the_store_declares_that_it_cannot_read_the_structural_route(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertFalse(store_codex.CodexStore(root=root).capabilities.structural)

    def test_the_store_satisfies_the_adapter_contract(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertIsInstance(store_codex.CodexStore(root=root), events.SessionStore)


class TestDefaultLocation(unittest.TestCase):
    def test_the_default_location_is_the_runtime_session_directory_under_the_home(self):
        default = store_codex.default_root()
        self.assertEqual(default.name, "sessions")
        self.assertEqual(default.parent.name, "." + "codex")
        self.assertEqual(default.parent.parent, store_codex.pathlib.Path.home())


class TestSessionIdentity(unittest.TestCase):
    def test_the_working_directory_becomes_the_key_the_other_stores_meet_on(self):
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [_session_meta(cwd=WORKTREE)])
            identity = _of_kind(_events_of(root), events.SessionIdentity)
            self.assertEqual([one.project for one in identity], [WORKTREE_KEY])

    def test_the_session_is_named_by_the_identifier_the_opening_record_carries(self):
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [_session_meta(identifier="rollout-9")])
            identity = _of_kind(_events_of(root), events.SessionIdentity)
            self.assertEqual([one.session_id for one in identity], ["rollout-9"])

    def test_the_identity_is_announced_before_the_events_it_covers(self):
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [_session_meta(), _typed_user_message("hello")])
            self.assertIsInstance(_events_of(root)[0], events.SessionIdentity)

    def test_a_log_naming_no_working_directory_is_still_read(self):
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [_typed_user_message("hello")])
            said = _of_kind(_events_of(root), events.UserText)
            self.assertEqual([one.text for one in said], ["hello"])


class TestUserUtterances(unittest.TestCase):
    def test_what_the_operator_typed_is_read_as_an_utterance(self):
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [_session_meta(), _typed_user_message("hello")])
            said = _of_kind(_events_of(root), events.UserText)
            self.assertEqual([one.text for one in said], ["hello"])

    def test_an_utterance_recorded_as_content_blocks_is_read(self):
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [_session_meta(), _item_message("user", "hello")])
            said = _of_kind(_events_of(root), events.UserText)
            self.assertEqual([one.text for one in said], ["hello"])

    def test_an_instruction_the_harness_wrote_is_not_read_as_an_utterance(self):
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [_session_meta(), _item_message("developer", "context")])
            collected = _events_of(root)
            self.assertEqual(_of_kind(collected, events.UserText), [])
            self.assertEqual(_of_kind(collected, events.Turn), [])


class TestOneConversationRecordedTwice(unittest.TestCase):
    def test_an_utterance_present_in_both_recordings_is_counted_once(self):
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [
                _session_meta(),
                _typed_user_message("hello"),
                _item_message("user", "hello"),
                _agent_message("answering"),
                _item_message("assistant", "answering", block="output_text"),
            ])
            collected = _events_of(root)
            self.assertEqual([one.text for one in _of_kind(collected, events.UserText)],
                             ["hello"])
            self.assertEqual([one.role for one in _of_kind(collected, events.Turn)],
                             ["user", "assistant"])

    def test_a_slash_command_present_in_both_recordings_fires_once(self):
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [
                _session_meta(),
                _typed_user_message("/claude-skills:commit please"),
                _item_message("user", "/claude-skills:commit please"),
            ])
            found = _of_kind(_events_of(root), events.SkillInvocation)
            self.assertEqual(
                found, [events.SkillInvocation(skill="commit", route=events.ROUTE_TEXT)]
            )

    def test_the_typed_recording_is_the_one_read_where_a_log_holds_both(self):
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [
                _session_meta(),
                _typed_user_message("hello"),
                _item_message("user", "hello"),
                _item_message("user", "output of a tool the harness ran"),
            ])
            said = _of_kind(_events_of(root), events.UserText)
            self.assertEqual([one.text for one in said], ["hello"])

    def test_a_log_holding_the_typed_recording_reads_no_superset_of_utterances(self):
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [
                _session_meta(),
                _typed_user_message("hello"),
                _item_message("user", "output of a tool the harness ran"),
            ])
            identity = _of_kind(_events_of(root), events.SessionIdentity)
            self.assertFalse(identity[0].utterances_are_superset)

    def test_a_log_without_the_typed_recording_says_its_utterances_are_a_superset(self):
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [_session_meta(), _item_message("user", "hello")])
            identity = _of_kind(_events_of(root), events.SessionIdentity)
            self.assertTrue(identity[0].utterances_are_superset)

    def test_a_log_holding_only_the_typed_recording_is_read_from_it(self):
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [
                _session_meta(),
                _typed_user_message("hello"),
                _agent_message("answering"),
            ])
            collected = _events_of(root)
            self.assertEqual([one.text for one in _of_kind(collected, events.UserText)],
                             ["hello"])
            self.assertEqual([one.role for one in _of_kind(collected, events.Turn)],
                             ["user", "assistant"])


class TestTurns(unittest.TestCase):
    def test_a_message_by_either_side_is_one_turn(self):
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [
                _session_meta(),
                _item_message("user", "ask"),
                _item_message("assistant", "answer", block="output_text"),
            ])
            turns = _of_kind(_events_of(root), events.Turn)
            self.assertEqual([one.role for one in turns], ["user", "assistant"])

    def test_a_record_that_is_not_a_message_is_not_a_turn(self):
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [
                _session_meta(),
                _record("event_msg", {"type": "token_count", "info": {}}),
                _record("response_item", {"type": "reasoning", "summary": []}),
                _record("turn_context", {"cwd": WORKTREE, "model": "a-model"}),
            ])
            self.assertEqual(_of_kind(_events_of(root), events.Turn), [])


class TestTextRoute(unittest.TestCase):
    def test_a_slash_command_in_an_utterance_is_detected_as_a_text_invocation(self):
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [
                _session_meta(), _typed_user_message("/claude-skills:commit please"),
            ])
            found = _of_kind(_events_of(root), events.SkillInvocation)
            self.assertEqual(
                found, [events.SkillInvocation(skill="commit", route=events.ROUTE_TEXT)]
            )


class TestNoStructuralRoute(unittest.TestCase):
    def test_a_command_naming_a_skill_directory_is_not_read_as_a_skill_firing(self):
        touched = SEPARATOR.join(("skills", "ba0918-commit", "SKILL.md"))
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [
                _session_meta(),
                _function_call("exec"),
                _record("response_item", {
                    "type": "function_call",
                    "name": "exec",
                    "call_id": "call-2",
                    "arguments": json.dumps({"command": ["cat", touched]}),
                }),
                _command_end(0, call_id="call-2", command=("cat", touched)),
            ])
            self.assertEqual(_of_kind(_events_of(root), events.SkillInvocation), [])

    def test_a_tool_call_is_not_read_as_a_skill_firing_whatever_it_is_named(self):
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [_session_meta(), _function_call("spawn_agent")])
            self.assertEqual(_of_kind(_events_of(root), events.SkillInvocation), [])


class TestToolErrors(unittest.TestCase):
    def test_a_command_ending_in_a_non_zero_status_counts_as_a_tool_error(self):
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [_session_meta(), _command_end(1)])
            self.assertEqual(len(_of_kind(_events_of(root), events.ToolError)), 1)

    def test_a_command_ending_in_success_is_not_a_tool_error(self):
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [_session_meta(), _command_end(0)])
            self.assertEqual(_of_kind(_events_of(root), events.ToolError), [])

    def test_the_error_names_the_tool_whose_call_it_answers(self):
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [
                _session_meta(), _function_call("exec_command", call_id="call-7"),
                _command_end(2, call_id="call-7"),
            ])
            failed = _of_kind(_events_of(root), events.ToolError)
            self.assertEqual([one.tool for one in failed], ["exec_command"])

    def test_an_error_answering_no_recorded_call_is_still_counted(self):
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [_session_meta(), _command_end(1, call_id="unseen")])
            failed = _of_kind(_events_of(root), events.ToolError)
            self.assertEqual([one.tool for one in failed], [store_codex.UNNAMED_TOOL])

    def test_a_failure_written_into_a_call_output_body_is_not_read_as_an_error(self):
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [
                _session_meta(),
                _function_call("exec", call_id="call-3"),
                _record("response_item", {
                    "type": "function_call_output",
                    "call_id": "call-3",
                    "output": "error: command failed with exit code 1",
                }),
                _record("response_item", {
                    "type": "custom_tool_call_output",
                    "call_id": "call-3",
                    "output": ["error: it failed"],
                }),
            ])
            self.assertEqual(_of_kind(_events_of(root), events.ToolError), [])


class TestAbandonedTurn(unittest.TestCase):
    def test_an_aborted_turn_is_not_read_as_a_tool_failure(self):
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [
                _session_meta(),
                _record("event_msg", {
                    "type": "turn_aborted",
                    "reason": "interrupted",
                    "turn_id": "t-1",
                    "started_at": NOW,
                    "completed_at": NOW,
                    "duration_ms": 10,
                }),
            ])
            collected = _events_of(root)
            self.assertEqual(_of_kind(collected, events.ToolError), [])
            self.assertEqual(_of_kind(collected, events.Turn), [])


class TestProjectFilter(unittest.TestCase):
    def test_only_the_named_project_is_read(self):
        other = SEPARATOR + SEPARATOR.join(("w", "other"))
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [_session_meta(cwd=WORKTREE), _typed_user_message("kept")])
            _write_rollout(root, [_session_meta(cwd=other), _typed_user_message("dropped")],
                           filename="rollout-2026-08-19T13-00-00-0001.jsonl")
            said = _of_kind(_events_of(root, project=WORKTREE_KEY), events.UserText)
            self.assertEqual([one.text for one in said], ["kept"])

    def test_a_project_whose_key_merely_extends_the_filter_is_not_read(self):
        extended = SEPARATOR + SEPARATOR.join(("w", "notes", "archive"))
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [_session_meta(cwd=WORKTREE), _typed_user_message("kept")])
            _write_rollout(root, [_session_meta(cwd=extended), _typed_user_message("dropped")],
                           filename="rollout-2026-08-19T13-00-00-0001.jsonl")
            said = _of_kind(_events_of(root, project=WORKTREE_KEY), events.UserText)
            self.assertEqual([one.text for one in said], ["kept"])


class TestPeriod(unittest.TestCase):
    def test_a_record_written_before_the_period_is_left_out(self):
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [
                _session_meta(),
                _typed_user_message("old", timestamp=LONG_AGO),
                _typed_user_message("new"),
            ])
            said = _of_kind(_events_of(root, since=CUTOFF), events.UserText)
            self.assertEqual([one.text for one in said], ["new"])

    def test_a_file_left_out_by_its_write_time_contributes_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            stale = _write_rollout(root, [_session_meta(), _typed_user_message("old")])
            stale_time = CUTOFF.timestamp() - 86400
            os.utime(stale, (stale_time, stale_time))
            self.assertEqual(_events_of(root, since=CUTOFF), [])


class TestDatedDirectories(unittest.TestCase):
    def test_logs_are_found_wherever_the_date_directories_put_them(self):
        with tempfile.TemporaryDirectory() as root:
            _write_rollout(root, [_session_meta(), _typed_user_message("first")],
                           dated=("2026", "08", "18"))
            _write_rollout(root, [_session_meta(), _typed_user_message("second")],
                           dated=("2026", "08", "19"))
            said = _of_kind(_events_of(root), events.UserText)
            self.assertEqual(sorted(one.text for one in said), ["first", "second"])


class TestMalformedInput(unittest.TestCase):
    def test_a_line_that_is_not_a_record_does_not_stop_the_reading(self):
        with tempfile.TemporaryDirectory() as root:
            directory = os.path.join(root, *DATED)
            os.makedirs(directory)
            with open(os.path.join(directory, ROLLOUT), "w", encoding="utf-8") as handle:
                handle.write("{not json\n")
                handle.write("\n")
                handle.write(json.dumps(_typed_user_message("survived")) + "\n")
            said = _of_kind(_events_of(root), events.UserText)
            self.assertEqual([one.text for one in said], ["survived"])


class TestContainment(unittest.TestCase):
    def test_a_log_linked_to_a_place_outside_the_root_is_refused(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            leaked = _write_rollout(outside, [_session_meta(), _typed_user_message("leaked")])
            directory = os.path.join(root, *DATED)
            os.makedirs(directory)
            os.symlink(leaked, os.path.join(directory, ROLLOUT))
            self.assertEqual(_events_of(root), [])

    def test_a_missing_root_is_read_as_an_empty_store(self):
        with tempfile.TemporaryDirectory() as parent:
            self.assertEqual(_events_of(os.path.join(parent, "absent")), [])


if __name__ == "__main__":
    unittest.main()
