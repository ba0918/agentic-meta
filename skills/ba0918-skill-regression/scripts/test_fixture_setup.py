#!/usr/bin/env python3
"""Unit tests for fixture_setup.py.

Two jobs are covered: refusing a scenario declaration that would set up an
environment other than the one it appears to declare, and materializing an
accepted declaration deterministically. The premises a scenario depends on —
which files exist, in what order they were touched, what the git history looks
like — are what the declaration exists to pin down, so a silent gap here lets a
run pass without ever reaching the branch it was written to exercise.
"""
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fixture_setup

PARENT = ".."
ROOTED = os.path.join(os.sep, "etc", "passwd")


def _minimal(**over):
    scenario = {
        "skill": "acme",
        "id": "ac-001",
        "prompt": "do the thing",
        "expectations": [{"text": "it did the thing", "critical": True}],
    }
    scenario.update(over)
    return scenario


def _inputs(root, files):
    base = os.path.join(root, "inputs")
    for rel, content in files.items():
        path = os.path.join(base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    return base


def _git(dest, *args):
    return subprocess.run(["git"] + list(args), cwd=dest, capture_output=True,
                          text=True, check=True).stdout.strip()


class TestValidateShape(unittest.TestCase):
    def test_minimal_scenario_is_accepted(self):
        self.assertEqual(fixture_setup.validate(_minimal()), [])

    def test_unknown_top_level_key_is_refused(self):
        # A declaration silently ignored is the worst failure: the premise the
        # author meant to pin is filled in by whoever runs it instead.
        self.assertTrue(fixture_setup.validate(_minimal(setup={"files": []})))

    def test_missing_id_is_refused(self):
        scenario = _minimal()
        del scenario["id"]
        self.assertTrue(fixture_setup.validate(scenario))

    def test_missing_skill_is_refused(self):
        scenario = _minimal()
        del scenario["skill"]
        self.assertTrue(fixture_setup.validate(scenario))

    def test_missing_prompt_is_refused(self):
        scenario = _minimal()
        del scenario["prompt"]
        self.assertTrue(fixture_setup.validate(scenario))

    def test_expectations_must_not_be_empty(self):
        self.assertTrue(fixture_setup.validate(_minimal(expectations=[])))

    def test_expectation_needs_text(self):
        self.assertTrue(fixture_setup.validate(_minimal(expectations=[{"critical": True}])))

    def test_at_least_one_expectation_must_be_critical(self):
        # Passing is defined as every critical expectation holding; with none
        # declared, a scenario passes without asserting anything.
        self.assertTrue(fixture_setup.validate(
            _minimal(expectations=[{"text": "a", "critical": False}])))

    def test_unknown_executor_tier_is_refused(self):
        self.assertTrue(fixture_setup.validate(_minimal(executor_tier="turbo")))

    def test_unknown_isolation_is_refused(self):
        self.assertTrue(fixture_setup.validate(_minimal(isolation="sandbox")))


class TestValidateFiles(unittest.TestCase):
    def test_plain_path_entry_is_accepted(self):
        self.assertEqual(fixture_setup.validate(_minimal(files=["project/a.md"])), [])

    def test_from_to_entry_is_accepted(self):
        self.assertEqual(fixture_setup.validate(
            _minimal(files=[{"from": "project/a.after.md", "to": "project/a.md"}])), [])

    def test_rooted_path_is_refused(self):
        self.assertTrue(fixture_setup.validate(_minimal(files=[ROOTED])))

    def test_parent_escape_is_refused(self):
        self.assertTrue(fixture_setup.validate(
            _minimal(files=[f"{PARENT}/outside.md"])))

    def test_git_metadata_path_is_refused(self):
        # Materializing into .git/ would let a hook reach outside the isolated area.
        self.assertTrue(fixture_setup.validate(_minimal(files=["project/.git/hooks/pre-commit"])))

    def test_git_metadata_path_is_refused_case_insensitively(self):
        self.assertTrue(fixture_setup.validate(_minimal(files=["project/.GIT/config"])))

    def test_unknown_file_entry_key_is_refused(self):
        self.assertTrue(fixture_setup.validate(
            _minimal(files=[{"from": "a.md", "to": "b.md", "mode": "0755"}])))

    def test_duplicate_destination_is_refused(self):
        self.assertTrue(fixture_setup.validate(
            _minimal(files=["a.md", {"from": "b.md", "to": "a.md"}])))


class TestValidateMtimesAndEnv(unittest.TestCase):
    def test_mtime_offset_must_be_an_integer(self):
        self.assertTrue(fixture_setup.validate(
            _minimal(files=["a.md"], mtimes={"a.md": "old"})))

    def test_mtime_needs_a_declared_destination(self):
        self.assertTrue(fixture_setup.validate(_minimal(mtimes={"a.md": -60})))

    def test_mtime_on_a_declared_destination_is_accepted(self):
        self.assertEqual(fixture_setup.validate(
            _minimal(files=["a.md"], mtimes={"a.md": -60})), [])

    def test_env_values_must_be_strings(self):
        self.assertTrue(fixture_setup.validate(_minimal(env={"TZ": 9})))


class TestValidateGit(unittest.TestCase):
    def test_commit_requires_init(self):
        self.assertTrue(fixture_setup.validate(_minimal(git={"commit": True})))

    def test_init_with_commit_is_accepted(self):
        self.assertEqual(fixture_setup.validate(
            _minimal(files=["a.md"], git={"init": True, "commit": True})), [])

    def test_commit_path_needs_a_declared_destination(self):
        self.assertTrue(fixture_setup.validate(
            _minimal(files=["a.md"], git={"init": True, "commit": ["b.md"]})))

    def test_empty_commit_list_is_refused(self):
        self.assertTrue(fixture_setup.validate(
            _minimal(files=["a.md"], git={"init": True, "commit": []})))

    def test_message_without_commit_is_refused(self):
        self.assertTrue(fixture_setup.validate(
            _minimal(git={"init": True, "message": "baseline"})))

    def test_commits_entry_needs_files_and_message(self):
        self.assertTrue(fixture_setup.validate(
            _minimal(files=["a.md"], git={"init": True, "commits": [{"files": ["a.md"]}]})))

    def test_commits_entry_is_accepted(self):
        self.assertEqual(fixture_setup.validate(_minimal(
            files=["a.md"],
            git={"init": True, "commit": True,
                 "commits": [{"files": [{"from": "a.after.md", "to": "a.md"}],
                              "message": "implement"}]})), [])


class TestValidateExercises(unittest.TestCase):
    def test_repo_relative_skill_path_is_accepted(self):
        self.assertEqual(fixture_setup.validate(
            _minimal(exercises=["skills/acme/SKILL.md"])), [])

    def test_path_outside_skills_is_refused(self):
        self.assertTrue(fixture_setup.validate(_minimal(exercises=["README.md"])))

    def test_rooted_path_is_refused(self):
        self.assertTrue(fixture_setup.validate(_minimal(exercises=[ROOTED])))


class TestScenarioHash(unittest.TestCase):
    def test_exercises_do_not_change_the_hash(self):
        # Adding an impact declaration must not cost a rerun; the scenario
        # measures the same thing either way.
        bare = _minimal()
        declared = _minimal(exercises=["skills/acme/SKILL.md"])
        self.assertEqual(fixture_setup.scenario_sha256(bare),
                         fixture_setup.scenario_sha256(declared))

    def test_prompt_change_changes_the_hash(self):
        self.assertNotEqual(fixture_setup.scenario_sha256(_minimal()),
                            fixture_setup.scenario_sha256(_minimal(prompt="other")))


class TestMaterialize(unittest.TestCase):
    def test_copies_declared_files_and_reports_baseline_hashes(self):
        with tempfile.TemporaryDirectory() as root:
            inputs = _inputs(root, {"project/a.md": "hello\n"})
            dest = os.path.join(root, "dest")
            out = fixture_setup.materialize(_minimal(files=["project/a.md"]), dest, inputs)
            with open(os.path.join(dest, "project/a.md"), encoding="utf-8") as f:
                self.assertEqual(f.read(), "hello\n")
            self.assertEqual(out["baseline"]["project/a.md"],
                             hashlib.sha256(b"hello\n").hexdigest())
            self.assertEqual(out["unmaterialized"], [])

    def test_from_to_entry_lands_at_the_destination_path(self):
        with tempfile.TemporaryDirectory() as root:
            inputs = _inputs(root, {"project/a.after.md": "after\n"})
            dest = os.path.join(root, "dest")
            fixture_setup.materialize(
                _minimal(files=[{"from": "project/a.after.md", "to": "project/a.md"}]),
                dest, inputs)
            with open(os.path.join(dest, "project/a.md"), encoding="utf-8") as f:
                self.assertEqual(f.read(), "after\n")

    def test_missing_input_file_stops_the_run(self):
        with tempfile.TemporaryDirectory() as root:
            inputs = _inputs(root, {})
            dest = os.path.join(root, "dest")
            with self.assertRaises(fixture_setup.MaterializeError):
                fixture_setup.materialize(_minimal(files=["project/a.md"]), dest, inputs)

    def test_input_path_escaping_the_inputs_root_stops_the_run(self):
        with tempfile.TemporaryDirectory() as root:
            inputs = _inputs(root, {})
            with open(os.path.join(root, "secret.md"), "w", encoding="utf-8") as f:
                f.write("secret\n")
            dest = os.path.join(root, "dest")
            with self.assertRaises(fixture_setup.MaterializeError):
                fixture_setup.materialize(
                    _minimal(files=[{"from": f"{PARENT}/secret.md", "to": "a.md"}]),
                    dest, inputs)

    def test_env_is_returned_for_the_executor(self):
        with tempfile.TemporaryDirectory() as root:
            inputs = _inputs(root, {})
            dest = os.path.join(root, "dest")
            out = fixture_setup.materialize(_minimal(env={"TZ": "UTC"}), dest, inputs)
            self.assertEqual(out["env"], {"TZ": "UTC"})

    def test_mtimes_are_applied_relative_to_the_base_time(self):
        with tempfile.TemporaryDirectory() as root:
            inputs = _inputs(root, {"a.md": "x\n", "b.md": "y\n"})
            dest = os.path.join(root, "dest")
            fixture_setup.materialize(
                _minimal(files=["a.md", "b.md"], mtimes={"a.md": -3600}),
                dest, inputs, base_time=1_000_000.0)
            self.assertEqual(os.stat(os.path.join(dest, "a.md")).st_mtime, 996400.0)

    def test_git_init_and_baseline_commit(self):
        with tempfile.TemporaryDirectory() as root:
            inputs = _inputs(root, {"a.md": "x\n"})
            dest = os.path.join(root, "dest")
            out = fixture_setup.materialize(
                _minimal(files=["a.md"], git={"init": True, "commit": True}), dest, inputs)
            self.assertTrue(out["git"]["commit"])
            self.assertEqual(_git(dest, "status", "--porcelain"), "")
            self.assertEqual(len(out["git"]["baseline"]), 40)

    def test_later_commit_replaces_the_file_and_extends_the_history(self):
        with tempfile.TemporaryDirectory() as root:
            inputs = _inputs(root, {"a.md": "before\n", "a.after.md": "after\n"})
            dest = os.path.join(root, "dest")
            out = fixture_setup.materialize(_minimal(
                files=["a.md"],
                git={"init": True, "commit": True,
                     "commits": [{"files": [{"from": "a.after.md", "to": "a.md"}],
                                  "message": "implement"}]}), dest, inputs)
            with open(os.path.join(dest, "a.md"), encoding="utf-8") as f:
                self.assertEqual(f.read(), "after\n")
            self.assertEqual(len(out["git"]["commits"]), 1)
            self.assertEqual(_git(dest, "log", "--format=%s", "-1"), "implement")
            self.assertEqual(_git(dest, "status", "--porcelain"), "")

    def test_baseline_sha_placeholder_is_substituted(self):
        with tempfile.TemporaryDirectory() as root:
            inputs = _inputs(root, {"a.md": "x\n", "note.md": "base {{fixture:sha:baseline}}\n"})
            dest = os.path.join(root, "dest")
            out = fixture_setup.materialize(_minimal(
                files=["a.md", "note.md"],
                git={"init": True, "commit": ["a.md"]}), dest, inputs)
            with open(os.path.join(dest, "note.md"), encoding="utf-8") as f:
                body = f.read()
            self.assertIn(out["git"]["baseline"], body)
            self.assertNotIn("{{fixture:sha:", body)

    def test_unknown_placeholder_stops_the_run(self):
        with tempfile.TemporaryDirectory() as root:
            inputs = _inputs(root, {"note.md": "{{fixture:sha:nonsense}}\n"})
            dest = os.path.join(root, "dest")
            with self.assertRaises(fixture_setup.MaterializeError):
                fixture_setup.materialize(_minimal(files=["note.md"]), dest, inputs)


if __name__ == "__main__":
    unittest.main()
