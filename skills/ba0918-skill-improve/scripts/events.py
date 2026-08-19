#!/usr/bin/env python3
"""The normalized events an adapter yields, and the contract every adapter meets.

Each agent runtime stores its session history its own way, so a reader per store
turns that storage into one shared vocabulary and the friction signals are computed
over the vocabulary alone. The vocabulary is deliberately poor: it holds the five
kinds the signals actually consume and nothing else. A richer common event would
have to be produced by every adapter, so each store added later would drag all the
existing ones along with it.

An adapter is only an ordered source of these events. It resolves paths, absorbs
time units, and filters by period, but it counts nothing and correlates nothing —
that is the aggregation layer's work, and keeping it there is what lets one
aggregation serve every store.
"""

import dataclasses
import datetime
import typing

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
    """One message by the operator or the agent — the unit the error rate divides by.

    Only these two roles are turns. Attachments, system records, and generated
    titles are stored as messages by some runtimes and not by others, so counting
    them would make the denominator a property of the store rather than of the
    session. Rejecting any other role here is what keeps that out of an adapter's
    discretion.
    """

    role: str
    at: datetime.datetime

    def __post_init__(self):
        if self.role not in TURN_ROLES:
            raise ValueError(f"not a turn role: {self.role!r}")
        _reject_zoneless(self.at, "turn")


@dataclasses.dataclass(frozen=True)
class SessionIdentity:
    """Which session the events that follow it belong to, and where it ran.

    The project is the slug form of the working directory, because one runtime
    keeps only the slug and the original path cannot be recovered from it. Adapters
    holding a real path convert it, so all three stores meet on the same key.
    """

    session_id: str
    project: str


NORMALIZED_EVENT_TYPES = (UserText, SkillInvocation, ToolError, Turn, SessionIdentity)

Event = typing.Union[NORMALIZED_EVENT_TYPES]


def project_slug(path: str) -> str:
    """Convert a real working directory into the slug SessionIdentity carries.

    Separators become hyphens and a leading hyphen is dropped. The conversion lives
    here because the adapters holding a real path would otherwise each write it, and
    two spellings of it do not fail loudly — they make one project read as two.

    The conversion is one-way: a hyphen already inside a directory name becomes
    indistinguishable from a converted separator, so the original path cannot be
    recovered from the slug.
    """
    return path.replace("/", "-").lstrip("-")


@dataclasses.dataclass(frozen=True)
class Capabilities:
    """Which of the two detection routes a store can actually be read along.

    A store with no structural route is not a store that happens to find fewer
    invocations; it is one that cannot find them at all along that route. The
    declaration exists so the aggregation can carry the gap into the report
    instead of an adapter filling it with an inference of its own.
    """

    text: bool
    structural: bool


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
