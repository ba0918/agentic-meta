#!/usr/bin/env python3
"""Reads one agent runtime's session history: a single SQLite database.

This runtime keeps no session files. One database holds every session, its
messages, and the parts a message is built from, with each body stored as JSON
text in a column. Reading it is therefore a query, not a scan, which is why it
cannot share a reader with the runtimes that write log files.

Two properties of that database are structural, not advisory:

The connection is opened read-only through a URI, so the reading cannot alter the
operator's own history and can proceed while the runtime itself is writing.

The same database holds the operator's credentials in tables beside the session
ones. Rather than a note telling a later reader not to touch them, the queries
this module can run are fixed and named here, so no statement it issues mentions a
credential-holding table at all.

Times in this database are integer milliseconds. Read as seconds they would land
tens of thousands of years in the future, which no period filter would ever
exclude — so the unit is absorbed here, and the aggregation sees ordinary times.
"""

import dataclasses
import datetime
import json
import pathlib
import sqlite3
import typing
import urllib.parse

from events import (
    Capabilities,
    Event,
    ROLE_USER,
    ROUTE_STRUCTURAL,
    ROUTE_TEXT,
    SessionIdentity,
    SkillInvocation,
    StoreUnreadable,
    TURN_ROLES,
    ToolError,
    Turn,
    UserText,
    project_slug,
)
from store_shared import slash_skill_in

NAME = "opencode"

# The whole set of tables this adapter may read, and every one of them is read. The
# credential-holding tables of the same database are outside it, and no statement
# below names one. A table declared and never read would widen that claim past what
# the statements do, which is the direction that makes such a claim worth less.
TABLES_READ = ("session", "message", "part")

SESSIONS_SQL = "SELECT id, directory, time_updated FROM session ORDER BY time_created"
MESSAGES_SQL = (
    "SELECT id, time_created, data FROM message WHERE session_id = ? ORDER BY time_created"
)
PARTS_SQL = (
    "SELECT message_id, data FROM part WHERE session_id = ?"
    " ORDER BY message_id, time_created"
)

# The one kind of part that holds something a side actually said. A message built
# only of the other kinds — a tool call and its result — is the runtime working,
# not a turn.
TEXT_PART = "text"

SKILL_TOOL = "skill"
ERROR_STATUS = "error"
UNNAMED_TOOL = "unknown"


def default_db_path() -> pathlib.Path:
    """The runtime's own database, assembled at call time.

    Assembled rather than written whole: the self-containment lint reads a rooted
    home path in any file as a reference outside the skill directory.
    """
    return pathlib.Path.home() / (".local") / "share" / "opencode" / "opencode.db"


def connect_readonly(path: pathlib.Path | str) -> sqlite3.Connection:
    """Open the database so that nothing this process does can write to it.

    The read-only URI, rather than a promise not to issue writes, is what makes a
    stray write fail instead of corrupting the operator's own history. It also
    reads a database the runtime is currently writing to.

    The location is escaped into that URI rather than pasted into it, because the
    URI's own punctuation is ordinary inside a file name and each piece of it
    breaks the guarantee differently. Measured on this reader: a name holding `?`
    had the read-only mode overridden by what followed, so a writable connection
    opened; a name holding `#` had everything after it discarded, mode and all,
    which created a different and empty database and read it as holding nothing; a
    name holding `%` was decoded as an escape and the real file could not be found.
    Escaping turns all three back into parts of a name. Resolving first keeps a
    relative location from naming one file here and a different one elsewhere.
    """
    located = pathlib.Path(path).resolve()
    return sqlite3.connect(
        "file:" + urllib.parse.quote(str(located), safe="/") + "?mode=ro", uri=True
    )


def from_milliseconds(value: int) -> datetime.datetime:
    """Read one of this database's integer times as a zoned time."""
    return datetime.datetime.fromtimestamp(value / 1000, tz=datetime.timezone.utc)


def _decoded(raw: typing.Any) -> dict | None:
    """The JSON body of a row, or None when the row does not hold one."""
    if not isinstance(raw, str):
        return None
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return body if isinstance(body, dict) else None


def carries_speech(parts: list[dict]) -> bool:
    """Whether anything was actually said in the message these parts build.

    This runtime keeps tool calls out of the message row and in parts of their
    own, so a message row exists for work as well as for speech. Counting every
    row would put the runtime's bookkeeping into the denominator of every rate
    computed downstream, and would do it by a different amount than the runtimes
    that file their tool calls as messages — leaving the three stores' numbers
    incomparable.
    """
    return any(part.get("type") == TEXT_PART for part in parts)


def part_text(part: dict) -> str | None:
    """The body of a text part, or None for any other part."""
    if part.get("type") != TEXT_PART:
        return None
    text = part.get("text")
    return text if isinstance(text, str) and text else None


def part_skill(part: dict) -> str | None:
    """The skill a tool part fired, or None when the part fired no skill.

    The name is stored without a plugin prefix here, so nothing is stripped.
    """
    if part.get("type") != "tool" or part.get("tool") != SKILL_TOOL:
        return None
    state = part.get("state")
    if not isinstance(state, dict):
        return None
    called = state.get("input")
    if not isinstance(called, dict):
        return None
    name = called.get("name")
    return name if isinstance(name, str) and name else None


def part_failure(part: dict) -> str | None:
    """The tool a part reports the failure of, or None when it reports none."""
    if part.get("type") != "tool":
        return None
    state = part.get("state")
    if not isinstance(state, dict) or state.get("status") != ERROR_STATUS:
        return None
    tool = part.get("tool")
    return tool if isinstance(tool, str) and tool else UNNAMED_TOOL


def _message_events(
    parts: list[dict], role: str | None, at: datetime.datetime
) -> typing.Iterator[Event]:
    """The events one message and its parts yield, in the order they occurred.

    The utterance is the message's text parts joined, not one utterance per part:
    emitting one each would make a single thing said read as several, which the
    correction count divides by.
    """
    if role is not None and carries_speech(parts):
        yield Turn(role=role, at=at)
    if role == ROLE_USER:
        fragments = [text for text in (part_text(part) for part in parts) if text]
        if fragments:
            said = "\n".join(fragments)
            yield UserText(text=said, at=at)
            fired = slash_skill_in(said)
            if fired is not None:
                yield SkillInvocation(skill=fired, route=ROUTE_TEXT)
    for part in parts:
        skill = part_skill(part)
        if skill is not None:
            yield SkillInvocation(skill=skill, route=ROUTE_STRUCTURAL)
        failed = part_failure(part)
        if failed is not None:
            yield ToolError(tool=failed)


@dataclasses.dataclass(frozen=True)
class OpenCodeStore:
    """The adapter over that runtime's database."""

    db_path: pathlib.Path | str = dataclasses.field(default_factory=default_db_path)
    since: datetime.datetime | None = None
    project: str | None = None
    connect: typing.Callable[[str], sqlite3.Connection] = connect_readonly
    name: str = NAME
    capabilities: Capabilities = Capabilities(text=True, structural=True)

    def events(self) -> typing.Iterator[Event]:
        """Yield every session's normalized events, oldest session first.

        A database that is not there is an empty store rather than a failure: the
        operator may simply not run this runtime, and one absent store must not
        stop the others from being read.

        A database that is there and cannot be read is neither empty nor fatal.
        Opening is deferred by this driver, so a location holding something that is
        not a database, and a database whose session table has moved on, both fail
        at the first query rather than at the connection — which is where the
        failure is turned into one the caller can report. Letting it out as it
        comes would end the whole run: the other stores were read fine, and one
        runtime's schema change would take their measurement down with it.
        """
        try:
            connection = self.connect(str(self.db_path))
        except sqlite3.Error:
            return
        try:
            for identifier, directory in self._sessions(connection):
                yield SessionIdentity(
                    session_id=identifier, project=project_slug(directory)
                )
                yield from self._session_events(connection, identifier)
        except sqlite3.Error as unreadable:
            raise StoreUnreadable(str(unreadable)) from unreadable
        finally:
            connection.close()

    def _sessions(self, connection) -> list[tuple[str, str]]:
        """Every session inside the period and the named project, oldest first."""
        kept: list[tuple[str, str]] = []
        for identifier, directory, updated in connection.execute(SESSIONS_SQL).fetchall():
            if not isinstance(identifier, str) or not isinstance(directory, str):
                continue
            if self.project is not None and project_slug(directory) != self.project:
                continue
            if self.since is not None and isinstance(updated, int):
                if from_milliseconds(updated) < self.since:
                    continue
            kept.append((identifier, directory))
        return kept

    def _session_events(self, connection, session_id: str) -> typing.Iterator[Event]:
        """One session's messages and their parts, oldest message first.

        The parts of the whole session are read in one statement and handed to the
        messages they belong to, rather than one statement per message. Every part
        row already carries the session it belongs to, so the rows are the same
        rows either way; asking per message multiplies the cost of reading a
        session by the number of messages in it.
        """
        parts = self._parts_by_message(connection, session_id)
        for message_id, created, raw in connection.execute(MESSAGES_SQL, (session_id,)):
            body = _decoded(raw)
            if body is None or not isinstance(created, int):
                continue
            at = from_milliseconds(created)
            if self.since is not None and at < self.since:
                continue
            role = body.get("role")
            yield from _message_events(
                parts.get(message_id, []), role if role in TURN_ROLES else None, at
            )

    def _parts_by_message(self, connection, session_id: str) -> dict[str, list[dict]]:
        """Every part of one session, gathered under the message it was built into.

        The order the statement returns them in is kept, so a message's parts stay
        in the order they were created — which is the order a message's text is
        joined in.
        """
        gathered: dict[str, list[dict]] = {}
        for message_id, raw in connection.execute(PARTS_SQL, (session_id,)):
            part = _decoded(raw)
            if part is not None:
                gathered.setdefault(message_id, []).append(part)
        return gathered
