#!/usr/bin/env python3
"""Friction signals, computed over normalized events and nothing else.

Nothing here knows how any runtime stores a session. The adapters have already
turned three storage formats into one vocabulary, so these counts are the same
counts whichever runtime produced them — which is the whole point of separating
the reading from the counting.

Four signals say a skill is not working well: it was fired again immediately, the
operator spoke again right after firing it, the session it ran in mostly failed,
and tool runs inside that session failed. The first two are attributed to the
skill; the last two are properties of the session, and every skill fired in that
session carries them.

Two of those attributions are inherited from the collector this replaces, and are
kept deliberately even though each reads oddly on its own:

A run of firings is reported as the length of the run, so the first repeat is 2
rather than 1. The thresholds in the scoring guide were calibrated against that
number, and changing the number without recalibrating them would move every
verdict silently.

A session's error and turn counts are attributed whole to every skill fired in it,
rather than divided among them. What is being measured is the friction around a
skill, and a session that failed throughout failed around each of them.

One attribution is deliberately not inherited. Corrections count what the operator
said, not every turn wearing the operator's role: one runtime records a tool answer
as a message in that role, so counting turns would read each tool run following a
skill as the operator correcting it.
"""

import dataclasses
import typing

from events import (
    Capabilities,
    Event,
    ROUTE_TEXT,
    SessionIdentity,
    SkillInvocation,
    ToolError,
    Turn,
    UserText,
    declared_capabilities,
)

# A firing this many turns or fewer after the previous firing of the same skill is
# the same attempt being made again rather than the skill being used afresh.
RETRY_WINDOW_TURNS = 3

# A session whose failed tool runs exceed this share of its turns is read as having
# been abandoned rather than finished.
ABANDONMENT_ERROR_SHARE = 0.3

NO_SESSION = ""
NO_PROJECT = ""


@dataclasses.dataclass(frozen=True)
class SkillInSession:
    """What one session shows about one skill."""

    skill: str
    invocations: int
    retries: int
    corrections: int
    routes: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class SessionSignals:
    """What one session shows, as a whole and per skill."""

    store: str
    session_id: str
    project: str
    turns: int
    tool_errors: int
    abandoned: bool
    skills: tuple[SkillInSession, ...]


@dataclasses.dataclass(frozen=True)
class SkillFriction:
    """Everything read about one skill, across every session of every store.

    A downgrade is not a smaller number: it says the count itself is incomplete,
    because a store it was seen through cannot read one of the two detection
    routes at all. The stores that cannot are named so a report can say which.
    """

    skill: str
    invocations: int = 0
    sessions: int = 0
    retries: int = 0
    corrections: int = 0
    abandoned_sessions: int = 0
    tool_errors: int = 0
    turns: int = 0
    stores: tuple[str, ...] = ()
    routes: tuple[str, ...] = ()
    stores_without_structural: tuple[str, ...] = ()
    confidence_downgraded: bool = False


@dataclasses.dataclass(frozen=True)
class Aggregate:
    """One reading of every store: the skills, the totals, and what was readable."""

    skills: dict[str, SkillFriction]
    capabilities: dict[str, Capabilities]
    projects: tuple[str, ...]
    sessions: int
    turns: int
    tool_errors: int


def split_sessions(
    stream: typing.Iterable[Event],
) -> typing.Iterator[tuple[SessionIdentity | None, list[Event]]]:
    """Cut one store's stream into sessions at each announced identity.

    Events arriving before any identity are yielded under no identity rather than
    dropped: a store that failed to announce a session should lose the session's
    name, not the session.
    """
    identity: SessionIdentity | None = None
    collected: list[Event] = []
    started = False
    for event in stream:
        if isinstance(event, SessionIdentity):
            if started or collected:
                yield identity, collected
            identity, collected, started = event, [], True
            continue
        collected.append(event)
    if started or collected:
        yield identity, collected


def session_signals(
    store: str, identity: SessionIdentity | None, stream: typing.Iterable[Event]
) -> SessionSignals:
    """Count one session's friction.

    A firing ends the run of corrections attributed to the previous skill only when
    it is a different skill. A retry of the same skill leaves what was said before
    it unattributed, which is the collector's behaviour this replaces.

    An utterance that fires a skill by slash command is that firing, not a
    correction of whatever ran before it. The adapters emit the utterance and then
    the firing it carries, so the utterance is discounted here when the firing
    arrives by the text route — otherwise every switch of skill by slash command
    would add a correction to the skill being switched away from.
    """
    turns = 0
    tool_errors = 0
    invocations: dict[str, int] = {}
    retries: dict[str, int] = {}
    corrections: dict[str, int] = {}
    routes: dict[str, set[str]] = {}
    last_skill: str | None = None
    last_skill_turn = 0
    said_since_skill = 0

    for event in stream:
        if isinstance(event, Turn):
            turns += 1
        elif isinstance(event, ToolError):
            tool_errors += 1
        elif isinstance(event, SkillInvocation):
            skill = event.skill
            invocations[skill] = invocations.get(skill, 0) + 1
            routes.setdefault(skill, set()).add(event.route)
            if event.route == ROUTE_TEXT and said_since_skill > 0:
                said_since_skill -= 1
            if last_skill == skill and (turns - last_skill_turn) <= RETRY_WINDOW_TURNS:
                retries[skill] = retries.get(skill, 1) + 1
            elif last_skill is not None and said_since_skill > 0:
                corrections[last_skill] = (
                    corrections.get(last_skill, 0) + said_since_skill
                )
            last_skill = skill
            last_skill_turn = turns
            said_since_skill = 0
        elif isinstance(event, UserText) and last_skill is not None:
            said_since_skill += 1

    if last_skill is not None and said_since_skill > 0:
        corrections[last_skill] = corrections.get(last_skill, 0) + said_since_skill

    return SessionSignals(
        store=store,
        session_id=identity.session_id if identity is not None else NO_SESSION,
        project=identity.project if identity is not None else NO_PROJECT,
        turns=turns,
        tool_errors=tool_errors,
        abandoned=turns > 0 and tool_errors > turns * ABANDONMENT_ERROR_SHARE,
        skills=tuple(
            SkillInSession(
                skill=skill,
                invocations=count,
                retries=retries.get(skill, 0),
                corrections=corrections.get(skill, 0),
                routes=tuple(sorted(routes.get(skill, ()))),
            )
            for skill, count in sorted(invocations.items())
        ),
    )


def store_signals(store) -> list[SessionSignals]:
    """Every session one store holds, counted."""
    return [
        session_signals(store.name, identity, collected)
        for identity, collected in split_sessions(store.events())
    ]


@dataclasses.dataclass
class _Running:
    """The counts of one skill while sessions are still being added to it."""

    invocations: int = 0
    retries: int = 0
    corrections: int = 0
    abandoned_sessions: int = 0
    tool_errors: int = 0
    turns: int = 0
    sessions: set = dataclasses.field(default_factory=set)
    stores: set = dataclasses.field(default_factory=set)
    routes: set = dataclasses.field(default_factory=set)


def _add_session(running: dict[str, _Running], session: SessionSignals) -> None:
    """Fold one session's counts into the running totals of each skill it fired."""
    for entry in session.skills:
        totals = running.setdefault(entry.skill, _Running())
        totals.invocations += entry.invocations
        totals.retries += entry.retries
        totals.corrections += entry.corrections
        totals.tool_errors += session.tool_errors
        totals.turns += session.turns
        totals.abandoned_sessions += 1 if session.abandoned else 0
        totals.sessions.add((session.store, session.session_id))
        totals.stores.add(session.store)
        totals.routes.update(entry.routes)


def _finished(
    skill: str, totals: _Running, capabilities: dict[str, Capabilities]
) -> SkillFriction:
    """Freeze one skill's running totals, with the confidence its stores allow."""
    unreadable = tuple(
        sorted(
            store
            for store in totals.stores
            if store in capabilities and not capabilities[store].structural
        )
    )
    return SkillFriction(
        skill=skill,
        invocations=totals.invocations,
        sessions=len(totals.sessions),
        retries=totals.retries,
        corrections=totals.corrections,
        abandoned_sessions=totals.abandoned_sessions,
        tool_errors=totals.tool_errors,
        turns=totals.turns,
        stores=tuple(sorted(totals.stores)),
        routes=tuple(sorted(totals.routes)),
        stores_without_structural=unreadable,
        confidence_downgraded=bool(unreadable),
    )


def aggregate(stores) -> Aggregate:
    """Read every store into one set of counts, keeping what each store can read.

    A store's declaration travels into the result whether or not it read anything,
    so a report can distinguish a store that found no friction from one that cannot
    see friction of that kind at all.
    """
    stores = list(stores)
    capabilities = declared_capabilities(stores)
    running: dict[str, _Running] = {}
    counted_sessions: set[tuple[str, str]] = set()
    projects: set[str] = set()
    turns = 0
    tool_errors = 0

    for store in stores:
        for session in store_signals(store):
            counted_sessions.add((session.store, session.session_id))
            if session.project != NO_PROJECT:
                projects.add(session.project)
            turns += session.turns
            tool_errors += session.tool_errors
            _add_session(running, session)

    return Aggregate(
        skills={
            skill: _finished(skill, totals, capabilities)
            for skill, totals in sorted(running.items())
        },
        capabilities=capabilities,
        projects=tuple(sorted(projects)),
        sessions=len(counted_sessions),
        turns=turns,
        tool_errors=tool_errors,
    )


def scorable(skills: dict[str, SkillFriction]) -> dict[str, SkillFriction]:
    """The skills a score may be computed for: those actually fired.

    A skill never fired has no rate to compute — every rate divides by the number
    of firings — so it is left out rather than scored as frictionless.
    """
    return {skill: friction for skill, friction in skills.items() if friction.invocations}
