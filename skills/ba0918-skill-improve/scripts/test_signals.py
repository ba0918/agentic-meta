#!/usr/bin/env python3
"""Unit tests for signals.py."""

import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import events
import signals

AT = datetime.datetime(2026, 8, 19, 12, 0, tzinfo=datetime.timezone.utc)
SEPARATOR = "/"


class FakeStore:
    """A store standing in for an adapter: a name, declared capabilities, events."""

    def __init__(self, name, produced=(), structural=True, text=True, abandonment=False):
        self.name = name
        self.capabilities = events.Capabilities(
            text=text, structural=structural, abandonment_signal=abandonment
        )
        self._produced = tuple(produced)

    def events(self):
        return iter(self._produced)


def _identity(session_id="s-1", project="-w-notes"):
    return events.SessionIdentity(session_id=session_id, project=project)


def _turn(role=events.ROLE_USER):
    return events.Turn(role=role, at=AT)


def _said(text="anything"):
    return events.UserText(text=text, at=AT)


def _fired(skill, route=events.ROUTE_STRUCTURAL):
    return events.SkillInvocation(skill=skill, route=route)


def _failed(tool="Bash"):
    return events.ToolError(tool=tool)


def _one_store(produced, structural=True):
    return signals.aggregate([FakeStore("claude", produced, structural=structural)])


class TestSessionBoundaries(unittest.TestCase):
    def test_each_announced_session_is_counted_once(self):
        aggregate = _one_store([_identity("s-1"), _turn(), _identity("s-2"), _turn()])
        self.assertEqual(aggregate.sessions, 2)

    def test_one_session_announced_twice_by_a_store_is_still_one_session(self):
        aggregate = _one_store([_identity("s-1"), _turn(), _identity("s-1"), _turn()])
        self.assertEqual(aggregate.sessions, 1)

    def test_what_arrives_before_any_session_is_announced_is_still_counted(self):
        aggregate = _one_store([_turn(), _turn()])
        self.assertEqual(aggregate.turns, 2)


class TestTurnCounting(unittest.TestCase):
    def test_only_turns_are_counted_as_turns(self):
        aggregate = _one_store([
            _identity(), _turn(), _turn(events.ROLE_ASSISTANT), _said(), _failed(),
        ])
        self.assertEqual(aggregate.turns, 2)


class TestRetries(unittest.TestCase):
    def test_the_same_skill_fired_again_within_the_window_is_a_retry(self):
        aggregate = _one_store([
            _identity(), _turn(), _fired("commit"), _turn(), _fired("commit"),
        ])
        self.assertEqual(aggregate.skills["commit"].retries, 2)

    def test_the_same_skill_fired_again_after_the_window_is_not_a_retry(self):
        aggregate = _one_store([
            _identity(), _turn(), _fired("commit"),
            _turn(), _turn(), _turn(), _turn(),
            _fired("commit"),
        ])
        self.assertEqual(aggregate.skills["commit"].retries, 0)

    def test_a_different_skill_firing_in_between_is_not_a_retry(self):
        aggregate = _one_store([
            _identity(), _turn(), _fired("commit"), _turn(), _fired("plan-create"),
        ])
        self.assertEqual(aggregate.skills["commit"].retries, 0)
        self.assertEqual(aggregate.skills["plan-create"].retries, 0)

    def test_a_run_of_three_firings_is_reported_as_the_length_of_the_run(self):
        aggregate = _one_store([
            _identity(), _turn(), _fired("commit"), _turn(), _fired("commit"),
            _turn(), _fired("commit"),
        ])
        self.assertEqual(aggregate.skills["commit"].retries, 3)


class TestOneFiringSeenOnBothRoutes(unittest.TestCase):
    """A slash command and the tool call it produced are one firing, not two."""

    def _pair(self):
        return _one_store([
            _identity(), _turn(), _said("/demo:tidy-up now"),
            _fired("tidy-up", events.ROUTE_TEXT), _fired("tidy-up"),
        ])

    def test_a_command_typed_and_the_tool_call_it_produced_are_one_firing(self):
        self.assertEqual(self._pair().skills["tidy-up"].invocations, 1)

    def test_a_firing_seen_along_both_routes_is_not_a_retry_of_itself(self):
        self.assertEqual(self._pair().skills["tidy-up"].retries, 0)

    def test_a_firing_seen_along_both_routes_is_kept_as_the_structural_one(self):
        self.assertEqual(self._pair().skills["tidy-up"].routes, ("structural",))

    def test_the_folding_is_counted_so_a_report_can_say_it_happened(self):
        self.assertEqual(self._pair().skills["tidy-up"].merged_route_pairs, 1)

    def test_a_firing_only_the_tool_record_shows_is_one_firing_folding_nothing(self):
        aggregate = _one_store([_identity(), _turn(), _fired("tidy-up")])
        self.assertEqual(aggregate.skills["tidy-up"].invocations, 1)
        self.assertEqual(aggregate.skills["tidy-up"].merged_route_pairs, 0)

    def test_a_firing_only_the_typed_command_shows_is_one_firing_folding_nothing(self):
        aggregate = _one_store([
            _identity(), _turn(), _said("/demo:tidy-up now"),
            _fired("tidy-up", events.ROUTE_TEXT),
        ])
        self.assertEqual(aggregate.skills["tidy-up"].invocations, 1)
        self.assertEqual(aggregate.skills["tidy-up"].merged_route_pairs, 0)

    def test_a_tool_call_further_away_than_the_window_is_a_second_firing(self):
        aggregate = _one_store([
            _identity(), _turn(), _fired("tidy-up", events.ROUTE_TEXT),
            _turn(), _turn(), _turn(), _turn(), _fired("tidy-up"),
        ])
        self.assertEqual(aggregate.skills["tidy-up"].invocations, 2)
        self.assertEqual(aggregate.skills["tidy-up"].merged_route_pairs, 0)

    def test_another_skill_firing_in_between_leaves_the_two_detections_apart(self):
        aggregate = _one_store([
            _identity(), _turn(), _fired("tidy-up", events.ROUTE_TEXT),
            _fired("commit"), _fired("tidy-up"),
        ])
        self.assertEqual(aggregate.skills["tidy-up"].invocations, 2)

    def test_a_command_typed_after_a_tool_call_is_a_second_firing_and_a_retry(self):
        aggregate = _one_store([
            _identity(), _turn(), _fired("tidy-up"),
            _turn(), _said("/demo:tidy-up now"), _fired("tidy-up", events.ROUTE_TEXT),
        ])
        self.assertEqual(aggregate.skills["tidy-up"].invocations, 2)
        self.assertEqual(aggregate.skills["tidy-up"].retries, 2)

    def test_the_two_routes_are_never_folded_across_a_session_boundary(self):
        aggregate = _one_store([
            _identity("s-1"), _turn(), _fired("tidy-up", events.ROUTE_TEXT),
            _identity("s-2"), _turn(), _fired("tidy-up"),
        ])
        self.assertEqual(aggregate.skills["tidy-up"].invocations, 2)
        self.assertEqual(aggregate.skills["tidy-up"].merged_route_pairs, 0)


class TestCorrections(unittest.TestCase):
    def test_what_the_operator_says_after_a_skill_fires_is_a_correction(self):
        aggregate = _one_store([
            _identity(), _turn(), _fired("commit"), _turn(), _said("no, not like that"),
        ])
        self.assertEqual(aggregate.skills["commit"].corrections, 1)

    def test_a_tool_answer_after_a_skill_fires_is_not_a_correction(self):
        aggregate = _one_store([
            _identity(), _turn(), _fired("commit"), _turn(), _turn(), _turn(),
        ])
        self.assertEqual(aggregate.skills["commit"].corrections, 0)

    def test_what_is_said_before_any_skill_fires_is_no_skill_correction(self):
        aggregate = _one_store([_identity(), _turn(), _said(), _turn(), _fired("commit")])
        self.assertEqual(aggregate.skills["commit"].corrections, 0)

    def test_a_correction_is_attributed_when_a_different_skill_fires(self):
        aggregate = _one_store([
            _identity(), _turn(), _fired("commit"), _turn(), _said(),
            _turn(), _fired("plan-create"),
        ])
        self.assertEqual(aggregate.skills["commit"].corrections, 1)
        self.assertEqual(aggregate.skills["plan-create"].corrections, 0)

    def test_a_correction_still_unattributed_at_the_end_is_attributed_there(self):
        aggregate = _one_store([_identity(), _turn(), _fired("commit"), _said(), _said()])
        self.assertEqual(aggregate.skills["commit"].corrections, 2)

    def test_the_utterance_that_fires_a_skill_is_not_also_a_correction(self):
        aggregate = _one_store([
            _identity(), _turn(), _fired("commit"),
            _turn(), _said("/claude-skills:plan-create instead"),
            _fired("plan-create", events.ROUTE_TEXT),
        ])
        self.assertEqual(aggregate.skills["commit"].corrections, 0)

    def test_what_was_said_before_the_utterance_that_switches_skill_still_counts(self):
        aggregate = _one_store([
            _identity(), _turn(), _fired("commit"),
            _turn(), _said("no, not like that"),
            _turn(), _said("/claude-skills:plan-create instead"),
            _fired("plan-create", events.ROUTE_TEXT),
        ])
        self.assertEqual(aggregate.skills["commit"].corrections, 1)

    def test_a_retry_of_the_same_skill_leaves_what_came_before_it_unattributed(self):
        aggregate = _one_store([
            _identity(), _turn(), _fired("commit"), _turn(), _said(),
            _turn(), _fired("commit"),
        ])
        self.assertEqual(aggregate.skills["commit"].corrections, 0)


class TestAbandonment(unittest.TestCase):
    def test_a_session_failing_more_than_three_turns_in_ten_is_abandoned(self):
        produced = [_identity()] + [_turn()] * 10 + [_failed()] * 4 + [_fired("commit")]
        self.assertEqual(_one_store(produced).skills["commit"].abandoned_sessions, 1)

    def test_a_session_failing_exactly_three_turns_in_ten_is_not_abandoned(self):
        produced = [_identity()] + [_turn()] * 10 + [_failed()] * 3 + [_fired("commit")]
        self.assertEqual(_one_store(produced).skills["commit"].abandoned_sessions, 0)

    def test_a_session_with_no_turns_at_all_is_not_abandoned(self):
        aggregate = _one_store([_identity(), _failed(), _fired("commit")])
        self.assertEqual(aggregate.skills["commit"].abandoned_sessions, 0)


class TestAbandonmentWhereTheStoreRecordsIt(unittest.TestCase):
    def _direct_store(self, produced):
        return signals.aggregate([FakeStore("codex", produced, abandonment=True)])

    def test_the_store_own_record_of_a_break_off_is_what_counts(self):
        aggregate = self._direct_store([
            _identity(), _turn(), _fired("commit"), events.SessionAbandoned(),
        ])
        self.assertEqual(aggregate.skills["commit"].abandoned_sessions, 1)

    def test_a_failing_session_the_store_never_called_broken_off_is_not_abandoned(self):
        produced = [_identity()] + [_turn()] * 10 + [_failed()] * 4 + [_fired("commit")]
        self.assertEqual(self._direct_store(produced).skills["commit"].abandoned_sessions, 0)

    def test_a_break_off_recorded_twice_in_one_session_abandons_it_once(self):
        aggregate = self._direct_store([
            _identity(), _turn(), _fired("commit"),
            events.SessionAbandoned(), events.SessionAbandoned(),
        ])
        self.assertEqual(aggregate.skills["commit"].abandoned_sessions, 1)

    def test_a_store_with_no_such_record_has_its_abandonment_inferred(self):
        aggregate = _one_store([_identity(), _turn(), _fired("commit")])
        self.assertEqual(
            aggregate.skills["commit"].stores_with_inferred_abandonment, ("claude",)
        )

    def test_a_skill_seen_only_where_break_offs_are_recorded_names_no_such_store(self):
        aggregate = self._direct_store([_identity(), _turn(), _fired("commit")])
        self.assertEqual(aggregate.skills["commit"].stores_with_inferred_abandonment, ())

    def test_a_skill_seen_through_both_kinds_of_store_names_only_the_inferring_one(self):
        claude = FakeStore("claude", [_identity("s-1"), _turn(), _fired("commit")])
        codex = FakeStore("codex", [
            _identity("s-2"), _turn(), _fired("commit", events.ROUTE_TEXT),
        ], structural=False, abandonment=True)
        aggregate = signals.aggregate([claude, codex])
        self.assertEqual(
            aggregate.skills["commit"].stores_with_inferred_abandonment, ("claude",)
        )


class TestWholeSessionCountsPerSkill(unittest.TestCase):
    def test_every_skill_of_a_session_carries_that_whole_session_error_count(self):
        aggregate = _one_store([
            _identity(), _turn(), _fired("commit"), _turn(), _fired("plan-create"),
            _failed(), _failed(),
        ])
        self.assertEqual(aggregate.skills["commit"].tool_errors, 2)
        self.assertEqual(aggregate.skills["plan-create"].tool_errors, 2)

    def test_every_skill_of_a_session_carries_that_whole_session_turn_count(self):
        aggregate = _one_store([_identity(), _turn(), _turn(), _fired("commit")])
        self.assertEqual(aggregate.skills["commit"].turns, 2)

    def test_a_skill_is_counted_once_per_session_it_appears_in(self):
        aggregate = _one_store([
            _identity("s-1"), _turn(), _fired("commit"), _turn(), _fired("commit"),
            _identity("s-2"), _turn(), _fired("commit"),
        ])
        self.assertEqual(aggregate.skills["commit"].sessions, 2)

    def test_every_firing_is_counted_as_a_firing(self):
        aggregate = _one_store([
            _identity("s-1"), _turn(), _fired("commit"), _turn(), _fired("commit"),
            _identity("s-2"), _turn(), _fired("commit"),
        ])
        self.assertEqual(aggregate.skills["commit"].invocations, 3)


class TestSeveralStores(unittest.TestCase):
    def _two_stores(self):
        claude = FakeStore("claude", [
            _identity("s-1"), _turn(), _fired("commit"), _turn(), _said(),
        ])
        codex = FakeStore("codex", [
            _identity("s-2"), _turn(), _fired("commit", events.ROUTE_TEXT),
        ], structural=False)
        return signals.aggregate([claude, codex])

    def test_what_several_stores_saw_of_one_skill_becomes_one_count(self):
        self.assertEqual(self._two_stores().skills["commit"].invocations, 2)

    def test_the_skill_records_which_stores_saw_it(self):
        self.assertEqual(self._two_stores().skills["commit"].stores, ("claude", "codex"))

    def test_the_skill_records_which_routes_detected_it(self):
        self.assertEqual(self._two_stores().skills["commit"].routes, ("structural", "text"))

    def test_sessions_of_every_store_are_counted_together(self):
        self.assertEqual(self._two_stores().sessions, 2)

    def test_two_stores_sharing_a_session_name_are_kept_apart(self):
        first = FakeStore("claude", [_identity("s-1"), _turn()])
        second = FakeStore("codex", [_identity("s-1"), _turn()])
        self.assertEqual(signals.aggregate([first, second]).sessions, 2)

    def test_every_store_declaration_is_carried_into_the_aggregate(self):
        aggregate = self._two_stores()
        self.assertTrue(aggregate.capabilities["claude"].structural)
        self.assertFalse(aggregate.capabilities["codex"].structural)


class TestConfidenceDowngrade(unittest.TestCase):
    def test_a_skill_seen_through_a_store_with_no_structural_route_is_downgraded(self):
        aggregate = _one_store([_identity(), _turn(), _fired("commit")], structural=False)
        self.assertTrue(aggregate.skills["commit"].confidence_downgraded)

    def test_the_downgrade_names_the_stores_that_cannot_read_the_structural_route(self):
        aggregate = _one_store([_identity(), _turn(), _fired("commit")], structural=False)
        self.assertEqual(aggregate.skills["commit"].stores_without_structural, ("claude",))

    def test_a_skill_seen_only_where_the_structural_route_is_read_is_not_downgraded(self):
        aggregate = _one_store([_identity(), _turn(), _fired("commit")])
        self.assertFalse(aggregate.skills["commit"].confidence_downgraded)
        self.assertEqual(aggregate.skills["commit"].stores_without_structural, ())

    def test_a_skill_seen_partly_through_such_a_store_is_downgraded_too(self):
        claude = FakeStore("claude", [_identity("s-1"), _turn(), _fired("commit")])
        codex = FakeStore("codex", [
            _identity("s-2"), _turn(), _fired("commit", events.ROUTE_TEXT),
        ], structural=False)
        aggregate = signals.aggregate([claude, codex])
        self.assertTrue(aggregate.skills["commit"].confidence_downgraded)
        self.assertEqual(aggregate.skills["commit"].stores_without_structural, ("codex",))


class TestUtterancesReadAsASuperset(unittest.TestCase):
    def _superset_session(self):
        return events.SessionIdentity(
            session_id="s-1", project="-w-notes", utterances_are_superset=True
        )

    def test_a_session_whose_utterances_are_a_superset_is_counted_under_its_store(self):
        store = FakeStore("codex", [self._superset_session(), _turn()], structural=False)
        self.assertEqual(
            signals.aggregate([store]).superset_utterance_sessions, {"codex": 1}
        )

    def test_a_store_that_read_no_such_session_is_not_named_at_all(self):
        self.assertEqual(
            _one_store([_identity(), _turn()]).superset_utterance_sessions, {}
        )

    def test_only_the_sessions_read_that_way_are_counted(self):
        store = FakeStore("codex", [
            self._superset_session(), _turn(), _identity("s-2"), _turn(),
        ], structural=False)
        self.assertEqual(
            signals.aggregate([store]).superset_utterance_sessions, {"codex": 1}
        )


class TestProjects(unittest.TestCase):
    def test_a_stored_key_and_a_converted_path_are_the_same_project(self):
        stored = FakeStore("claude", [_identity("s-1", "-w-notes"), _turn()])
        converted = FakeStore("opencode", [
            _identity("s-2", events.project_slug(SEPARATOR + SEPARATOR.join(("w", "notes")))),
            _turn(),
        ])
        self.assertEqual(signals.aggregate([stored, converted]).projects, ("-w-notes",))

    def test_separate_projects_are_reported_separately(self):
        first = FakeStore("claude", [_identity("s-1", "-w-notes"), _turn()])
        second = FakeStore("opencode", [_identity("s-2", "-w-other"), _turn()])
        self.assertEqual(
            signals.aggregate([first, second]).projects, ("-w-notes", "-w-other")
        )


class TestWhatEachSessionShowed(unittest.TestCase):
    def test_every_session_read_is_kept_beside_the_totals(self):
        aggregate = _one_store([_identity("s-1"), _turn(), _identity("s-2"), _turn()])
        self.assertEqual([one.session_id for one in aggregate.per_session], ["s-1", "s-2"])

    def test_each_kept_session_names_the_store_it_was_read_from(self):
        claude = FakeStore("claude", [_identity("s-1"), _turn()])
        codex = FakeStore("codex", [_identity("s-2"), _turn()], structural=False)
        aggregate = signals.aggregate([claude, codex])
        self.assertEqual([one.store for one in aggregate.per_session], ["claude", "codex"])

    def test_reading_no_store_at_all_keeps_no_session(self):
        self.assertEqual(signals.aggregate([]).per_session, ())


class TestScorableSkills(unittest.TestCase):
    def test_a_skill_that_was_never_fired_is_left_out_of_scoring(self):
        never = signals.SkillFriction(skill="unused")
        self.assertEqual(signals.scorable({"unused": never}), {})

    def test_a_skill_that_was_fired_is_kept_for_scoring(self):
        aggregate = _one_store([_identity(), _turn(), _fired("commit")])
        self.assertEqual(list(signals.scorable(aggregate.skills)), ["commit"])


class TestReadingEmptyStores(unittest.TestCase):
    def test_reading_no_store_at_all_yields_an_empty_aggregate(self):
        aggregate = signals.aggregate([])
        self.assertEqual(aggregate.skills, {})
        self.assertEqual(aggregate.sessions, 0)
        self.assertEqual(aggregate.capabilities, {})

    def test_a_store_that_read_nothing_still_declares_what_it_can_read(self):
        aggregate = signals.aggregate([FakeStore("codex", [], structural=False)])
        self.assertFalse(aggregate.capabilities["codex"].structural)
        self.assertEqual(aggregate.sessions, 0)


if __name__ == "__main__":
    unittest.main()
