#!/usr/bin/env python3
"""Friction signals, computed over normalized events and nothing else.

Nothing here knows how any runtime stores a session. The adapters have already
turned three storage formats into one vocabulary, so these counts are the same
counts whichever runtime produced them — which is the whole point of separating
the reading from the counting.

Four signals say a skill is not working well: it was fired again immediately, the
operator spoke again right after firing it, the session it ran in was broken off,
and tool runs inside that session failed. The first two are attributed to the
skill; the last two are properties of the session, and every skill fired in that
session carries them.

One firing can be observed twice. Where a store reads both routes, an operator
typing a slash command leaves a text detection and then the runtime's own record of
the call that command produced. The pair is folded into one firing, and the record
the runtime kept is the route that survives; the measurement behind that, and the
reason counting both is not coverage, is on one_firing_seen_twice.

Being broken off is read two ways, because only one of the three stores writes it
down. Where a store does, its own record decides and nothing is inferred. Where a
store does not, it is inferred from the share of the session's turns that failed.
The inference is never laid on top of a store that keeps the record — that would
count one break-off twice — and which of the two produced a number is carried into
the result, since a report presenting them as one measurement would be wrong about
what it measured.

Two of those attributions are inherited from the collector this replaces, and are
kept deliberately even though each reads oddly on its own:

A run of firings is reported as the length of the run, so the first repeat is 2
rather than 1. The thresholds in the scoring guide assume that number. No
calibration stands behind them — they came over with the counting, and no
measurement they were fitted to was ever recorded — so changing the number would
move an inherited boundary rather than a fitted one, silently and for every skill
at once.

A session's error and turn counts are attributed whole to every skill fired in it,
rather than divided among them. What is being measured is the friction around a
skill, and a session that failed throughout failed around each of them.

One attribution is deliberately not inherited. A correction is an utterance, not a
turn wearing the operator's role. The two sets are close, now that an adapter
raises a turn only where something was said, but they answer different questions: a
turn is the boundary the retry window is measured in, and an utterance is a body
that was spoken. Counting utterances keeps the correction count right whatever a
store later decides to file under a speaking role.
"""

import dataclasses
import typing

from events import (
    Capabilities,
    Event,
    ROUTE_STRUCTURAL,
    ROUTE_TEXT,
    SessionAbandoned,
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

# A typed command and the tool call it produced are this many turns or fewer apart;
# further apart than that they are two firings. It is deliberately the retry window: a
# pair falling outside a narrower window would land inside the retry window instead,
# and be counted as the immediate repeat this folding exists to stop it being read as.
PAIRED_ROUTE_WINDOW_TURNS = RETRY_WINDOW_TURNS

# Where a store keeps no record of a session being broken off, a session whose
# failed tool runs exceed this share of its turns is read as having been broken off
# rather than finished.
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
    merged_route_pairs: int = 0


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
    utterances_are_superset: bool = False


@dataclasses.dataclass(frozen=True)
class SkillFriction:
    """Everything read about one skill, across every session of every store.

    A downgrade is not a smaller number: it says the count itself is incomplete,
    because a store it was seen through cannot read one of the two detection
    routes at all. The stores that cannot are named so a report can say which.

    The abandoned count is named the same way, for a different reason: it mixes
    stores that recorded a break-off with stores where one was inferred from the
    share of failed turns. Naming the inferring ones is what lets a report qualify
    the number instead of presenting a mixture as a single measurement.
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
    merged_route_pairs: int = 0
    stores_without_structural: tuple[str, ...] = ()
    confidence_downgraded: bool = False
    stores_with_inferred_abandonment: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class Aggregate:
    """One reading of every store: the skills, the totals, and what was readable.

    Sessions whose utterances could only be read as a superset of what the operator
    said are counted per store, so a report can qualify the correction counts drawn
    from that store instead of presenting them as exact.

    What each session showed is kept beside the totals. A caller wanting both the
    totals and the spread behind them would otherwise have to read every store a
    second time, and a store being written to while it is read can disagree with
    its own earlier answer.
    """

    skills: dict[str, SkillFriction]
    capabilities: dict[str, Capabilities]
    projects: tuple[str, ...]
    sessions: int
    turns: int
    tool_errors: int
    superset_utterance_sessions: dict[str, int] = dataclasses.field(default_factory=dict)
    per_session: tuple[SessionSignals, ...] = ()


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


def broken_off(
    recorded: bool, its_own_record: bool, turns: int, tool_errors: int
) -> bool:
    """Whether the session ended without finishing, by the best evidence there is.

    Where the store keeps its own record, that record decides and the share of
    failed runs is not consulted. Consulting both would count one break-off twice,
    and would let an inference the store never needed override its silence.
    """
    if recorded:
        return its_own_record
    return turns > 0 and tool_errors > turns * ABANDONMENT_ERROR_SHARE


def one_firing_seen_twice(
    previous_skill: str | None,
    previous_route: str | None,
    skill: str,
    route: str,
    turns_since: int,
) -> bool:
    """Whether this detection is the previous one seen again rather than a new firing.

    A store reading both routes sees one firing twice whenever the operator types the
    command: the utterance names the skill, and the runtime then records the tool call
    that utterance produced. Counted as written, that single firing arrives as two
    invocations of the same skill no turns apart — which is also what the retry rule
    reads as an immediate repeat. Measured on one synthetic session holding exactly one
    such firing, the reading was invocation_count 2 and retry_count 2, making
    retry_rate 1.0 on a firing that succeeded in one attempt. Since retry_rate carries
    the heaviest weight in the friction score, every skill fired by slash command was
    ranked as maximally frictional.

    Counting both and calling it coverage is the tempting alternative and is wrong.
    The two detections are not two observations to be added up; they are one firing
    observed along two routes. Adding them inflates the numerator of every rate while
    the denominator stays one session, so the skills the score points at are the ones
    the operator typed rather than the ones that went badly.

    Only a typed command followed by a tool call is folded, never the reverse. A tool
    call the runtime recorded first, with the operator then typing the command, is the
    operator firing the skill again after the agent had already fired it — a real
    second firing, and exactly the repeat the retry signal exists to catch.
    """
    return (
        previous_skill == skill
        and previous_route == ROUTE_TEXT
        and route == ROUTE_STRUCTURAL
        and turns_since <= PAIRED_ROUTE_WINDOW_TURNS
    )


def session_signals(
    store: str,
    identity: SessionIdentity | None,
    stream: typing.Iterable[Event],
    records_abandonment: bool = False,
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

    The route each firing was counted under is kept per firing rather than as a set,
    because folding a pair re-labels the firing already counted: what the operator
    typed is superseded by the runtime's own record of the call it produced.
    """
    turns = 0
    tool_errors = 0
    invocations: dict[str, int] = {}
    retries: dict[str, int] = {}
    corrections: dict[str, int] = {}
    firing_routes: dict[str, list[str]] = {}
    folded: dict[str, int] = {}
    last_skill: str | None = None
    last_route: str | None = None
    last_skill_turn = 0
    said_since_skill = 0
    its_own_record = False

    for event in stream:
        if isinstance(event, SessionAbandoned):
            its_own_record = True
        elif isinstance(event, Turn):
            turns += 1
        elif isinstance(event, ToolError):
            tool_errors += 1
        elif isinstance(event, SkillInvocation):
            skill = event.skill
            if one_firing_seen_twice(
                last_skill, last_route, skill, event.route, turns - last_skill_turn
            ):
                folded[skill] = folded.get(skill, 0) + 1
                firing_routes[skill][-1] = ROUTE_STRUCTURAL
                last_route = ROUTE_STRUCTURAL
                last_skill_turn = turns
                continue
            invocations[skill] = invocations.get(skill, 0) + 1
            firing_routes.setdefault(skill, []).append(event.route)
            if event.route == ROUTE_TEXT and said_since_skill > 0:
                said_since_skill -= 1
            if last_skill == skill and (turns - last_skill_turn) <= RETRY_WINDOW_TURNS:
                retries[skill] = retries.get(skill, 1) + 1
            elif last_skill is not None and said_since_skill > 0:
                corrections[last_skill] = (
                    corrections.get(last_skill, 0) + said_since_skill
                )
            last_skill = skill
            last_route = event.route
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
        utterances_are_superset=(
            identity.utterances_are_superset if identity is not None else False
        ),
        turns=turns,
        tool_errors=tool_errors,
        abandoned=broken_off(records_abandonment, its_own_record, turns, tool_errors),
        skills=tuple(
            SkillInSession(
                skill=skill,
                invocations=count,
                retries=retries.get(skill, 0),
                corrections=corrections.get(skill, 0),
                routes=tuple(sorted(set(firing_routes.get(skill, ())))),
                merged_route_pairs=folded.get(skill, 0),
            )
            for skill, count in sorted(invocations.items())
        ),
    )


def store_signals(store) -> list[SessionSignals]:
    """Every session one store holds, counted as that store's declaration allows."""
    return [
        session_signals(
            store.name, identity, collected, store.capabilities.abandonment_signal
        )
        for identity, collected in split_sessions(store.events())
    ]


@dataclasses.dataclass
class _Running:
    """The counts of one skill while sessions are still being added to it."""

    invocations: int = 0
    retries: int = 0
    corrections: int = 0
    merged_route_pairs: int = 0
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
        totals.merged_route_pairs += entry.merged_route_pairs
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
    inferred = tuple(
        sorted(
            store
            for store in totals.stores
            if store in capabilities and not capabilities[store].abandonment_signal
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
        merged_route_pairs=totals.merged_route_pairs,
        stores_without_structural=unreadable,
        confidence_downgraded=bool(unreadable),
        stores_with_inferred_abandonment=inferred,
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
    superset: dict[str, int] = {}
    read: list[SessionSignals] = []
    turns = 0
    tool_errors = 0

    for store in stores:
        for session in store_signals(store):
            read.append(session)
            counted_sessions.add((session.store, session.session_id))
            if session.project != NO_PROJECT:
                projects.add(session.project)
            if session.utterances_are_superset:
                superset[session.store] = superset.get(session.store, 0) + 1
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
        superset_utterance_sessions=superset,
        per_session=tuple(read),
    )


def scorable(skills: dict[str, SkillFriction]) -> dict[str, SkillFriction]:
    """The skills a score may be computed for: those actually fired.

    A skill never fired has no rate to compute — every rate divides by the number
    of firings — so it is left out rather than scored as frictionless.
    """
    return {skill: friction for skill, friction in skills.items() if friction.invocations}
