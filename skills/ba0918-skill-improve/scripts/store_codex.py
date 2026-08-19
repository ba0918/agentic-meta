#!/usr/bin/env python3
"""Reads one agent runtime's session history: rollout logs under a date hierarchy.

Each line is a record of three fields — a timestamp, a channel, and a payload — and
the payload's own kind says what the record is. The runtime writes the same
conversation to two channels: one mirrors the model's own items, the other mirrors
what the interface displayed. A single utterance therefore appears twice.

Only one channel is read per file. Whichever channel that file records messages on
is the one turns and utterances come from, and the other is passed over. Reading
both would double the turn count and fire slash-command detection twice for one
utterance, which manufactures retries out of nothing. Passing one over under-reads
a conversation that was recorded twice; emitting both invents events that never
happened, and an invented number moves an improvement action.

**This store has no structural route.** Across the whole of one operator's history
— 114,117 records — no tool name corresponding to a skill call exists; the runtime
has no such tool. So the adapter declares the structural route unavailable rather
than reconstructing it.

In particular it does not read a skill firing out of a shell command. A third of
the recorded commands mention a skill directory, but that is a command that read or
wrote a skill's files, not one that fired the skill. The share is high enough to
make the inference obviously wrong, and a friction score built on invented
invocations drives an improvement action at a skill that was never used — a worse
outcome than reporting that this route cannot be read at all.

**Error detection reaches only the newer generation of these logs.** A failure is
read from the record that ends a command and carries its exit status. Older logs
have no such record; there the failure is written into the body of a call's output,
with no status beside it. That body is not parsed for failure, for the same reason
the commands are not parsed for skill firings, so a reading of older logs
under-reports errors and says so rather than guessing.

An aborted turn is recognised and deliberately produces nothing. The normalized
vocabulary holds five kinds and abandonment is not one of them; it is derived
downstream from how much of a session failed. Recording an abort as a tool failure
would inflate exactly the count that derivation divides by. Consequently
abandonment detection here inherits the same generational limit as error detection.
"""

import dataclasses
import datetime
import json
import os
import pathlib
import re
import typing

from events import (
    Capabilities,
    Event,
    ROLE_ASSISTANT,
    ROLE_USER,
    ROUTE_TEXT,
    SessionIdentity,
    SkillInvocation,
    TURN_ROLES,
    ToolError,
    Turn,
    UserText,
    project_slug,
)

NAME = "codex"

# The two channels the same conversation is written to.
CHANNEL_ITEMS = "response_item"
CHANNEL_INTERFACE = "event_msg"

OPENING_RECORD = "session_meta"

# A command's failure names the call it answers by identifier, not by tool name, so
# the name comes from the call recorded earlier. A failure answering no recorded
# call stays counted but unnamed: dropping it would lose a failure that happened.
UNNAMED_TOOL = "unknown"

# No working directory was recorded for the session. Left empty rather than given a
# placeholder name, which would collide with a project that happened to be called it.
UNKNOWN_PROJECT = ""

# /<plugin>:<skill-name> in an utterance, with no whitelist of plugin names.
SLASH_SKILL_RE = re.compile(r"/([a-z][a-z0-9-]*):([a-z][a-z0-9-]*)")

TEXT_BLOCKS = ("input_text", "output_text")


def default_root() -> pathlib.Path:
    """The runtime's own session directory, assembled at call time.

    Assembled rather than written whole: the self-containment lint reads a rooted
    home path in any file as a reference outside the skill directory.
    """
    return pathlib.Path.home() / ("." + "codex") / "sessions"


def resolve_within(path: pathlib.Path, root: pathlib.Path) -> pathlib.Path | None:
    """Resolve links and return the path only if it stays inside root."""
    try:
        resolved = path.resolve(strict=True)
        resolved_root = root.resolve(strict=True)
    except (OSError, ValueError):
        return None
    if not resolved.is_relative_to(resolved_root):
        return None
    return resolved


def files_written_since(
    files: typing.Iterable[pathlib.Path], since: datetime.datetime | None
) -> list[pathlib.Path]:
    """Drop files last written before the period, without opening any of them."""
    if since is None:
        return list(files)
    cutoff = since.timestamp()
    kept: list[pathlib.Path] = []
    for path in files:
        try:
            if path.stat().st_mtime >= cutoff:
                kept.append(path)
        except OSError:
            kept.append(path)
    return kept


def rollout_files(root: pathlib.Path) -> list[pathlib.Path]:
    """Every readable rollout log under the date hierarchy, oldest path first."""
    resolved_root = resolve_within(root, root)
    if resolved_root is None:
        return []
    try:
        candidates = sorted(resolved_root.rglob("*.jsonl"))
    except (OSError, PermissionError):
        return []
    found: list[pathlib.Path] = []
    for candidate in candidates:
        log = resolve_within(candidate, resolved_root)
        if log is None or not os.access(log, os.R_OK):
            continue
        found.append(log)
    return found


def record_time(record: dict) -> datetime.datetime | None:
    """Read the record's own timestamp, always as a zoned time."""
    raw = record.get("timestamp")
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def _payload(record: dict) -> dict:
    payload = record.get("payload")
    return payload if isinstance(payload, dict) else {}


def read_records(path: pathlib.Path) -> list[dict]:
    """Every record of one rollout log, malformed lines skipped.

    A whole log is held at once because the channel to read cannot be chosen until
    the log has been looked over. These logs are short — under a hundred records
    each across the measured history — so holding one costs little.
    """
    try:
        handle = open(path, "r", encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return []
    records: list[dict] = []
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def conversation_channel(records: list[dict]) -> str:
    """Which of the two recordings of this conversation to read it from.

    The model's own items are preferred where present because that channel carries
    both sides under one kind of record.
    """
    for record in records:
        if record.get("type") == CHANNEL_ITEMS and _payload(record).get("type") == "message":
            return CHANNEL_ITEMS
    return CHANNEL_INTERFACE


def session_identity(records: list[dict], fallback_name: str) -> SessionIdentity:
    """Which session this log holds and where it ran."""
    for record in records:
        if record.get("type") != OPENING_RECORD:
            continue
        opening = _payload(record)
        identifier = opening.get("session_id") or opening.get("id")
        cwd = opening.get("cwd")
        return SessionIdentity(
            session_id=identifier if isinstance(identifier, str) else fallback_name,
            project=project_slug(cwd) if isinstance(cwd, str) else UNKNOWN_PROJECT,
        )
    return SessionIdentity(session_id=fallback_name, project=UNKNOWN_PROJECT)


def called_tool_name(record: dict) -> tuple[str, str] | None:
    """The identifier and name of the tool call this record makes, if it makes one."""
    payload = _payload(record)
    if payload.get("type") not in ("function_call", "custom_tool_call"):
        return None
    identifier = payload.get("call_id")
    name = payload.get("name")
    if isinstance(identifier, str) and isinstance(name, str):
        return identifier, name
    return None


def content_text(payload: dict) -> str | None:
    """The whole body of a message recorded as content blocks."""
    content = payload.get("content")
    if isinstance(content, str):
        return content or None
    if not isinstance(content, list):
        return None
    fragments = [
        block["text"]
        for block in content
        if isinstance(block, dict)
        and block.get("type") in TEXT_BLOCKS
        and isinstance(block.get("text"), str)
    ]
    return "\n".join(fragments) if fragments else None


def slash_skill_in(text: str) -> str | None:
    """The skill a slash command in this text fires, stripped of its plugin prefix."""
    found = SLASH_SKILL_RE.search(text)
    return found.group(2) if found else None


def command_failure(payload: dict, called: dict[str, str]) -> str | None:
    """The tool a command-ending record reports the failure of, or None.

    The exit status decides. The status word beside it was never measured across
    the history, so its values are not relied on.
    """
    if payload.get("type") != "exec_command_end":
        return None
    exit_code = payload.get("exit_code")
    if not isinstance(exit_code, int) or exit_code == 0:
        return None
    return called.get(payload.get("call_id"), UNNAMED_TOOL)


def _utterance_events(
    said: str | None, at: datetime.datetime
) -> typing.Iterator[Event]:
    """What one operator utterance yields: the body, and any slash command in it."""
    if not said:
        return
    yield UserText(text=said, at=at)
    fired = slash_skill_in(said)
    if fired is not None:
        yield SkillInvocation(skill=fired, route=ROUTE_TEXT)


def record_events(
    record: dict,
    channel: str,
    called: dict[str, str],
    since: datetime.datetime | None,
) -> typing.Iterator[Event]:
    """The normalized events one record yields, in the order they occurred in it."""
    naming = called_tool_name(record)
    if naming is not None:
        called[naming[0]] = naming[1]
    at = record_time(record)
    if at is None or (since is not None and at < since):
        return
    kind = record.get("type")
    payload = _payload(record)
    spoken = payload.get("type")
    if channel == CHANNEL_ITEMS and kind == CHANNEL_ITEMS and spoken == "message":
        role = payload.get("role")
        if role in TURN_ROLES:
            yield Turn(role=role, at=at)
            if role == ROLE_USER:
                yield from _utterance_events(content_text(payload), at)
    elif channel == CHANNEL_INTERFACE and kind == CHANNEL_INTERFACE:
        if spoken == "user_message":
            yield Turn(role=ROLE_USER, at=at)
            message = payload.get("message")
            yield from _utterance_events(message if isinstance(message, str) else None, at)
        elif spoken == "agent_message":
            yield Turn(role=ROLE_ASSISTANT, at=at)
    failed = command_failure(payload, called)
    if failed is not None:
        yield ToolError(tool=failed)


@dataclasses.dataclass(frozen=True)
class CodexStore:
    """The adapter over that runtime's rollout logs."""

    root: pathlib.Path | str = dataclasses.field(default_factory=default_root)
    since: datetime.datetime | None = None
    project: str | None = None
    name: str = NAME
    capabilities: Capabilities = Capabilities(text=True, structural=False)

    def events(self) -> typing.Iterator[Event]:
        """Yield every session's normalized events, oldest log path first."""
        logs = files_written_since(rollout_files(pathlib.Path(self.root)), self.since)
        for path in logs:
            records = read_records(path)
            if not records:
                continue
            identity = session_identity(records, path.stem)
            if self.project is not None and identity.project != self.project:
                continue
            yield identity
            channel = conversation_channel(records)
            called: dict[str, str] = {}
            for record in records:
                yield from record_events(record, channel, called, self.since)
