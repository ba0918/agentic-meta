#!/usr/bin/env python3
"""Unit tests for collect.py.

Every store these tests read is assembled in a temporary directory. The real ones
hold the operator's own history, so reading them here would make the tests depend
on data no one can inspect.

Sample paths are assembled rather than written whole: the self-containment lint
reads a rooted home path in any file as an escape from the skill directory.
"""

import contextlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import collect
import store_claude
import store_codex
import store_opencode

NOW = "2026-08-19T12:00:00.000Z"
LONG_AGO = "2026-01-01T00:00:00.000Z"
PROJECT = "-w-notes"
OPERATOR = "someone"
HOME_PROJECT = "-".join(("", "home", OPERATOR, "develop", "notes"))
SEPARATOR = "/"
WORKTREE = SEPARATOR + SEPARATOR.join(("w", "notes"))


def _claude_record(role, content, timestamp=NOW):
    return {
        "type": role,
        "sessionId": "session-1",
        "timestamp": timestamp,
        "message": {"role": role, "content": content},
    }


def _claude_root(parent, records=None, project=PROJECT, name="claude-store"):
    """A store of the first kind, holding one session of the given records."""
    root = os.path.join(parent, name)
    directory = os.path.join(root, project)
    os.makedirs(directory, exist_ok=True)
    if records is None:
        records = [
            _claude_record("user", "please commit"),
            _claude_record("assistant", [
                {"type": "text", "text": "firing it"},
                {"type": "tool_use", "name": "Skill", "input": {"skill": "commit"}},
            ]),
        ]
    with open(os.path.join(directory, "a.jsonl"), "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    return root


def _codex_root(parent, said="/claude-skills:commit please", name="codex-store"):
    """A store of the third kind, holding one session with one typed utterance."""
    root = os.path.join(parent, name)
    directory = os.path.join(root, "2026", "08", "19")
    os.makedirs(directory, exist_ok=True)
    records = [
        {"timestamp": NOW, "type": "session_meta",
         "payload": {"id": "rollout-1", "session_id": "rollout-1", "cwd": WORKTREE}},
        {"timestamp": NOW, "type": "event_msg",
         "payload": {"type": "user_message", "message": said}},
    ]
    path = os.path.join(directory, "rollout-2026-08-19T12-00-00-0000.jsonl")
    with open(path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    return root


def _codex_mirrored_root(parent, said="hello", name="codex-mirrored"):
    """A store of the third kind holding no record of the operator having typed.

    Its utterances can only be read from the recording that also carries tool
    output, so the session it holds is one whose utterances are a superset.
    """
    root = os.path.join(parent, name)
    directory = os.path.join(root, "2026", "08", "19")
    os.makedirs(directory, exist_ok=True)
    records = [
        {"timestamp": NOW, "type": "session_meta",
         "payload": {"id": "rollout-2", "session_id": "rollout-2", "cwd": WORKTREE}},
        {"timestamp": NOW, "type": "response_item",
         "payload": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": said}]}},
    ]
    path = os.path.join(directory, "rollout-2026-08-19T13-00-00-0000.jsonl")
    with open(path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    return root


def _run(parent, *arguments, claude=None, codex=None, opencode=None):
    """Run the collector over the given stores and read back what it wrote.

    Every store is pointed somewhere inside the temporary directory, including the
    ones a test does not care about. A store left unpointed would fall back to its
    own location under the operator's home, and the test would then be reading the
    operator's real history.
    """
    output = os.path.join(parent, "friction.json")
    argv = [
        "--output", output, "--all-projects",
        "--claude-root", claude or os.path.join(parent, "no-claude-store"),
        "--codex-root", codex or os.path.join(parent, "no-codex-store"),
        "--opencode-db", opencode or os.path.join(parent, "no-opencode-store.db"),
    ]
    argv += list(arguments)
    code = collect.main(argv)
    with open(output, "r", encoding="utf-8") as handle:
        return code, json.load(handle)


class TestWhichStoresAreRead(unittest.TestCase):
    def test_the_store_named_is_the_only_one_read(self):
        with tempfile.TemporaryDirectory() as parent:
            _, result = _run(
                parent, "--store", store_codex.NAME,
                claude=_claude_root(parent), codex=_codex_root(parent),
            )
            self.assertEqual(list(result["summary"]["stores"]), [store_codex.NAME])

    def test_every_store_is_read_when_all_of_them_are_asked_for(self):
        with tempfile.TemporaryDirectory() as parent:
            _, result = _run(
                parent, "--store", "all",
                claude=_claude_root(parent), codex=_codex_root(parent),
            )
            self.assertEqual(
                sorted(result["summary"]["stores"]),
                sorted((store_claude.NAME, store_opencode.NAME, store_codex.NAME)),
            )

    def test_every_store_is_read_when_none_is_named(self):
        with tempfile.TemporaryDirectory() as parent:
            _, result = _run(parent, claude=_claude_root(parent))
            self.assertEqual(len(result["summary"]["stores"]), 3)

    def test_a_name_no_store_answers_to_is_refused_rather_than_read_as_empty(self):
        with tempfile.TemporaryDirectory() as parent:
            output = os.path.join(parent, "friction.json")
            self.assertNotEqual(
                collect.main(["--store", "mystery", "--output", output]), 0
            )
            self.assertFalse(os.path.exists(output))


class TestWhereEachStoreIsRead(unittest.TestCase):
    def test_the_location_of_each_store_can_be_given_as_an_argument(self):
        with tempfile.TemporaryDirectory() as parent:
            claude = _claude_root(parent)
            codex = _codex_root(parent)
            database = os.path.join(parent, "opencode.db")
            _, result = _run(parent, claude=claude, codex=codex, opencode=database)
            read = result["summary"]["stores"]
            self.assertEqual(read[store_claude.NAME]["location"], claude)
            self.assertEqual(read[store_codex.NAME]["location"], codex)
            self.assertEqual(read[store_opencode.NAME]["location"], database)

    def test_what_the_named_location_holds_is_what_gets_counted(self):
        with tempfile.TemporaryDirectory() as parent:
            _, result = _run(parent, "--store", store_claude.NAME,
                             claude=_claude_root(parent))
            self.assertEqual(result["summary"]["unique_skills_used"], ["commit"])


class TestAStoreThatIsNotThere(unittest.TestCase):
    def _missing_codex(self, parent):
        return _run(
            parent, claude=_claude_root(parent),
            codex=os.path.join(parent, "no-such-store"),
        )

    def test_a_store_that_is_not_there_does_not_stop_the_run(self):
        with tempfile.TemporaryDirectory() as parent:
            code, result = self._missing_codex(parent)
            self.assertEqual(code, 0)
            self.assertEqual(result["summary"]["unique_skills_used"], ["commit"])

    def test_a_store_that_is_not_there_is_reported_as_absent(self):
        with tempfile.TemporaryDirectory() as parent:
            _, result = self._missing_codex(parent)
            self.assertFalse(result["summary"]["stores"][store_codex.NAME]["present"])

    def test_a_store_that_is_not_there_is_named_in_the_notes(self):
        with tempfile.TemporaryDirectory() as parent:
            _, result = self._missing_codex(parent)
            self.assertTrue(
                any(store_codex.NAME in note for note in result["notes"]),
                msg=result["notes"],
            )

    def test_a_store_that_is_there_is_reported_as_present(self):
        with tempfile.TemporaryDirectory() as parent:
            _, result = self._missing_codex(parent)
            self.assertTrue(result["summary"]["stores"][store_claude.NAME]["present"])


class TestAStoreThatIsThereAndCannotBeRead(unittest.TestCase):
    def _over(self, parent, database):
        return _run(parent, claude=_claude_root(parent), opencode=database)

    def _not_a_database(self, parent):
        database = os.path.join(parent, "opencode.db")
        with open(database, "w", encoding="utf-8") as handle:
            handle.write("this is not a database at all\n")
        return database

    def _database_without_sessions(self, parent):
        database = os.path.join(parent, "opencode.db")
        connection = sqlite3.connect(database)
        connection.execute("CREATE TABLE something_else (id TEXT)")
        connection.commit()
        connection.close()
        return database

    def test_a_location_holding_no_database_does_not_stop_the_other_stores(self):
        with tempfile.TemporaryDirectory() as parent:
            code, result = self._over(parent, self._not_a_database(parent))
            self.assertEqual(code, 0)
            self.assertEqual(result["summary"]["unique_skills_used"], ["commit"])

    def test_a_database_holding_no_sessions_does_not_stop_the_other_stores(self):
        with tempfile.TemporaryDirectory() as parent:
            code, result = self._over(parent, self._database_without_sessions(parent))
            self.assertEqual(code, 0)
            self.assertEqual(result["summary"]["unique_skills_used"], ["commit"])

    def test_a_store_that_could_not_be_read_is_named_in_the_notes(self):
        with tempfile.TemporaryDirectory() as parent:
            _, result = self._over(parent, self._not_a_database(parent))
            self.assertTrue(
                any(store_opencode.NAME in note for note in result["notes"]),
                msg=result["notes"],
            )

    def test_a_store_that_could_not_be_read_is_not_reported_as_absent(self):
        with tempfile.TemporaryDirectory() as parent:
            _, result = self._over(parent, self._not_a_database(parent))
            self.assertTrue(result["summary"]["stores"][store_opencode.NAME]["present"])


class TestWhatEachStoreCouldBeReadFor(unittest.TestCase):
    def _read(self, parent):
        return _run(parent, claude=_claude_root(parent), codex=_codex_root(parent))[1]

    def test_the_routes_each_store_can_be_read_along_are_reported(self):
        with tempfile.TemporaryDirectory() as parent:
            read = self._read(parent)["summary"]["stores"]
            self.assertTrue(read[store_claude.NAME]["structural_route"])
            self.assertFalse(read[store_codex.NAME]["structural_route"])
            self.assertTrue(read[store_codex.NAME]["text_route"])

    def test_a_store_recording_abandonment_itself_is_reported_as_recording_it(self):
        with tempfile.TemporaryDirectory() as parent:
            read = self._read(parent)["summary"]["stores"]
            self.assertEqual(read[store_codex.NAME]["abandonment"],
                             collect.ABANDONMENT_RECORDED)

    def test_a_store_with_no_such_record_is_reported_as_having_it_inferred(self):
        with tempfile.TemporaryDirectory() as parent:
            read = self._read(parent)["summary"]["stores"]
            self.assertEqual(read[store_claude.NAME]["abandonment"],
                             collect.ABANDONMENT_INFERRED)

    def test_a_store_whose_error_detection_has_a_limit_is_reported_as_partial(self):
        with tempfile.TemporaryDirectory() as parent:
            read = self._read(parent)["summary"]["stores"]
            self.assertEqual(read[store_codex.NAME]["error_detection"],
                             collect.ERROR_DETECTION_PARTIAL)

    def test_a_store_reading_every_failure_it_holds_is_reported_as_full(self):
        with tempfile.TemporaryDirectory() as parent:
            read = self._read(parent)["summary"]["stores"]
            self.assertEqual(read[store_claude.NAME]["error_detection"],
                             collect.ERROR_DETECTION_FULL)

    def test_a_store_reading_only_real_utterances_counts_no_superset_session(self):
        with tempfile.TemporaryDirectory() as parent:
            read = self._read(parent)["summary"]["stores"]
            self.assertEqual(read[store_codex.NAME]["superset_utterance_sessions"], 0)

    def test_a_session_read_as_a_superset_of_what_was_said_is_counted_per_store(self):
        with tempfile.TemporaryDirectory() as parent:
            _, result = _run(parent, "--store", store_codex.NAME,
                             codex=_codex_mirrored_root(parent))
            self.assertEqual(
                result["summary"]["stores"][store_codex.NAME][
                    "superset_utterance_sessions"
                ],
                1,
            )

    def test_a_session_read_that_way_says_so_on_its_own_row(self):
        with tempfile.TemporaryDirectory() as parent:
            _, result = _run(parent, "--store", store_codex.NAME,
                             codex=_codex_mirrored_root(parent))
            self.assertTrue(result["sessions"][0]["utterances_are_superset"])

    def test_a_skill_seen_only_where_no_structure_is_read_carries_the_downgrade(self):
        with tempfile.TemporaryDirectory() as parent:
            _, result = _run(parent, "--store", store_codex.NAME,
                             codex=_codex_root(parent))
            self.assertTrue(result["friction_signals"]["commit"]["confidence_downgraded"])
            self.assertEqual(
                result["friction_signals"]["commit"]["stores_without_structural"],
                [store_codex.NAME],
            )


class TestWhenNothingFiredASkill(unittest.TestCase):
    def _nothing_fired(self, parent):
        records = [_claude_record("user", "just chatting")]
        return _run(parent, "--store", store_claude.NAME,
                    claude=_claude_root(parent, records))

    def test_a_run_that_found_no_firing_says_the_analysis_should_not_go_on(self):
        with tempfile.TemporaryDirectory() as parent:
            _, result = self._nothing_fired(parent)
            self.assertFalse(result["analysis"]["proceed"])

    def test_a_run_that_found_no_firing_says_why_the_analysis_should_not_go_on(self):
        with tempfile.TemporaryDirectory() as parent:
            _, result = self._nothing_fired(parent)
            self.assertTrue(result["analysis"]["reason"])

    def test_a_run_that_found_no_firing_still_reports_what_it_read(self):
        with tempfile.TemporaryDirectory() as parent:
            _, result = self._nothing_fired(parent)
            self.assertEqual(result["summary"]["total_skill_invocations"], 0)
            self.assertEqual(result["summary"]["sessions_found"], 1)

    def test_a_run_that_found_a_firing_lets_the_analysis_go_on(self):
        with tempfile.TemporaryDirectory() as parent:
            _, result = _run(parent, "--store", store_claude.NAME,
                             claude=_claude_root(parent))
            self.assertTrue(result["analysis"]["proceed"])
            self.assertIsNone(result["analysis"]["reason"])


class TestFrictionReported(unittest.TestCase):
    def test_each_skill_is_reported_with_the_counts_the_score_is_built_from(self):
        with tempfile.TemporaryDirectory() as parent:
            _, result = _run(parent, "--store", store_claude.NAME,
                             claude=_claude_root(parent))
            reported = result["friction_signals"]["commit"]
            self.assertEqual(reported["invocation_count"], 1)
            for counted in ("retry_count", "correction_turns", "tool_error_count",
                            "session_abandoned_count", "total_turns_to_completion"):
                self.assertIn(counted, reported)

    def test_the_stores_whose_abandonment_was_inferred_are_named_per_skill(self):
        with tempfile.TemporaryDirectory() as parent:
            _, result = _run(parent, "--store", store_claude.NAME,
                             claude=_claude_root(parent))
            self.assertEqual(
                result["friction_signals"]["commit"]["stores_with_inferred_abandonment"],
                [store_claude.NAME],
            )


class TestOneFiringSeenOnBothRoutes(unittest.TestCase):
    def _both_routes(self, parent):
        """A session where the operator typed the command and the tool call followed."""
        records = [
            _claude_record("user", "run /demo:tidy-up on this repo"),
            _claude_record("assistant", [
                {"type": "tool_use", "name": "Skill", "input": {"skill": "demo:tidy-up"}},
            ]),
        ]
        return _run(parent, "--store", store_claude.NAME,
                    claude=_claude_root(parent, records))[1]

    def test_a_command_typed_and_the_tool_call_it_produced_are_counted_once(self):
        with tempfile.TemporaryDirectory() as parent:
            reported = self._both_routes(parent)["friction_signals"]["tidy-up"]
            self.assertEqual(reported["invocation_count"], 1)
            self.assertEqual(reported["retry_count"], 0)

    def test_the_measurement_says_how_many_firings_both_routes_showed(self):
        with tempfile.TemporaryDirectory() as parent:
            reported = self._both_routes(parent)["friction_signals"]["tidy-up"]
            self.assertEqual(reported["merged_route_pairs"], 1)


class TestSessionsReported(unittest.TestCase):
    def test_the_sessions_read_are_reported_without_anything_naming_them(self):
        with tempfile.TemporaryDirectory() as parent:
            _, result = _run(parent, "--store", store_claude.NAME,
                             claude=_claude_root(parent))
            self.assertEqual(len(result["sessions"]), 1)
            for named in result["sessions"]:
                self.assertNotIn("session_id", named)
                self.assertNotIn("file", named)

    def test_each_session_reports_what_it_showed(self):
        with tempfile.TemporaryDirectory() as parent:
            _, result = _run(parent, "--store", store_claude.NAME,
                             claude=_claude_root(parent))
            shown = result["sessions"][0]
            self.assertEqual(shown["store"], store_claude.NAME)
            self.assertEqual(shown["project"], PROJECT)
            self.assertEqual(shown["turns"], 2)
            self.assertEqual(shown["skill_count"], 1)


class TestCredentialWarnings(unittest.TestCase):
    def _leaking_root(self, parent, said):
        return _claude_root(parent, [_claude_record("user", said)])

    def test_a_credential_in_an_utterance_is_reported_masked(self):
        leaked = "AKIA" + "A1B2C3D4E5F6G7H8"
        with tempfile.TemporaryDirectory() as parent:
            _, result = _run(parent, "--store", store_claude.NAME,
                             claude=self._leaking_root(parent, "the key is " + leaked))
            self.assertEqual(
                result["secret_warnings"], [{"type": "aws_key", "masked": "[REDACTED:aws_key]"}]
            )

    def test_the_credential_itself_never_reaches_the_result(self):
        leaked = "AKIA" + "A1B2C3D4E5F6G7H8"
        with tempfile.TemporaryDirectory() as parent:
            _, result = _run(parent, "--store", store_claude.NAME,
                             claude=self._leaking_root(parent, "the key is " + leaked))
            self.assertNotIn(leaked, json.dumps(result))

    def test_the_same_kind_of_credential_seen_twice_is_reported_once(self):
        leaked = "AKIA" + "A1B2C3D4E5F6G7H8"
        with tempfile.TemporaryDirectory() as parent:
            root = self._leaking_root(parent, leaked + " and again " + leaked)
            _, result = _run(parent, "--store", store_claude.NAME, claude=root)
            self.assertEqual(len(result["secret_warnings"]), 1)


class TestTheProjectThatIsRead(unittest.TestCase):
    def test_only_the_named_project_is_counted(self):
        with tempfile.TemporaryDirectory() as parent:
            root = _claude_root(parent)
            _claude_root(parent, project="-w-other", name="claude-store")
            output = os.path.join(parent, "friction.json")
            collect.main(["--output", output, "--store", store_claude.NAME,
                          "--claude-root", root, "--project=" + PROJECT])
            with open(output, "r", encoding="utf-8") as handle:
                result = json.load(handle)
            self.assertEqual(result["summary"]["projects_scanned"], [PROJECT])


class TestWhatTheResultShowsOfTheOperator(unittest.TestCase):
    def _over_a_home_project(self, parent):
        root = _claude_root(parent, project=HOME_PROJECT)
        return _run(parent, claude=root)[1]

    def test_a_project_key_naming_the_operators_home_is_masked_on_a_session_row(self):
        with tempfile.TemporaryDirectory() as parent:
            shown = self._over_a_home_project(parent)["sessions"][0]["project"]
            self.assertNotIn(OPERATOR, shown)
            self.assertIn("[REDACTED:home_path]", shown)

    def test_such_a_key_is_masked_where_the_projects_read_are_listed(self):
        with tempfile.TemporaryDirectory() as parent:
            listed = self._over_a_home_project(parent)["summary"]["projects_scanned"]
            self.assertEqual(len(listed), 1)
            self.assertNotIn(OPERATOR, listed[0])

    def test_such_a_key_is_masked_where_the_project_asked_for_is_named(self):
        with tempfile.TemporaryDirectory() as parent:
            root = _claude_root(parent, project=HOME_PROJECT)
            output = os.path.join(parent, "friction.json")
            collect.main(["--output", output, "--store", store_claude.NAME,
                          "--claude-root", root, "--project=" + HOME_PROJECT])
            with open(output, "r", encoding="utf-8") as handle:
                result = json.load(handle)
            self.assertNotIn(OPERATOR, result["summary"]["project_filter"])

    def test_a_project_key_naming_no_home_is_shown_as_it_is(self):
        with tempfile.TemporaryDirectory() as parent:
            result = _run(parent, claude=_claude_root(parent))[1]
            self.assertEqual(result["sessions"][0]["project"], PROJECT)


class TestThePeriodThatIsRead(unittest.TestCase):
    def test_a_session_untouched_since_before_the_period_is_left_out(self):
        with tempfile.TemporaryDirectory() as parent:
            root = _claude_root(parent, [_claude_record("user", "old", LONG_AGO)])
            stale = os.path.join(root, PROJECT, "a.jsonl")
            os.utime(stale, (0, 0))
            _, result = _run(parent, "--store", store_claude.NAME, "--days", "30",
                             claude=root)
            self.assertEqual(result["summary"]["sessions_found"], 0)

    def test_the_period_asked_for_is_reported(self):
        with tempfile.TemporaryDirectory() as parent:
            _, result = _run(parent, "--days", "7", claude=_claude_root(parent))
            self.assertEqual(result["summary"]["days"], 7)


class TestWhereTheResultGoes(unittest.TestCase):
    def test_a_result_written_over_an_earlier_one_leaves_no_half_written_file(self):
        with tempfile.TemporaryDirectory() as parent:
            output = os.path.join(parent, "friction.json")
            claude = _claude_root(parent)
            for _ in range(2):
                collect.main(["--output", output, "--all-projects",
                              "--store", store_claude.NAME, "--claude-root", claude])
            self.assertFalse(os.path.exists(output + ".tmp"))
            with open(output, "r", encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["summary"]["sessions_found"], 1)

    def test_the_result_goes_to_the_output_when_no_file_is_named(self):
        with tempfile.TemporaryDirectory() as parent:
            claude = _claude_root(parent)
            written = io.StringIO()
            with contextlib.redirect_stdout(written):
                code = collect.main(["--all-projects", "--store", store_claude.NAME,
                                     "--claude-root", claude])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(written.getvalue())["summary"]["days"], 30)


if __name__ == "__main__":
    unittest.main()
