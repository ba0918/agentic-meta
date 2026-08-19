#!/usr/bin/env python3
"""Unit tests for lock.py.

The lock records that every scenario of a skill passed while its behaviour
surface held a particular content. What the tests protect is the direction of
every judgment: whenever the material for a decision is missing, the answer must
fall to the heavy side — a rerun is demanded — rather than to the light one.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lock

TODAY = "2026-08-19"


def _write(root, rel, content=""):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _scenario_yaml(skill, sid, prompt="do it", exercises=None, critical="it worked"):
    lines = [f"skill: {skill}", f"id: {sid}", f"prompt: {prompt}"]
    if exercises:
        lines.append("exercises:")
        lines += [f"  - {p}" for p in exercises]
    lines += ["expectations:", f"  - text: {critical}", "    critical: true"]
    return "\n".join(lines) + "\n"


def _repo(root, prompt="do it", exercises=None):
    _write(root, "skills/acme/SKILL.md", "body")
    _write(root, "skills/acme/references/guide.md", "guide")
    _write(root, "evals/cases/acme/ac-001.yaml",
           _scenario_yaml("acme", "ac-001", prompt, exercises))
    return root


class TestScenarioLoading(unittest.TestCase):
    def test_reads_one_scenario_per_file(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            _write(root, "evals/cases/acme/ac-002.yaml", _scenario_yaml("acme", "ac-002"))
            self.assertEqual([s["id"] for s in lock.load_scenarios(root, "acme")],
                             ["ac-001", "ac-002"])

    def test_a_skill_without_scenarios_is_not_tracked(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/acme/SKILL.md", "body")
            self.assertEqual(lock.load_scenarios(root, "acme"), [])

    def test_an_unreadable_scenario_file_stops_the_read(self):
        # Skipping it silently would drop a scenario from the run while the
        # report still claimed the skill was covered.
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            _write(root, "evals/cases/acme/broken.yaml", "files: [a, b]\n")
            with self.assertRaises(lock.LockError):
                lock.load_scenarios(root, "acme")


class TestStaleSeverity(unittest.TestCase):
    def test_no_change_is_not_stale(self):
        self.assertEqual(lock.stale_severity({"a": "1"}, {"a": "1"}), (None, []))

    def test_added_file_from_inside_the_skill_is_an_addition(self):
        severity, changed = lock.stale_severity(
            {"skills/a/SKILL.md": "1"},
            {"skills/a/SKILL.md": "1", "skills/a/new.md": "2"},
            own_prefix="skills/a/")
        self.assertEqual(severity, lock.SEVERITY_ADDITION)
        self.assertEqual(changed, ["skills/a/new.md"])

    def test_added_file_from_outside_the_skill_is_a_change(self):
        # A bare-path reference whose target appears later brings unverified
        # content onto the surface, so it cannot ride the light rail.
        severity, _ = lock.stale_severity(
            {"skills/a/SKILL.md": "1"},
            {"skills/a/SKILL.md": "1", "skills/b/shared.md": "2"},
            own_prefix="skills/a/")
        self.assertEqual(severity, lock.SEVERITY_CHANGE)

    def test_dangling_added_file_is_a_change(self):
        severity, _ = lock.stale_severity(
            {"skills/a/SKILL.md": "1"},
            {"skills/a/SKILL.md": "1", "skills/a/gone.md": lock.MISSING},
            own_prefix="skills/a/")
        self.assertEqual(severity, lock.SEVERITY_CHANGE)

    def test_removed_file_is_a_change(self):
        severity, _ = lock.stale_severity({"a": "1", "b": "2"}, {"a": "1"})
        self.assertEqual(severity, lock.SEVERITY_CHANGE)

    def test_prose_only_modification_is_prose_change(self):
        severity, _ = lock.stale_severity(
            {"a.md": "1"}, {"a.md": "2"},
            recorded_struct={"a.md": "s"}, current_struct={"a.md": "s"})
        self.assertEqual(severity, lock.SEVERITY_PROSE)

    def test_structural_modification_is_a_change(self):
        severity, _ = lock.stale_severity(
            {"a.md": "1"}, {"a.md": "2"},
            recorded_struct={"a.md": "s"}, current_struct={"a.md": "t"})
        self.assertEqual(severity, lock.SEVERITY_CHANGE)

    def test_modification_without_a_structural_record_is_a_change(self):
        severity, _ = lock.stale_severity({"a.md": "1"}, {"a.md": "2"})
        self.assertEqual(severity, lock.SEVERITY_CHANGE)

    def test_an_entry_with_no_recorded_hashes_is_a_change(self):
        severity, _ = lock.stale_severity({}, {"a": "1"})
        self.assertEqual(severity, lock.SEVERITY_CHANGE)


class TestAcceptResult(unittest.TestCase):
    def test_addition_on_top_of_a_real_run_is_accepted_addition(self):
        self.assertEqual(
            lock.accept_result({"skills/a/SKILL.md": "1"},
                               {"skills/a/SKILL.md": "1", "skills/a/n.md": "2"},
                               lock.RESULT_PASS, own_prefix="skills/a/"),
            lock.RESULT_ACCEPTED_ADDITION)

    def test_addition_on_top_of_an_acceptance_is_not(self):
        # Otherwise a lock could keep taking light approvals forever without a
        # single real run, and the signal for that would never fire.
        self.assertEqual(
            lock.accept_result({"skills/a/SKILL.md": "1"},
                               {"skills/a/SKILL.md": "1", "skills/a/n.md": "2"},
                               lock.RESULT_ACCEPTED_WITHOUT_RUN, own_prefix="skills/a/"),
            lock.RESULT_ACCEPTED_WITHOUT_RUN)

    def test_prose_change_on_top_of_a_real_run_is_accepted_prose(self):
        self.assertEqual(
            lock.accept_result({"a.md": "1"}, {"a.md": "2"}, lock.RESULT_PASS,
                               recorded_struct={"a.md": "s"},
                               current_struct={"a.md": "s"}),
            lock.RESULT_ACCEPTED_PROSE)

    def test_no_difference_at_all_is_accepted_without_run(self):
        self.assertEqual(
            lock.accept_result({"a": "1"}, {"a": "1"}, lock.RESULT_PASS),
            lock.RESULT_ACCEPTED_WITHOUT_RUN)


class TestEntryShape(unittest.TestCase):
    def test_entry_records_only_content_facts(self):
        # Nothing about the route, the model or the token count belongs here:
        # those are facts about the environment a run happened in, and the lock
        # is committed to a repository other environments clone.
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            surface = lock.skill_surface(root, "acme")
            entry = lock.make_entry(root, surface, lock.RESULT_PASS, TODAY)
            self.assertEqual(sorted(entry), [
                "file_sha256", "result", "structural_sha256", "surface",
                "surface_sha256", "verified"])

    def test_note_and_carried_note_are_kept_when_given(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            surface = lock.skill_surface(root, "acme")
            entry = lock.make_entry(root, surface, lock.RESULT_PASS, TODAY,
                                    note="ran on the queue route",
                                    carried_note="previous note")
            self.assertEqual(entry["note"], "ran on the queue route")
            self.assertEqual(entry["carried_note"], "previous note")

    def test_scenarios_are_omitted_when_absent(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            surface = lock.skill_surface(root, "acme")
            self.assertNotIn(
                "scenarios", lock.make_entry(root, surface, lock.RESULT_PASS, TODAY))


class TestLoadSave(unittest.TestCase):
    def test_round_trip_at_the_repository_root(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            state = lock.load(root)
            state["skills"]["acme"] = lock.make_entry(
                root, lock.skill_surface(root, "acme"), lock.RESULT_PASS, TODAY)
            lock.save(root, state)
            self.assertTrue(os.path.isfile(os.path.join(root, lock.LOCK_REL)))
            self.assertEqual(lock.load(root)["skills"]["acme"]["result"], lock.RESULT_PASS)

    def test_a_missing_lock_reads_as_empty(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(lock.load(root), {"version": 1, "skills": {},
                                               "coverage_exempt": {}})

    def test_nothing_is_written_inside_the_skill_directory(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            before = sorted(os.listdir(os.path.join(root, "skills", "acme")))
            state = lock.load(root)
            state["skills"]["acme"] = lock.make_entry(
                root, lock.skill_surface(root, "acme"), lock.RESULT_PASS, TODAY)
            lock.save(root, state)
            self.assertEqual(sorted(os.listdir(os.path.join(root, "skills", "acme"))),
                             before)


class TestCheck(unittest.TestCase):
    def _issues(self, root, state):
        return {(kind, skill) for kind, skill, _ in lock.check(root, state)}

    def test_a_skill_with_scenarios_and_no_entry_is_unverified(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            self.assertIn(("unverified", "acme"), self._issues(root, lock.load(root)))

    def test_a_matching_entry_raises_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            state = lock.load(root)
            state["skills"]["acme"] = lock.make_entry(
                root, lock.skill_surface(root, "acme"), lock.RESULT_PASS, TODAY)
            self.assertEqual(lock.check(root, state), [])

    def test_a_changed_surface_is_stale(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            state = lock.load(root)
            state["skills"]["acme"] = lock.make_entry(
                root, lock.skill_surface(root, "acme"), lock.RESULT_PASS, TODAY)
            _write(root, "skills/acme/SKILL.md", "body, reworked")
            self.assertIn(("stale", "acme"), self._issues(root, state))

    def test_an_entry_whose_scenarios_are_gone_is_an_orphan(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/acme/SKILL.md", "body")
            state = lock.load(root)
            state["skills"]["acme"] = lock.make_entry(root, ["skills/acme/SKILL.md"],
                                                      lock.RESULT_PASS, TODAY)
            self.assertIn(("orphan", "acme"), self._issues(root, state))

    def test_a_stale_issue_carries_its_severity(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            state = lock.load(root)
            state["skills"]["acme"] = lock.make_entry(
                root, lock.skill_surface(root, "acme"), lock.RESULT_PASS, TODAY)
            _write(root, "skills/acme/added.md", "new file")
            detail = [d for kind, _, d in lock.check(root, state) if kind == "stale"][0]
            self.assertIn(lock.SEVERITY_ADDITION, detail)


class TestScenarioImpact(unittest.TestCase):
    def test_a_change_to_the_skill_body_reaches_every_scenario(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root, exercises=["skills/acme/references/guide.md"])
            scenarios = lock.load_scenarios(root, "acme")
            surface = lock.skill_surface(root, "acme")
            self.assertEqual(
                lock.impacted_scenarios("acme", surface, scenarios,
                                        ["skills/acme/SKILL.md"]),
                ["ac-001"])

    def test_a_declared_dependency_reaches_only_the_scenarios_declaring_it(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root, exercises=["skills/acme/references/guide.md"])
            _write(root, "evals/cases/acme/ac-002.yaml",
                   _scenario_yaml("acme", "ac-002", exercises=["skills/acme/SKILL.md"]))
            scenarios = lock.load_scenarios(root, "acme")
            surface = lock.skill_surface(root, "acme")
            self.assertEqual(
                lock.impacted_scenarios("acme", surface, scenarios,
                                        ["skills/acme/references/guide.md"]),
                ["ac-001"])

    def test_a_scenario_without_declarations_is_always_reached(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            scenarios = lock.load_scenarios(root, "acme")
            surface = lock.skill_surface(root, "acme")
            self.assertEqual(
                lock.impacted_scenarios("acme", surface, scenarios,
                                        ["skills/acme/references/guide.md"]),
                ["ac-001"])

    def test_a_declaration_naming_a_path_off_the_surface_is_not_believed(self):
        # A typo or a moved reference would otherwise read as "this scenario
        # does not touch it", carrying a pass that no longer holds.
        with tempfile.TemporaryDirectory() as root:
            _repo(root, exercises=["skills/acme/nowhere.md"])
            scenarios = lock.load_scenarios(root, "acme")
            surface = lock.skill_surface(root, "acme")
            self.assertEqual(
                lock.impacted_scenarios("acme", surface, scenarios,
                                        ["skills/acme/references/guide.md"]),
                ["ac-001"])

    def test_no_change_reaches_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            scenarios = lock.load_scenarios(root, "acme")
            surface = lock.skill_surface(root, "acme")
            self.assertEqual(lock.impacted_scenarios("acme", surface, scenarios, []), [])


class TestCarryover(unittest.TestCase):
    def _recorded(self, root, scenarios, surface):
        return ({s["id"]: {"scenario_sha256": lock.scenario_sha256(s),
                           "result": lock.RESULT_PASS, "verified": TODAY}
                 for s in scenarios},
                lock.file_hashes(root, surface))

    def test_an_untouched_scenario_carries_over(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root, exercises=["skills/acme/references/guide.md"])
            surface = lock.skill_surface(root, "acme")
            scenarios = lock.load_scenarios(root, "acme")
            recorded_scenarios, recorded_hashes = self._recorded(root, scenarios, surface)
            self.assertIsNone(lock.carryover_reason(
                "acme", scenarios[0], surface, recorded_hashes,
                lock.file_hashes(root, surface), recorded_scenarios))

    def test_a_redefined_scenario_does_not_carry_over(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            surface = lock.skill_surface(root, "acme")
            scenarios = lock.load_scenarios(root, "acme")
            recorded_scenarios, recorded_hashes = self._recorded(root, scenarios, surface)
            _write(root, "evals/cases/acme/ac-001.yaml",
                   _scenario_yaml("acme", "ac-001", prompt="do it differently"))
            changed = lock.load_scenarios(root, "acme")[0]
            self.assertIsNotNone(lock.carryover_reason(
                "acme", changed, surface, recorded_hashes,
                lock.file_hashes(root, surface), recorded_scenarios))

    def test_a_moved_dependency_does_not_carry_over(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root, exercises=["skills/acme/references/guide.md"])
            surface = lock.skill_surface(root, "acme")
            scenarios = lock.load_scenarios(root, "acme")
            recorded_scenarios, recorded_hashes = self._recorded(root, scenarios, surface)
            _write(root, "skills/acme/references/guide.md", "guide, reworked")
            self.assertIsNotNone(lock.carryover_reason(
                "acme", scenarios[0], surface, recorded_hashes,
                lock.file_hashes(root, surface), recorded_scenarios))

    def test_a_scenario_with_no_previous_record_does_not_carry_over(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            surface = lock.skill_surface(root, "acme")
            scenarios = lock.load_scenarios(root, "acme")
            self.assertIsNotNone(lock.carryover_reason(
                "acme", scenarios[0], surface, lock.file_hashes(root, surface),
                lock.file_hashes(root, surface), {}))


class TestSkillResult(unittest.TestCase):
    def test_every_scenario_a_real_run_is_pass(self):
        self.assertEqual(lock.skill_result({"a": {"result": lock.RESULT_PASS}}),
                         lock.RESULT_PASS)

    def test_one_acceptance_drops_the_skill_below_pass(self):
        self.assertEqual(
            lock.skill_result({"a": {"result": lock.RESULT_PASS},
                               "b": {"result": lock.RESULT_ACCEPTED_WITHOUT_RUN}}),
            lock.RESULT_ACCEPTED_WITHOUT_RUN)

    def test_runs_plus_judged_scenarios_read_as_judged(self):
        self.assertEqual(
            lock.skill_result({"a": {"result": lock.RESULT_PASS},
                               "b": {"result": lock.RESULT_ACCEPTED_SEMANTIC}}),
            lock.RESULT_ACCEPTED_SEMANTIC)


class TestCoverage(unittest.TestCase):
    def test_skills_split_into_covered_and_uncovered(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            _write(root, "skills/other/SKILL.md", "body")
            report = lock.coverage(root, lock.load(root))
            self.assertEqual(report["covered"], ["acme"])
            self.assertEqual(report["uncovered"], ["other"])

    def test_an_exemption_is_declared_in_the_lock_with_a_reason(self):
        # Declaring it on the skill side would let merely touching a skill
        # directory make it disappear from the count.
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            _write(root, "skills/other/SKILL.md", "body")
            state = lock.load(root)
            state["coverage_exempt"]["other"] = "a contract library, never launched on its own"
            report = lock.coverage(root, state)
            self.assertEqual(report["uncovered"], [])
            self.assertIn("other", report["exempt"])


if __name__ == "__main__":
    unittest.main()


class TestCarriedNote(unittest.TestCase):
    def test_the_previous_note_moves_into_the_carried_slot(self):
        self.assertEqual(lock.carried_note({"note": "ran on the queue route"}, None),
                         "ran on the queue route")

    def test_an_entry_without_a_note_passes_on_what_it_carried(self):
        self.assertEqual(lock.carried_note({"carried_note": "older note"}, "new note"),
                         "older note")

    def test_repeating_the_same_note_does_not_duplicate_it(self):
        self.assertIsNone(lock.carried_note({"note": "same"}, "same"))


class TestUpdate(unittest.TestCase):
    def test_a_full_run_records_every_scenario_as_a_pass(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            state = lock.load(root)
            lock.update(root, state, "acme", TODAY)
            entry = state["skills"]["acme"]
            self.assertEqual(entry["result"], lock.RESULT_PASS)
            self.assertEqual(entry["scenarios"]["ac-001"]["result"], lock.RESULT_PASS)
            self.assertEqual(entry["scenarios"]["ac-001"]["verified"], TODAY)
            self.assertEqual(lock.check(root, state), [])

    def test_an_acceptance_keeps_the_dates_of_the_last_real_run(self):
        # A per-scenario date says when that scenario was last confirmed by
        # running it. Stamping today on an acceptance would make the two
        # indistinguishable from the record alone.
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            state = lock.load(root)
            lock.update(root, state, "acme", "2026-08-01")
            _write(root, "skills/acme/added.md", "new file")
            lock.update_accept(root, state, "acme", TODAY)
            entry = state["skills"]["acme"]
            self.assertEqual(entry["result"], lock.RESULT_ACCEPTED_ADDITION)
            self.assertEqual(entry["scenarios"]["ac-001"]["verified"], "2026-08-01")
            self.assertEqual(entry["verified"], TODAY)

    def test_an_acceptance_on_top_of_an_acceptance_is_not_light(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            state = lock.load(root)
            lock.update(root, state, "acme", "2026-08-01")
            _write(root, "skills/acme/one.md", "first")
            lock.update_accept(root, state, "acme", TODAY)
            _write(root, "skills/acme/two.md", "second")
            lock.update_accept(root, state, "acme", TODAY)
            self.assertEqual(state["skills"]["acme"]["result"],
                             lock.RESULT_ACCEPTED_WITHOUT_RUN)

    def test_a_note_is_carried_into_the_next_entry(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            state = lock.load(root)
            lock.update(root, state, "acme", "2026-08-01", note="ran on the queue route")
            _write(root, "skills/acme/added.md", "new file")
            lock.update_accept(root, state, "acme", TODAY)
            self.assertEqual(state["skills"]["acme"]["carried_note"],
                             "ran on the queue route")


class TestPartialUpdate(unittest.TestCase):
    def _two_scenarios(self, root):
        _repo(root, exercises=["skills/acme/references/guide.md"])
        _write(root, "evals/cases/acme/ac-002.yaml",
               _scenario_yaml("acme", "ac-002", exercises=["skills/acme/SKILL.md"]))

    def test_the_scenarios_that_ran_are_recorded_and_the_rest_carried(self):
        with tempfile.TemporaryDirectory() as root:
            self._two_scenarios(root)
            state = lock.load(root)
            lock.update(root, state, "acme", "2026-08-01")
            _write(root, "skills/acme/references/guide.md", "guide, reworked")
            refused = lock.partial_update(root, state, "acme", ["ac-001"], TODAY)
            self.assertEqual(refused, [])
            scenarios = state["skills"]["acme"]["scenarios"]
            self.assertEqual(scenarios["ac-001"]["verified"], TODAY)
            self.assertEqual(scenarios["ac-002"]["verified"], "2026-08-01")
            self.assertEqual(state["skills"]["acme"]["result"], lock.RESULT_PASS)

    def test_a_scenario_that_cannot_be_carried_refuses_the_whole_update(self):
        # Recording the rest anyway would leave a lock claiming verification for
        # a scenario whose dependency moved under it.
        with tempfile.TemporaryDirectory() as root:
            self._two_scenarios(root)
            state = lock.load(root)
            lock.update(root, state, "acme", "2026-08-01")
            before = json.dumps(state, sort_keys=True)
            _write(root, "skills/acme/SKILL.md", "body, reworked")
            refused = lock.partial_update(root, state, "acme", ["ac-001"], TODAY)
            self.assertEqual([skill_id for skill_id, _ in refused], ["ac-002"])
            self.assertEqual(json.dumps(state, sort_keys=True), before)

    def test_running_nothing_is_legitimate_when_everything_carries(self):
        # A declaration-only edit reaches no scenario, so the lock advances with
        # no run at all.
        with tempfile.TemporaryDirectory() as root:
            self._two_scenarios(root)
            state = lock.load(root)
            lock.update(root, state, "acme", "2026-08-01")
            refused = lock.partial_update(root, state, "acme", [], TODAY)
            self.assertEqual(refused, [])
            self.assertEqual(state["skills"]["acme"]["result"], lock.RESULT_PASS)

    def test_an_unknown_scenario_id_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            self._two_scenarios(root)
            state = lock.load(root)
            lock.update(root, state, "acme", "2026-08-01")
            with self.assertRaises(lock.LockError):
                lock.partial_update(root, state, "acme", ["ac-999"], TODAY)


class TestSemanticDiffHash(unittest.TestCase):
    def test_only_the_files_that_moved_count(self):
        # An unrelated addition to the surface must not invalidate a judgment
        # made about the same diff.
        first = lock.semantic_diff_sha256({"a": "1", "b": "2"}, {"a": "1", "b": "3"})
        second = lock.semantic_diff_sha256({"a": "1", "b": "2", "c": "9"},
                                           {"a": "1", "b": "3", "c": "9"})
        self.assertEqual(first, second)

    def test_a_different_change_gives_a_different_hash(self):
        self.assertNotEqual(lock.semantic_diff_sha256({"b": "2"}, {"b": "3"}),
                            lock.semantic_diff_sha256({"b": "2"}, {"b": "4"}))


class TestValidateJudgment(unittest.TestCase):
    def _judgment(self, recorded, current, **over):
        judgment = {
            "skill": "acme",
            "diff_sha256": lock.semantic_diff_sha256(recorded, current),
            "model": "some-judge",
            "scenarios": {"ac-001": {"verdict": lock.VERDICT_UNAFFECTED,
                                     "rationale": "the edit is a wording change"}},
        }
        judgment.update(over)
        return judgment

    def test_a_well_formed_judgment_is_accepted(self):
        recorded, current = {"a": "1"}, {"a": "2"}
        self.assertIsNone(lock.validate_judgment(
            self._judgment(recorded, current), "acme", recorded, current,
            gate_reason=None, known_ids={"ac-001"}))

    def test_a_judgment_about_another_change_is_refused(self):
        # This is what stops an old judgment being reused for a new diff.
        recorded, current = {"a": "1"}, {"a": "2"}
        judgment = self._judgment(recorded, current)
        self.assertIsNotNone(lock.validate_judgment(
            judgment, "acme", recorded, {"a": "3"}, gate_reason=None,
            known_ids={"ac-001"}))

    def test_a_judgment_for_another_skill_is_refused(self):
        recorded, current = {"a": "1"}, {"a": "2"}
        self.assertIsNotNone(lock.validate_judgment(
            self._judgment(recorded, current, skill="other"), "acme", recorded,
            current, gate_reason=None, known_ids={"ac-001"}))

    def test_an_uncalibrated_judge_is_refused(self):
        recorded, current = {"a": "1"}, {"a": "2"}
        self.assertIsNotNone(lock.validate_judgment(
            self._judgment(recorded, current), "acme", recorded, current,
            gate_reason="a behaviour-changing case was called unaffected",
            known_ids={"ac-001"}))

    def test_a_judgment_without_a_model_name_is_refused(self):
        recorded, current = {"a": "1"}, {"a": "2"}
        self.assertIsNotNone(lock.validate_judgment(
            self._judgment(recorded, current, model="  "), "acme", recorded,
            current, gate_reason=None, known_ids={"ac-001"}))

    def test_a_verdict_without_a_rationale_is_refused(self):
        # A verdict nobody can audit is not evidence.
        recorded, current = {"a": "1"}, {"a": "2"}
        judgment = self._judgment(recorded, current)
        judgment["scenarios"]["ac-001"]["rationale"] = ""
        self.assertIsNotNone(lock.validate_judgment(
            judgment, "acme", recorded, current, gate_reason=None,
            known_ids={"ac-001"}))

    def test_a_verdict_for_an_unknown_scenario_is_refused(self):
        # Dropping it silently would leave a typo looking like a missing verdict.
        recorded, current = {"a": "1"}, {"a": "2"}
        self.assertIsNotNone(lock.validate_judgment(
            self._judgment(recorded, current), "acme", recorded, current,
            gate_reason=None, known_ids={"ac-002"}))


class TestPartialUpdateWithJudgment(unittest.TestCase):
    def _prepare(self, root):
        _repo(root, exercises=["skills/acme/references/guide.md"])
        _write(root, "evals/cases/acme/ac-002.yaml",
               _scenario_yaml("acme", "ac-002", exercises=["skills/acme/references/guide.md"]))
        state = lock.load(root)
        lock.update(root, state, "acme", "2026-08-01")
        recorded = dict(state["skills"]["acme"]["file_sha256"])
        _write(root, "skills/acme/references/guide.md", "guide, reworked")
        current = lock.file_hashes(root, lock.skill_surface(root, "acme"))
        return state, recorded, current

    def _judgment(self, recorded, current, ids, verdict=None):
        return {
            "skill": "acme",
            "diff_sha256": lock.semantic_diff_sha256(recorded, current),
            "model": "some-judge",
            "scenarios": {sid: {"verdict": verdict or lock.VERDICT_UNAFFECTED,
                                "rationale": "the wording changed, the steps did not"}
                          for sid in ids},
        }

    def test_an_unaffected_verdict_is_recorded_as_judged(self):
        with tempfile.TemporaryDirectory() as root:
            state, recorded, current = self._prepare(root)
            refused = lock.partial_update(
                root, state, "acme", ["ac-001"], TODAY,
                semantic=self._judgment(recorded, current, ["ac-002"]))
            self.assertEqual(refused, [])
            scenarios = state["skills"]["acme"]["scenarios"]
            self.assertEqual(scenarios["ac-002"]["result"], lock.RESULT_ACCEPTED_SEMANTIC)
            self.assertEqual(state["skills"]["acme"]["result"],
                             lock.RESULT_ACCEPTED_SEMANTIC)

    def test_an_unclear_verdict_records_nothing_and_still_needs_a_run(self):
        with tempfile.TemporaryDirectory() as root:
            state, recorded, current = self._prepare(root)
            refused = lock.partial_update(
                root, state, "acme", ["ac-001"], TODAY,
                semantic=self._judgment(recorded, current, ["ac-002"],
                                        verdict=lock.VERDICT_UNCLEAR))
            self.assertEqual([sid for sid, _ in refused], ["ac-002"])

    def test_a_judgment_that_does_not_validate_stops_the_update(self):
        with tempfile.TemporaryDirectory() as root:
            state, recorded, current = self._prepare(root)
            before = json.dumps(state, sort_keys=True)
            with self.assertRaises(lock.LockError):
                lock.partial_update(
                    root, state, "acme", ["ac-001"], TODAY,
                    semantic=self._judgment(recorded, current, ["ac-002"]),
                    gate_reason="the judge was not calibrated")
            self.assertEqual(json.dumps(state, sort_keys=True), before)
