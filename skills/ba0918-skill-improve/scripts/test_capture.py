#!/usr/bin/env python3
"""Unit tests for capture.py.

Every repository and every store these tests read is assembled in a temporary
directory. The harvest writes message bodies, so a test of it must never be pointed
at the operator's own history or at a real working repository.

Sample paths are assembled rather than written whole: the self-containment lint
reads a rooted home path in any file as an escape from the skill directory.
"""

import contextlib
import datetime
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capture
import events
import store_claude

AT = datetime.datetime(2026, 8, 19, 12, 0, tzinfo=datetime.timezone.utc)
PROJECT = "-w-notes"
ALLOWED = (".agents", "tmp")


def _said(text, at=AT):
    return events.UserText(text=text, at=at)


def _fired(skill, route=events.ROUTE_STRUCTURAL):
    return events.SkillInvocation(skill=skill, route=route)


def _identity(session_id="s-1", project=PROJECT):
    return events.SessionIdentity(session_id=session_id, project=project)


def _repository(parent):
    """A repository whose allowed output directory is ignored by its own rules."""
    subprocess.run(["git", "init", "-q", parent], check=True, capture_output=True)
    with open(os.path.join(parent, ".gitignore"), "w", encoding="utf-8") as handle:
        handle.write(ALLOWED[0] + "/\n")
    allowed = os.path.join(parent, *ALLOWED)
    os.makedirs(allowed)
    return allowed


def _claude_root(parent, said="/claude-skills:commit please"):
    """A store of the first kind, holding one session with one utterance."""
    root = os.path.join(parent, "claude-store")
    directory = os.path.join(root, PROJECT)
    os.makedirs(directory, exist_ok=True)
    record = {
        "type": "user",
        "sessionId": "session-1",
        "timestamp": "2026-08-19T12:00:00.000Z",
        "message": {"role": "user", "content": said},
    }
    with open(os.path.join(directory, "a.jsonl"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    return root


class TestWhatOneRecordHolds(unittest.TestCase):
    def _one(self, *produced):
        return capture.capture_records(iter(produced))[0]

    def test_the_fields_of_a_record_are_the_ones_the_evaluation_reads(self):
        self.assertEqual(
            capture.RECORD_FIELDS,
            ("ts", "project", "user_text_masked", "fired_skill", "signals"),
        )

    def test_a_record_carries_those_fields_and_no_others(self):
        record = self._one(_identity(), _said("hello"))
        self.assertEqual(tuple(record), capture.RECORD_FIELDS)

    def test_the_record_is_timed_by_the_utterance_it_holds(self):
        self.assertEqual(self._one(_identity(), _said("hello"))["ts"], AT.isoformat())

    def test_the_record_names_the_project_the_session_ran_in(self):
        self.assertEqual(self._one(_identity(), _said("hello"))["project"], PROJECT)

    def test_an_utterance_outside_any_announced_session_still_becomes_a_record(self):
        self.assertEqual(self._one(_said("hello"))["project"], "")


class TestTheSignalsOnARecord(unittest.TestCase):
    def _signals(self, *produced):
        return [record["signals"] for record in capture.capture_records(iter(produced))]

    def test_the_signal_names_are_the_ones_the_evaluation_reads(self):
        self.assertEqual(capture.SLASH_FIRED, "slash_fired")
        self.assertEqual(capture.CORRECTION_AFTER_SKILL, "correction_after_skill")

    def test_an_utterance_firing_a_skill_by_slash_command_is_marked_as_firing_it(self):
        self.assertEqual(
            self._signals(_identity(), _said("/claude-skills:commit please")),
            [[capture.SLASH_FIRED]],
        )

    def test_the_skill_a_slash_command_fires_is_named_without_its_plugin(self):
        records = capture.capture_records(
            iter([_identity(), _said("/claude-skills:commit please")])
        )
        self.assertEqual(records[0]["fired_skill"], "commit")

    def test_an_utterance_after_a_skill_fired_is_marked_as_a_correction(self):
        self.assertEqual(
            self._signals(_identity(), _fired("commit"), _said("no, not like that")),
            [[capture.CORRECTION_AFTER_SKILL]],
        )

    def test_an_utterance_before_any_skill_fired_carries_no_signal(self):
        self.assertEqual(self._signals(_identity(), _said("hello")), [[]])

    def test_an_utterance_that_fires_a_skill_is_not_also_a_correction(self):
        self.assertEqual(
            self._signals(
                _identity(), _fired("commit"), _said("/claude-skills:plan-create instead")
            ),
            [[capture.SLASH_FIRED]],
        )

    def test_an_utterance_naming_no_skill_leaves_the_fired_skill_empty(self):
        records = capture.capture_records(iter([_identity(), _said("hello")]))
        self.assertIsNone(records[0]["fired_skill"])

    def test_a_new_session_forgets_the_skill_the_previous_one_fired(self):
        self.assertEqual(
            self._signals(
                _identity("s-1"), _fired("commit"),
                _identity("s-2"), _said("a fresh start"),
            ),
            [[]],
        )


class TestMasking(unittest.TestCase):
    def test_a_credential_in_an_utterance_is_masked_in_the_record(self):
        leaked = "AKIA" + "A1B2C3D4E5F6G7H8"
        records = capture.capture_records(
            iter([_identity(), _said("the key is " + leaked)])
        )
        self.assertNotIn(leaked, records[0]["user_text_masked"])
        self.assertIn("[REDACTED:aws_key]", records[0]["user_text_masked"])

    def test_what_the_operator_said_around_a_credential_survives_the_masking(self):
        leaked = "AKIA" + "A1B2C3D4E5F6G7H8"
        records = capture.capture_records(
            iter([_identity(), _said("the key is " + leaked)])
        )
        self.assertTrue(records[0]["user_text_masked"].startswith("the key is "))


class TestWhereTheOutputMayGo(unittest.TestCase):
    def test_a_path_inside_the_allowed_directory_is_accepted(self):
        with tempfile.TemporaryDirectory() as parent:
            allowed = os.path.join(parent, *ALLOWED)
            os.makedirs(allowed)
            wanted = os.path.join(allowed, "prompts.jsonl")
            self.assertEqual(
                capture.validate_output_path(wanted, pathlib.Path(allowed)),
                pathlib.Path(allowed).resolve() / "prompts.jsonl",
            )

    def test_a_path_outside_the_allowed_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as parent:
            allowed = os.path.join(parent, *ALLOWED)
            os.makedirs(allowed)
            self.assertIsNone(
                capture.validate_output_path(
                    os.path.join(parent, "prompts.jsonl"), pathlib.Path(allowed)
                )
            )

    def test_a_neighbour_whose_name_merely_extends_the_allowed_one_is_refused(self):
        with tempfile.TemporaryDirectory() as parent:
            allowed = os.path.join(parent, *ALLOWED)
            neighbour = os.path.join(parent, ALLOWED[0], ALLOWED[1] + "2")
            os.makedirs(allowed)
            os.makedirs(neighbour)
            self.assertIsNone(
                capture.validate_output_path(
                    os.path.join(neighbour, "prompts.jsonl"), pathlib.Path(allowed)
                )
            )

    def test_a_link_leading_out_of_the_allowed_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as parent:
            allowed = os.path.join(parent, *ALLOWED)
            outside = os.path.join(parent, "outside")
            os.makedirs(allowed)
            os.makedirs(outside)
            os.symlink(outside, os.path.join(allowed, "escape"))
            self.assertIsNone(
                capture.validate_output_path(
                    os.path.join(allowed, "escape", "prompts.jsonl"),
                    pathlib.Path(allowed),
                )
            )

    def test_a_path_whose_directory_does_not_exist_is_refused(self):
        with tempfile.TemporaryDirectory() as parent:
            allowed = os.path.join(parent, *ALLOWED)
            os.makedirs(allowed)
            self.assertIsNone(
                capture.validate_output_path(
                    os.path.join(allowed, "not-made-yet", "prompts.jsonl"),
                    pathlib.Path(allowed),
                )
            )

    def test_a_path_naming_a_directory_rather_than_a_file_is_refused(self):
        with tempfile.TemporaryDirectory() as parent:
            allowed = os.path.join(parent, *ALLOWED)
            os.makedirs(allowed)
            for degenerate in (allowed, os.path.join(allowed, "."), ""):
                self.assertIsNone(
                    capture.validate_output_path(degenerate, pathlib.Path(allowed)),
                    msg=degenerate,
                )


class TestTheGateOnWritingBodies(unittest.TestCase):
    def test_a_path_the_repository_ignores_may_be_written(self):
        with tempfile.TemporaryDirectory() as parent:
            allowed = _repository(parent)
            self.assertTrue(
                capture.output_is_git_ignored(pathlib.Path(allowed) / "prompts.jsonl")
            )

    def test_a_path_the_repository_does_not_ignore_is_refused(self):
        with tempfile.TemporaryDirectory() as parent:
            _repository(parent)
            tracked = os.path.join(parent, "tracked")
            os.makedirs(tracked)
            self.assertFalse(
                capture.output_is_git_ignored(pathlib.Path(tracked) / "prompts.jsonl")
            )

    def test_a_path_no_repository_can_judge_is_refused(self):
        with tempfile.TemporaryDirectory() as parent:
            self.assertFalse(
                capture.output_is_git_ignored(pathlib.Path(parent) / "prompts.jsonl")
            )

    def test_a_path_no_repository_can_judge_is_refused_with_something_to_act_on(self):
        with tempfile.TemporaryDirectory() as parent:
            complaint = io.StringIO()
            with contextlib.redirect_stderr(complaint):
                capture.output_is_git_ignored(pathlib.Path(parent) / "prompts.jsonl")
            self.assertIn("GIT_CONFIG_GLOBAL", complaint.getvalue())


class TestWritingTheHarvest(unittest.TestCase):
    def _records(self):
        return capture.capture_records(iter([_identity(), _said("hello"), _said("again")]))

    def test_every_record_is_written_as_one_line_of_its_own(self):
        with tempfile.TemporaryDirectory() as parent:
            path = pathlib.Path(parent) / "prompts.jsonl"
            capture.write_records(self._records(), path)
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["user_text_masked"], "hello")

    def test_a_harvest_written_over_an_earlier_one_leaves_no_half_written_file(self):
        with tempfile.TemporaryDirectory() as parent:
            path = pathlib.Path(parent) / "prompts.jsonl"
            capture.write_records(self._records(), path)
            capture.write_records(self._records(), path)
            self.assertFalse(os.path.exists(str(path) + ".tmp"))
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 2)


class TestARunOfTheHarvest(unittest.TestCase):
    def _argv(self, parent, output):
        return [
            "--output", output,
            "--all-projects",
            "--store", store_claude.NAME,
            "--claude-root", _claude_root(parent),
            "--codex-root", os.path.join(parent, "no-codex-store"),
            "--opencode-db", os.path.join(parent, "no-opencode-store.db"),
        ]

    def test_a_run_writes_the_harvest_where_it_was_told_to(self):
        with tempfile.TemporaryDirectory() as parent:
            allowed = _repository(parent)
            output = os.path.join(allowed, "prompts.jsonl")
            with contextlib.chdir(parent), contextlib.redirect_stderr(io.StringIO()):
                code = capture.main(self._argv(parent, output))
            self.assertEqual(code, 0)
            written = json.loads(pathlib.Path(output).read_text(encoding="utf-8"))
            self.assertEqual(written["fired_skill"], "commit")
            self.assertEqual(written["signals"], [capture.SLASH_FIRED])

    def test_a_run_refuses_an_output_outside_the_allowed_directory(self):
        with tempfile.TemporaryDirectory() as parent:
            _repository(parent)
            output = os.path.join(parent, "prompts.jsonl")
            with contextlib.chdir(parent), contextlib.redirect_stderr(io.StringIO()):
                code = capture.main(self._argv(parent, output))
            self.assertNotEqual(code, 0)
            self.assertFalse(os.path.exists(output))

    def test_a_run_refuses_an_output_the_repository_does_not_ignore(self):
        with tempfile.TemporaryDirectory() as parent:
            allowed = _repository(parent)
            with open(os.path.join(parent, ".gitignore"), "w", encoding="utf-8") as handle:
                handle.write("nothing-here\n")
            output = os.path.join(allowed, "prompts.jsonl")
            with contextlib.chdir(parent), contextlib.redirect_stderr(io.StringIO()):
                code = capture.main(self._argv(parent, output))
            self.assertNotEqual(code, 0)
            self.assertFalse(os.path.exists(output))

    def test_a_run_that_was_told_no_output_refuses_rather_than_choosing_one(self):
        with tempfile.TemporaryDirectory() as parent:
            _repository(parent)
            argv = [
                argument
                for argument in self._argv(parent, "unused")
                if argument not in ("--output", "unused")
            ]
            with contextlib.chdir(parent), contextlib.redirect_stderr(io.StringIO()):
                self.assertNotEqual(capture.main(argv), 0)


if __name__ == "__main__":
    unittest.main()
