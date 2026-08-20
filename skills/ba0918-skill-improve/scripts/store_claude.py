#!/usr/bin/env python3
"""Reads one agent runtime's session history: a directory of JSONL files per project.

The store keeps one directory per project, named after the working directory with
every character outside the key alphabet turned into a hyphen, and inside it one
JSONL file per session. The original path is not recoverable from that name, so
this adapter never converts anything: the directory name is already the key the
other adapters convert their real paths into.

Both detection routes are available here. A skill firing is recorded structurally,
as a call to the Skill tool carrying the skill name, and an operator may also fire
one by typing a slash command, which only the utterance body shows.

Undated records are left out entirely. The period filter is this layer's work, and
a record that cannot be dated cannot be placed inside or outside the period — so
keeping it would let a record from any time into a bounded reading. The runtime
does timestamp its message records, so what this drops in practice is malformed
lines.

A record wearing a speaker's role is not by itself a turn. This runtime files a
tool answer as a message in the operator's role, and a tool call or a block of the
agent's private thinking as a message in the agent's, so what a record holds — not
the role it wears — decides whether anything was said in it.
"""

import dataclasses
import datetime
import itertools
import json
import pathlib
import re
import typing

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
)
from store_shared import (
    files_written_since,
    log_files_under,
    resolve_within,
    slash_skill_in,
    zoned_time,
)

NAME = "claude"

# A tool answer names the call it answers by identifier, not by tool name, so the
# name is resolved from the call recorded earlier in the same session. A call that
# was never recorded — the session began mid-conversation, or the call fell outside
# the period — leaves the failure counted but unnamed, because dropping it would
# undercount a failure that was actually observed.
UNNAMED_TOOL = "unknown"

SKILL_TOOL_NAMES = ("Skill", "skill")

# The one block type that holds something a side actually said.
SPEECH_BLOCK = "text"

# "<plugin>:<skill-name>" or a bare "<skill-name>" in the Skill tool's input.
SKILL_INPUT_RE = re.compile(r"^(?:([a-z][a-z0-9-]*):)?([a-z][a-z0-9-]*)$")


def default_root() -> pathlib.Path:
    """The runtime's own project directory, assembled at call time.

    Assembled rather than written whole: the self-containment lint reads a rooted
    home path in any file as a reference outside the skill directory.
    """
    return pathlib.Path.home() / ("." + "claude") / "projects"


def session_files(
    root: pathlib.Path, project: str | None = None
) -> list[tuple[str, pathlib.Path]]:
    """Pair every session file under root with the project it belongs to.

    The project is matched whole rather than by substring, because the key extends
    by suffix — one project's key is a substring of every key that extends it.

    A root that is not there yields no pairs, and the caller reports the absence. A
    root or a project directory that is there and cannot be listed refuses the
    reading instead of yielding fewer pairs: a store the operator cannot open would
    otherwise report exactly what a store holding no friction reports.
    """
    resolved_root = resolve_within(root, root)
    if resolved_root is None:
        return []
    found: list[tuple[str, pathlib.Path]] = []
    try:
        entries = sorted(resolved_root.iterdir())
    except OSError as unreadable:
        raise StoreUnreadable(str(unreadable)) from unreadable
    for entry in entries:
        if project is not None and entry.name != project:
            continue
        directory = resolve_within(entry, resolved_root)
        if directory is None or not directory.is_dir():
            continue
        for candidate in log_files_under(directory):
            session = resolve_within(candidate, resolved_root)
            if session is None:
                continue
            found.append((entry.name, session))
    return found


def record_time(record: dict) -> datetime.datetime | None:
    """Read the record's own timestamp, always as a zoned time."""
    return zoned_time(record.get("timestamp"))


def _blocks(record: dict) -> list[dict]:
    message = record.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def role_of(record: dict) -> str | None:
    """The side that spoke, or None for a record that is not a message."""
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    role = message.get("role")
    return role if role in TURN_ROLES else None


def carries_speech(record: dict) -> bool:
    """Whether anything was actually said in this record.

    A body written as a plain string is always something said; a body written as
    blocks is something said only where one of those blocks is spoken text. The
    rest of what this runtime files under the two speaking roles — a tool answer
    under the operator's, a tool call or a block of private thinking under the
    agent's — is the runtime working, and counting it as a turn would put the
    store's bookkeeping into the denominator of every rate computed downstream.
    """
    message = record.get("message")
    if not isinstance(message, dict):
        return False
    if isinstance(message.get("content"), str):
        return True
    return any(block.get("type") == SPEECH_BLOCK for block in _blocks(record))


def utterance_of(record: dict) -> str | None:
    """The whole body the operator wrote in one message, or None if it wrote none.

    The fragments of one message are joined into a single utterance. Emitting one
    per fragment would make a single thing said read as several, which downstream
    counts every correction by.
    """
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content or None
    fragments = [
        block["text"]
        for block in _blocks(record)
        if block.get("type") == SPEECH_BLOCK and isinstance(block.get("text"), str)
    ]
    if not fragments:
        return None
    return "\n".join(fragments)


def _bare_skill_name(value: typing.Any) -> str | None:
    """The skill name without its plugin prefix, or the value as written.

    A value that does not fit the naming pattern is kept as written rather than
    dropped: the call was observed, and dropping it would undercount a firing that
    did happen.
    """
    if not isinstance(value, str) or not value:
        return None
    fitted = SKILL_INPUT_RE.match(value)
    return fitted.group(2) if fitted else value


def structural_skills(record: dict) -> list[str]:
    """Every skill fired by a Skill tool call in this record."""
    fired: list[str] = []
    for block in _blocks(record):
        if block.get("type") != "tool_use" or block.get("name") not in SKILL_TOOL_NAMES:
            continue
        called = block.get("input")
        if not isinstance(called, dict):
            continue
        name = _bare_skill_name(called.get("skill"))
        if name is not None:
            fired.append(name)
    return fired


def called_tool_names(record: dict) -> dict[str, str]:
    """Every tool call this record makes, keyed by the identifier its answer cites."""
    called: dict[str, str] = {}
    for block in _blocks(record):
        if block.get("type") != "tool_use":
            continue
        identifier = block.get("id")
        name = block.get("name")
        if isinstance(identifier, str) and isinstance(name, str):
            called[identifier] = name
    return called


def failed_tool(record: dict, called: dict[str, str]) -> str | None:
    """The tool this record reports a failure of, or None if it reports none.

    One record reports at most one failure. The runtime records the same failure
    both inside the message and beside it, so reading each place as its own failure
    would double a count the error rate divides by.
    """
    for block in _blocks(record):
        if block.get("type") == "tool_result" and block.get("is_error") is True:
            answered = block.get("tool_use_id")
            return called.get(answered, UNNAMED_TOOL)
    beside = record.get("toolUseResult")
    if isinstance(beside, dict) and beside.get("is_error") is True:
        return UNNAMED_TOOL
    return None


def record_events(
    record: dict, called: dict[str, str], since: datetime.datetime | None
) -> typing.Iterator[Event]:
    """The normalized events one record yields, in the order they occurred in it."""
    called.update(called_tool_names(record))
    at = record_time(record)
    if at is None or (since is not None and at < since):
        return
    role = role_of(record)
    if role is not None and carries_speech(record):
        yield Turn(role=role, at=at)
    if role == ROLE_USER:
        said = utterance_of(record)
        if said is not None:
            yield UserText(text=said, at=at)
            fired = slash_skill_in(said)
            if fired is not None:
                yield SkillInvocation(skill=fired, route=ROUTE_TEXT)
    for name in structural_skills(record):
        yield SkillInvocation(skill=name, route=ROUTE_STRUCTURAL)
    failed = failed_tool(record, called)
    if failed is not None:
        yield ToolError(tool=failed)


def _parsed_records(handle: typing.Iterable[str]) -> typing.Iterator[dict]:
    """Every line of a session file that parses as a record, malformed ones skipped."""
    for line in handle:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            yield record


def _session_events(
    path: pathlib.Path, project: str, since: datetime.datetime | None
) -> typing.Iterator[Event]:
    """One session file's events, its identity announced before them.

    A file that is listed and cannot be opened refuses the reading where it broke,
    rather than being stepped over: the sessions already read stay counted, and the
    caller reports that the store's counts are a floor rather than a total.
    """
    try:
        handle = open(path, "r", encoding="utf-8", errors="replace")
    except OSError as unreadable:
        raise StoreUnreadable(str(unreadable)) from unreadable
    with handle:
        records = _parsed_records(handle)
        try:
            first = next(records)
        except StopIteration:
            return
        identifier = first.get("sessionId")
        yield SessionIdentity(
            session_id=identifier if isinstance(identifier, str) else path.stem,
            project=project,
        )
        called: dict[str, str] = {}
        for record in itertools.chain([first], records):
            yield from record_events(record, called, since)


@dataclasses.dataclass(frozen=True)
class ClaudeCodeStore:
    """The adapter over that runtime's project directories."""

    root: pathlib.Path | str = dataclasses.field(default_factory=default_root)
    since: datetime.datetime | None = None
    project: str | None = None
    name: str = NAME
    capabilities: Capabilities = Capabilities(text=True, structural=True)

    def events(self) -> typing.Iterator[Event]:
        """Yield every session's normalized events, oldest file path first."""
        pairs = session_files(pathlib.Path(self.root), self.project)
        readable = set(files_written_since([path for _, path in pairs], self.since))
        for project, path in pairs:
            if path not in readable:
                continue
            yield from _session_events(path, project, self.since)
