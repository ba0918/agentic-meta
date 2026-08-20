#!/usr/bin/env python3
"""The normalized events an adapter yields, and the contract every adapter meets.

Each agent runtime stores its session history its own way, so a reader per store
turns that storage into one shared vocabulary and the friction signals are computed
over the vocabulary alone. The vocabulary is deliberately poor: it holds the kinds
the signals actually consume and nothing else. A richer common event would have to
be produced by every adapter, so each store added later would drag all the existing
ones along with it.

A kind earns its place only where at least one store records the thing directly. A
store that does not is not asked to fake it: it declares the gap in its
capabilities, and the aggregation decides what to do about the asymmetry.

An adapter is only an ordered source of these events. It resolves paths, absorbs
time units, and filters by period, but it counts nothing and correlates nothing —
that is the aggregation layer's work, and keeping it there is what lets one
aggregation serve every store.
"""

import dataclasses
import datetime
import re
import typing

_OUTSIDE_KEY_ALPHABET = re.compile(r"[^A-Za-z0-9-]")

ROUTE_TEXT = "text"
ROUTE_STRUCTURAL = "structural"
DETECTION_ROUTES = (ROUTE_TEXT, ROUTE_STRUCTURAL)

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
TURN_ROLES = (ROLE_USER, ROLE_ASSISTANT)


def _reject_zoneless(at: datetime.datetime, subject: str) -> None:
    """Refuse a time that carries no zone, naming what the time belongs to."""
    if at.tzinfo is None or at.tzinfo.utcoffset(at) is None:
        raise ValueError(f"{subject} time must carry a zone")


@dataclasses.dataclass(frozen=True)
class UserText:
    """One utterance by the operator, as written, and when it was written.

    The utterance carries its own time because the prompt line this skill hands to
    the trigger evaluation fixes a timestamp to the utterance itself. Reading that
    timestamp off the preceding turn instead would make the pairing an implicit
    dependency on event order, so an adapter that reorders or omits a turn would
    quietly attach the wrong time to an utterance.

    The stores record time differently — one as integer milliseconds, the others as
    ISO 8601 strings — so a missing zone is refused here rather than left to each
    adapter to notice, which is the same reason Turn refuses one.
    """

    text: str
    at: datetime.datetime

    def __post_init__(self):
        _reject_zoneless(self.at, "utterance")


@dataclasses.dataclass(frozen=True)
class SkillInvocation:
    """One skill firing, together with the route that observed it.

    The route travels with the invocation because a store detecting only one of the
    two routes yields a systematically incomplete count, and the report has to say
    so rather than present the number as whole.
    """

    skill: str
    route: str

    def __post_init__(self):
        if self.route not in DETECTION_ROUTES:
            raise ValueError(f"unknown detection route: {self.route!r}")


@dataclasses.dataclass(frozen=True)
class ToolError:
    """One failed tool run."""

    tool: str


@dataclasses.dataclass(frozen=True)
class Turn:
    """One thing said by the operator or the agent — the unit the error rate divides by.

    A turn is speech, not every record wearing a speaker's role. Each runtime files
    its own working records under the same two roles it files speech under: a tool
    answer is written as a message in the operator's role, and a tool call or a
    block of the agent's private thinking as a message in the agent's. Counting
    those makes the denominator a property of the store rather than of the
    conversation — in one runtime's history, records holding nothing but a tool
    answer are 86% of everything wearing the operator's role, while another runtime
    keeps tool calls in a table of their own and so does not swell at all. Numbers
    divided by denominators that differ that much cannot be compared across stores,
    which is the whole reason the reading was split from the counting.

    Attachments, system records and generated titles are left out for the same
    reason, and rejecting any other role here keeps that out of an adapter's
    discretion. Which of a store's records count as speech is that store's
    adapter's business; that a turn is speech is settled here.
    """

    role: str
    at: datetime.datetime

    def __post_init__(self):
        if self.role not in TURN_ROLES:
            raise ValueError(f"not a turn role: {self.role!r}")
        _reject_zoneless(self.at, "turn")


@dataclasses.dataclass(frozen=True)
class SessionAbandoned:
    """The session was broken off rather than run to its end.

    One runtime writes this down itself; the other two keep no record of it at all,
    and for them the aggregation infers abandonment from how much of the session
    failed. The two are not the same measurement, so the store's own record is kept
    as its own kind of event: an inference can then be confined to the stores that
    need one, and a report can say which of the two a number came from.

    It carries nothing beyond the fact. Why a session was broken off is not
    something all three stores could answer, and nothing downstream divides by it.
    """


@dataclasses.dataclass(frozen=True)
class SessionIdentity:
    """Which session the events that follow it belong to, and where it ran.

    The project is the slug form of the working directory, because one runtime
    keeps only the slug and the original path cannot be recovered from it. Adapters
    holding a real path convert it, so all three stores meet on the same key.

    A session may declare its utterances a superset of what the operator actually
    said. That happens where the only record of an utterance a store kept also
    holds tool output and text a harness injected, with no field separating them.
    The declaration travels with the session rather than with each utterance
    because it is a property of how the whole session had to be read, and a
    consumer that hands utterance bodies onward needs to know it before it does.
    """

    session_id: str
    project: str
    utterances_are_superset: bool = False


NORMALIZED_EVENT_TYPES = (
    UserText,
    SkillInvocation,
    ToolError,
    Turn,
    SessionAbandoned,
    SessionIdentity,
)

Event = typing.Union[NORMALIZED_EVENT_TYPES]


def project_slug(path: str) -> str:
    """Convert a real working directory into the slug SessionIdentity carries.

    Every character outside the key alphabet — ASCII letters, digits, hyphen —
    becomes a hyphen, and nothing is stripped afterwards, so an absolute path keeps
    the leading hyphen its leading separator produced. Letter case is carried
    through unchanged. This reproduces the directory names one runtime actually
    writes, checked against the whole of that runtime's project directory.

    Dropping the leading hyphen, and converting only the separator, would both be
    survivable if the key were only ever compared loosely; the earlier form did
    exactly that and matched by substring. Substring matching makes one project a
    match for every project whose name extends it, so the key is compared whole and
    therefore has to be spelled exactly as the runtime spells it.

    The conversion lives here because the adapters holding a real path would
    otherwise each write it, and two spellings of it do not fail loudly — they make
    one project read as two.

    The conversion is one-way: a hyphen already inside a directory name becomes
    indistinguishable from a converted separator, so the original path cannot be
    recovered from the slug.
    """
    return _OUTSIDE_KEY_ALPHABET.sub("-", path)


@dataclasses.dataclass(frozen=True)
class Capabilities:
    """What a store can actually be read for, declared by its own adapter.

    A store with no structural route is not a store that happens to find fewer
    invocations; it is one that cannot find them at all along that route. The
    declaration exists so the aggregation can carry the gap into the report
    instead of an adapter filling it with an inference of its own.

    The record of abandonment is declared for the opposite reason. Here it is the
    stores without one that get an inference — drawn from how much of a session
    failed — so the declaration is what tells a reader which of two different
    measurements produced an abandonment count, and what stops the inference from
    being applied on top of a store that already said so itself.
    """

    text: bool
    structural: bool
    abandonment_signal: bool = False


class StoreUnreadable(Exception):
    """A store that is on this machine and whose contents could not be read.

    A store that is not here at all is read as an empty one, and the caller already
    reports the absence. A store that is here and cannot be read — a database in a
    shape this reader does not know, a schema that has moved on, a location holding
    something else entirely — is a third case, and reporting it as empty would let
    one store's trouble read as a clean measurement of no friction.

    It is raised rather than returned so that an adapter needs no way of saying it
    part way through a stream of events, and it is deliberately not one of the
    normalized events: those describe what happened in a session, and this
    describes the reading itself. The caller decides what to do with it; every one
    of them reports it and goes on to the next store.
    """


@typing.runtime_checkable
class SessionStore(typing.Protocol):
    """What an adapter offers: a name, its declared capabilities, and its events."""

    name: str
    capabilities: Capabilities

    def events(self) -> typing.Iterator[Event]:
        """Yield the session's normalized events in the order they occurred."""


def declared_capabilities(stores) -> dict[str, Capabilities]:
    """Collect each store's own declaration, keyed by store name.

    Two stores under one name are refused rather than the later quietly replacing
    the earlier: a report that lost a store's declaration would present a partial
    reading as a whole one, which is the failure this declaration exists to prevent.
    """
    collected: dict[str, Capabilities] = {}
    for store in stores:
        if store.name in collected:
            raise ValueError(f"duplicate store name: {store.name!r}")
        collected[store.name] = store.capabilities
    return collected
