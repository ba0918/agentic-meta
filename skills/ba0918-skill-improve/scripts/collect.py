#!/usr/bin/env python3
"""Reads the selected session stores and writes one friction measurement as JSON.

This is the entry point and nothing else: it chooses the stores, hands them to the
aggregation, and shapes the answer. No count is computed here.

What the result says about itself matters as much as the counts. Every store the
run asked for appears in the summary with what it could actually be read for — the
two detection routes, how much of the store its failures could be read out of, and
whether a session being broken off was recorded by the store or inferred from how
much of it failed. A number drawn through a route a
store cannot read is not a smaller number but a different measurement, and a
report that cannot tell the two apart will recommend fixing a skill nobody ran.

A store that is not on this machine is reported and stepped over, never dropped in
silence: an operator who mistyped a location and an operator who does not run that
runtime would otherwise read the same clean result. A store that is here and cannot
be read is reported the same way and kept apart from absence — the reading of that
one store stops where it broke, rather than one runtime's changed schema ending the
measurement of the other two.

Where the reading found no skill firing at all, the result says so and says the
analysis should not go on. Every friction rate divides by the number of firings, so
an analysis of nothing produces scores out of nothing.

Two parts of the collector this replaces are deliberately not reproduced. There is
no per-invocation list: the normalized events carry no turn index or timestamp per
firing, which is the price of the vocabulary being poor enough that three stores
can fill it. And the per-session rows name no session and no file — the report this
feeds forbids session identifiers, and a session file's path is under the
operator's home, which is exactly what the credential masking exists to keep out.

The credential warnings are raised over utterances only. The collector this
replaces scanned every raw line of every session file, which also covered bodies it
never emitted; here the utterances are the only bodies that ever leave a session,
so they are the only ones a warning can be about.
"""

import argparse
import datetime
import json
import os
import pathlib
import sys
import typing

import secret_detect
import signals
import stores
from events import Capabilities, StoreUnreadable, UserText

EXIT_OK = 0
EXIT_REFUSED = 2

DEFAULT_DAYS = 30
DEFAULT_STORE = stores.EVERY_STORE

# How a store's abandonment count was arrived at.
ABANDONMENT_RECORDED = "recorded"
ABANDONMENT_INFERRED = "inferred"

# How much of a store its failures could be read out of.
ERROR_DETECTION_FULL = "full"
ERROR_DETECTION_PARTIAL = "partial"

NOTHING_FIRED = (
    "no skill firing was found in the period, so there is nothing to score"
)


class WatchedForSecrets:
    """One store's events, passed through unchanged, with utterances watched.

    A store is wrapped rather than the aggregation being taught about credentials:
    the aggregation counts friction and knows nothing about what a body contains,
    and teaching it would put a second responsibility into the one layer every
    store's numbers pass through. Wrapping also keeps the reading single-pass —
    the events are watched as they go by, not read a second time.
    """

    def __init__(self, inner, found: list[dict[str, str]]):
        self.inner = inner
        self.name = inner.name
        self.capabilities = inner.capabilities
        self._found = found

    def events(self) -> typing.Iterator:
        """Yield the wrapped store's events, noting credentials seen in utterances."""
        for event in self.inner.events():
            if isinstance(event, UserText):
                self._found.extend(secret_detect.detect_secrets(event.text))
            yield event


class ReadAsFarAsItGoes:
    """One store's events, ending that store's reading rather than the whole run.

    An adapter that meets a store it cannot read says so instead of returning
    nothing, because "here and unreadable" and "not here" are different facts and a
    reader told only that a store held nothing cannot tell which of the two it is
    reading. Catching it per store keeps the difference and keeps the run: the
    reading stops where it broke, the reason is kept for the result, and the stores
    after it are still read.

    It wraps for the same reason the credential watch does. The aggregation counts
    friction and knows nothing about where events came from, and teaching it to
    would put the handling of one storage format into the one layer every store's
    numbers pass through.
    """

    def __init__(self, inner, unreadable: dict[str, str]):
        self.inner = inner
        self.name = inner.name
        self.capabilities = inner.capabilities
        self._unreadable = unreadable

    def events(self) -> typing.Iterator:
        """Yield the wrapped store's events until it says it cannot be read on."""
        try:
            yield from self.inner.events()
        except StoreUnreadable as refusal:
            self._unreadable[self.name] = str(refusal)


def period_start(days: int, now: datetime.datetime) -> datetime.datetime:
    """The oldest moment inside the period asked for."""
    return now - datetime.timedelta(days=days)


def shown_location(location: pathlib.Path | str) -> str:
    """A location as the result may show it, with the operator's home masked.

    The stores sit under the operator's home directory, whose name is the operator.
    The result is read by other agents and pasted into reports, so the same masking
    every harvested body passes through is applied to the locations as well.
    """
    return secret_detect.mask_secrets(str(location))


def store_report(
    reading: stores.Reading,
    capabilities: dict[str, Capabilities],
    superset_sessions: dict[str, int],
) -> dict[str, typing.Any]:
    """What one store was read at, and what it could be read for."""
    declared = capabilities.get(reading.name, Capabilities(text=False, structural=False))
    return {
        "location": shown_location(reading.location),
        "present": reading.present,
        "text_route": declared.text,
        "structural_route": declared.structural,
        "abandonment": (
            ABANDONMENT_RECORDED if declared.abandonment_signal else ABANDONMENT_INFERRED
        ),
        "error_detection": (
            ERROR_DETECTION_PARTIAL
            if declared.error_detection_partial
            else ERROR_DETECTION_FULL
        ),
        "superset_utterance_sessions": superset_sessions.get(reading.name, 0),
    }


def friction_report(friction: signals.SkillFriction) -> dict[str, typing.Any]:
    """One skill's counts, under the names the scoring guide divides by."""
    return {
        "invocation_count": friction.invocations,
        "retry_count": friction.retries,
        "correction_turns": friction.corrections,
        "session_abandoned_count": friction.abandoned_sessions,
        "tool_error_count": friction.tool_errors,
        "total_turns_to_completion": friction.turns,
        "sessions": friction.sessions,
        "stores": list(friction.stores),
        "routes": list(friction.routes),
        "merged_route_pairs": friction.merged_route_pairs,
        "stores_without_structural": list(friction.stores_without_structural),
        "confidence_downgraded": friction.confidence_downgraded,
        "stores_with_inferred_abandonment": list(friction.stores_with_inferred_abandonment),
    }


def session_report(session: signals.SessionSignals) -> dict[str, typing.Any]:
    """What one session showed, with nothing in it that names the session."""
    return {
        "store": session.store,
        "project": session.project,
        "turns": session.turns,
        "tool_errors": session.tool_errors,
        "abandoned": session.abandoned,
        "skill_count": len(session.skills),
        "utterances_are_superset": session.utterances_are_superset,
    }


def deduplicate_secrets(found: list[dict[str, str]]) -> list[dict[str, str]]:
    """One warning per kind of credential, in the order each kind first appeared."""
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for warning in found:
        key = f"{warning['type']}:{warning['masked']}"
        if key not in seen:
            seen.add(key)
            unique.append(warning)
    return unique


def absence_notes(readings: list[stores.Reading]) -> list[str]:
    """One note for every store the run asked for and did not find."""
    return [
        f"the {reading.name} store was not found at {shown_location(reading.location)}"
        " — it was read as empty and the run went on"
        for reading in readings
        if not reading.present
    ]


def unreadable_notes(
    readings: list[stores.Reading], unreadable: dict[str, str]
) -> list[str]:
    """One note for every store the run found and could not read to the end.

    Kept apart from the absence notes because the two facts differ in what they
    say about the numbers. A store that is not on this machine contributed nothing
    and was never going to; a store that broke off may have contributed part of
    what it holds. The reason is masked like every other text this result carries.
    """
    return [
        f"the {reading.name} store at {shown_location(reading.location)} could not be"
        f" read to the end ({secret_detect.mask_secrets(unreadable[reading.name])})"
        " — the reading stopped there and the run went on"
        for reading in readings
        if reading.name in unreadable
    ]


def build_result(
    readings: list[stores.Reading],
    aggregate: signals.Aggregate,
    found_secrets: list[dict[str, str]],
    arguments: argparse.Namespace,
    project: str | None,
    now: datetime.datetime,
    unreadable: dict[str, str],
) -> dict[str, typing.Any]:
    """Shape one reading into the result the analysis reads."""
    scorable = signals.scorable(aggregate.skills)
    return {
        "summary": {
            "collection_timestamp": now.isoformat(),
            "days": arguments.days,
            "project_filter": project,
            "all_projects": arguments.all_projects,
            "projects_scanned": list(aggregate.projects),
            "stores": {
                reading.name: store_report(
                    reading, aggregate.capabilities, aggregate.superset_utterance_sessions
                )
                for reading in readings
            },
            "sessions_found": aggregate.sessions,
            "total_turns": aggregate.turns,
            "total_tool_errors": aggregate.tool_errors,
            "total_skill_invocations": sum(
                friction.invocations for friction in scorable.values()
            ),
            "unique_skills_used": sorted(scorable),
        },
        "analysis": {
            "proceed": bool(scorable),
            "reason": None if scorable else NOTHING_FIRED,
        },
        "sessions": [session_report(session) for session in aggregate.per_session],
        "friction_signals": {
            skill: friction_report(friction) for skill, friction in scorable.items()
        },
        "secret_warnings": deduplicate_secrets(found_secrets),
        "notes": absence_notes(readings) + unreadable_notes(readings, unreadable),
    }


def write_result(result: dict[str, typing.Any], output_path: str | None) -> None:
    """Write the result to the named file, or to the output when none is named.

    The named file is replaced in one step. A reader that opened the previous
    result would otherwise be able to see a half-written one, and a run that failed
    part way would leave the previous measurement destroyed rather than intact.
    """
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if output_path is None:
        print(text)
        return
    partial = output_path + ".tmp"
    try:
        with open(partial, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.write("\n")
        os.replace(partial, output_path)
    finally:
        try:
            os.unlink(partial)
        except FileNotFoundError:
            pass


def parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    """The command line this entry point accepts.

    The per-store location arguments are declared from the registry rather than
    listed here, so a store added later brings its own argument with it.
    """
    parser = argparse.ArgumentParser(
        description="Read the session stores and measure skill friction",
    )
    parser.add_argument(
        "--store", default=DEFAULT_STORE,
        help="which store to read: one of " + ", ".join(stores.SELECTABLE),
    )
    for kind in stores.REGISTRY:
        parser.add_argument(
            kind.location_flag, default=None,
            help=f"where to read the {kind.name} store (default: its own location)",
        )
    parser.add_argument(
        "--days", type=int, default=DEFAULT_DAYS,
        help=f"how many days back to read (default: {DEFAULT_DAYS})",
    )
    parser.add_argument(
        "--project", default=None,
        help="which project to read, written as --project=KEY because a project key"
             " begins with a hyphen (default: the working directory)",
    )
    parser.add_argument(
        "--all-projects", action="store_true", default=False,
        help="read every project rather than one",
    )
    parser.add_argument(
        "--output", default=None,
        help="where to write the result (default: the output)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Read the selected stores and write one measurement."""
    arguments = parse_arguments(argv)
    try:
        stores.selected_names(arguments.store)
    except ValueError as refusal:
        print(f"error: {refusal}", file=sys.stderr)
        return EXIT_REFUSED

    now = datetime.datetime.now(datetime.timezone.utc)
    project = stores.chosen_project(arguments.project, arguments.all_projects)
    readings = stores.build_stores(
        arguments.store,
        stores.given_locations(arguments),
        since=period_start(arguments.days, now),
        project=project,
    )

    found_secrets: list[dict[str, str]] = []
    unreadable: dict[str, str] = {}
    aggregate = signals.aggregate([
        ReadAsFarAsItGoes(WatchedForSecrets(reading.store, found_secrets), unreadable)
        for reading in readings
    ])
    result = build_result(
        readings, aggregate, found_secrets, arguments, project, now, unreadable
    )
    write_result(result, arguments.output)

    for note in result["notes"]:
        print(f"[collect] {note}", file=sys.stderr)
    if not result["analysis"]["proceed"]:
        print(f"[collect] {NOTHING_FIRED}", file=sys.stderr)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
