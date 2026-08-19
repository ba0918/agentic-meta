#!/usr/bin/env python3
"""Unit tests for events.py."""

import dataclasses
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import events

AT = datetime.datetime(2026, 8, 19, 12, 0, tzinfo=datetime.timezone.utc)


class FakeStore:
    """An adapter standing in for a real one: a name, declared capabilities, events."""

    def __init__(self, name, capabilities, produced=()):
        self.name = name
        self.capabilities = capabilities
        self._produced = tuple(produced)

    def events(self):
        return iter(self._produced)


class TestNormalizedEventVocabulary(unittest.TestCase):
    def test_the_vocabulary_is_limited_to_the_kinds_the_friction_signals_need(self):
        self.assertEqual(
            events.NORMALIZED_EVENT_TYPES,
            (
                events.UserText,
                events.SkillInvocation,
                events.ToolError,
                events.Turn,
                events.SessionAbandoned,
                events.SessionIdentity,
            ),
        )


class TestSessionAbandoned(unittest.TestCase):
    def test_it_says_the_session_was_broken_off_and_nothing_more(self):
        self.assertEqual(dataclasses.fields(events.SessionAbandoned), ())

    def test_it_cannot_be_altered_once_an_adapter_has_produced_it(self):
        broken_off = events.SessionAbandoned()
        with self.assertRaises(Exception):
            broken_off.reason = "interrupted"


class TestUserText(unittest.TestCase):
    def test_it_carries_the_body_of_the_utterance(self):
        self.assertEqual(events.UserText(text="/improve please", at=AT).text, "/improve please")

    def test_it_records_when_the_utterance_was_made(self):
        self.assertEqual(events.UserText(text="/improve please", at=AT).at, AT)

    def test_it_refuses_a_time_carrying_no_zone(self):
        with self.assertRaises(ValueError):
            events.UserText(text="/improve please", at=datetime.datetime(2026, 8, 19, 12, 0))


class TestSkillInvocation(unittest.TestCase):
    def test_it_records_the_skill_and_the_route_that_detected_it(self):
        found = events.SkillInvocation(skill="ba0918-trigger-eval", route=events.ROUTE_STRUCTURAL)
        self.assertEqual(found.skill, "ba0918-trigger-eval")
        self.assertEqual(found.route, "structural")

    def test_a_slash_command_in_an_utterance_is_the_text_route(self):
        self.assertEqual(events.ROUTE_TEXT, "text")
        self.assertEqual(
            events.SkillInvocation(skill="commit", route=events.ROUTE_TEXT).route, "text"
        )

    def test_it_refuses_a_route_that_is_not_one_of_the_two_detection_routes(self):
        with self.assertRaises(ValueError):
            events.SkillInvocation(skill="commit", route="guessed")


class TestToolError(unittest.TestCase):
    def test_it_names_the_tool_whose_run_failed(self):
        self.assertEqual(events.ToolError(tool="Bash").tool, "Bash")


class TestTurn(unittest.TestCase):
    def test_it_records_which_side_spoke_and_when(self):
        turn = events.Turn(role=events.ROLE_USER, at=AT)
        self.assertEqual(turn.role, "user")
        self.assertEqual(turn.at, AT)

    def test_it_refuses_a_role_other_than_user_or_assistant(self):
        for role in ("system", "attachment", "summary"):
            with self.assertRaises(ValueError, msg=role):
                events.Turn(role=role, at=AT)

    def test_it_refuses_a_time_carrying_no_zone(self):
        with self.assertRaises(ValueError):
            events.Turn(role=events.ROLE_USER, at=datetime.datetime(2026, 8, 19, 12, 0))


class TestSessionIdentity(unittest.TestCase):
    def test_it_names_the_session_and_the_project_the_session_ran_in(self):
        identity = events.SessionIdentity(session_id="s-1", project="-home-someone-work")
        self.assertEqual(identity.session_id, "s-1")
        self.assertEqual(identity.project, "-home-someone-work")

    def test_a_session_is_read_as_holding_only_real_utterances_unless_it_says_otherwise(self):
        identity = events.SessionIdentity(session_id="s-1", project="-w-notes")
        self.assertFalse(identity.utterances_are_superset)

    def test_a_session_can_declare_that_its_utterances_are_a_superset(self):
        identity = events.SessionIdentity(
            session_id="s-1", project="-w-notes", utterances_are_superset=True
        )
        self.assertTrue(identity.utterances_are_superset)


class TestProjectSlug(unittest.TestCase):
    def test_a_working_directory_path_becomes_the_key_every_store_meets_on(self):
        separator = "/"
        path = separator + separator.join(("home", "someone", "develop", "notes"))
        self.assertEqual(events.project_slug(path), "-home-someone-develop-notes")

    def test_the_leading_separator_survives_as_the_leading_hyphen_of_the_key(self):
        separator = "/"
        path = separator + separator.join(("home", "someone", "work"))
        self.assertTrue(events.project_slug(path).startswith("-"))

    def test_a_dot_is_converted_like_any_other_character_outside_the_key_alphabet(self):
        separator = "/"
        path = separator + separator.join(("home", "someone", ".notes"))
        self.assertEqual(events.project_slug(path), "-home-someone--notes")

    def test_capital_letters_are_carried_into_the_key_unchanged(self):
        separator = "/"
        path = separator + separator.join(("tmp", "Crates", "Core"))
        self.assertEqual(events.project_slug(path), "-tmp-Crates-Core")

    def test_a_hyphen_inside_a_directory_name_is_indistinguishable_from_a_separator(self):
        separator = "/"
        hyphenated = separator + separator.join(("home", "someone", "my-work"))
        nested = separator + separator.join(("home", "someone", "my", "work"))
        self.assertEqual(events.project_slug(hyphenated), events.project_slug(nested))


class TestEventImmutability(unittest.TestCase):
    def test_an_event_cannot_be_altered_once_an_adapter_has_produced_it(self):
        turn = events.Turn(role=events.ROLE_USER, at=AT)
        with self.assertRaises(Exception):
            turn.role = events.ROLE_ASSISTANT


class TestCapabilities(unittest.TestCase):
    def test_a_store_declares_whether_it_detects_by_text_and_by_structure(self):
        declared = events.Capabilities(text=True, structural=False)
        self.assertTrue(declared.text)
        self.assertFalse(declared.structural)

    def test_a_store_is_read_as_having_no_record_of_abandonment_unless_it_says_so(self):
        self.assertFalse(events.Capabilities(text=True, structural=True).abandonment_signal)

    def test_a_store_that_records_abandonment_itself_declares_that_it_does(self):
        declared = events.Capabilities(
            text=True, structural=False, abandonment_signal=True
        )
        self.assertTrue(declared.abandonment_signal)


class TestAdapterContract(unittest.TestCase):
    def test_a_name_declared_capabilities_and_an_event_stream_make_a_session_store(self):
        store = FakeStore("claude", events.Capabilities(text=True, structural=True))
        self.assertIsInstance(store, events.SessionStore)

    def test_a_reader_that_declares_no_capabilities_is_not_a_session_store(self):
        class Undeclared:
            name = "mystery"

            def events(self):
                return iter(())

        self.assertNotIsInstance(Undeclared(), events.SessionStore)


class TestDeclaredCapabilitiesByStore(unittest.TestCase):
    def test_each_store_is_reported_under_its_own_name(self):
        claude = FakeStore("claude", events.Capabilities(text=True, structural=True))
        opencode = FakeStore("opencode", events.Capabilities(text=True, structural=True))
        self.assertEqual(
            events.declared_capabilities([claude, opencode]),
            {
                "claude": events.Capabilities(text=True, structural=True),
                "opencode": events.Capabilities(text=True, structural=True),
            },
        )

    def test_a_store_detecting_no_structure_carries_that_absence_into_the_aggregate(self):
        codex = FakeStore("codex", events.Capabilities(text=True, structural=False))
        claude = FakeStore("claude", events.Capabilities(text=True, structural=True))
        aggregate = events.declared_capabilities([codex, claude])
        self.assertFalse(aggregate["codex"].structural)
        self.assertTrue(aggregate["claude"].structural)

    def test_two_stores_sharing_a_name_are_refused_rather_than_one_replacing_the_other(self):
        first = FakeStore("codex", events.Capabilities(text=True, structural=False))
        second = FakeStore("codex", events.Capabilities(text=True, structural=True))
        with self.assertRaises(ValueError):
            events.declared_capabilities([first, second])


if __name__ == "__main__":
    unittest.main()
