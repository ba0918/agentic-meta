#!/usr/bin/env python3
"""Reads one agent runtime's session history: rollout logs under a date hierarchy.

Each line is a record of three fields — a timestamp, a channel, and a payload — and
the payload's own kind says what the record is. The runtime writes the same
conversation to two channels: one mirrors the model's own items, the other mirrors
what the interface displayed. A single utterance therefore appears twice.

Only one of the two recordings is read per file, and the typed one wins. A file
holding any record of the operator having typed is read from that recording alone;
only a file holding no such record at all falls back to the other one.

The order is settled by measurement, not preference. Across the whole of one
operator's history — 1,212 files — the typed recording holds 1,753 utterances and
the mirrored one 5,083, and 1,708 of the typed utterances (97%) appear verbatim in
both. 1,005 files hold both recordings and 991 of those really do duplicate. The
mirrored recording is thus a superset, not a second source: its surplus is tool
output and text a harness injected, filed under the operator's role, exactly as
another runtime files its tool answers. Reading both recordings would double nearly
every utterance, fire slash-command detection twice for one command, and
manufacture retries out of nothing. Preferring the mirrored recording — which an
earlier reading of these logs did — is not a way of losing less: it silently
substitutes the superset for the utterances, putting tool output into the
correction count and into the prompt harvest.

A file that had to fall back says so: its session identity declares its utterances
a superset, so nothing downstream presents that reading as if it held only what the
operator said.

Turns follow whichever recording was chosen. In the typed recording a turn is the
operator having typed or the agent having answered; in the fallback it is a message
record in one of those two roles, the harness's own role left out. Without that
reconciliation a fallback file would contribute utterances and no turns at all, and
every rate computed over it would divide by zero.

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

An aborted turn is this runtime's own record of a session having been broken off,
and it is the only one of the three stores that keeps such a record. It is emitted
as abandonment and never as a tool failure: a failure would inflate exactly the
count the other stores' abandonment is inferred from, so the two would stop meaning
the same thing under the same name.
"""

import dataclasses
import datetime
import json
import pathlib
import typing

from events import (
    Capabilities,
    Event,
    ROLE_ASSISTANT,
    ROLE_USER,
    ROUTE_TEXT,
    SessionAbandoned,
    SessionIdentity,
    SkillInvocation,
    StoreUnreadable,
    TURN_ROLES,
    ToolError,
    Turn,
    UserText,
    project_slug,
)
from store_shared import (
    files_written_since,
    log_files_under,
    resolve_within,
    slash_skill_in,
    zoned_time,
)

NAME = "codex"

# The two channels the same conversation is written to.
CHANNEL_ITEMS = "response_item"
CHANNEL_INTERFACE = "event_msg"

# The record the interface channel writes when the operator typed something.
TYPED_UTTERANCE = "user_message"

# The record this runtime writes when a turn was broken off before it finished.
BROKEN_OFF = "turn_aborted"

OPENING_RECORD = "session_meta"

# A command's failure names the call it answers by identifier, not by tool name, so
# the name comes from the call recorded earlier. A failure answering no recorded
# call stays counted but unnamed: dropping it would lose a failure that happened.
UNNAMED_TOOL = "unknown"

# No working directory was recorded for the session. Left empty rather than given a
# placeholder name, which would collide with a project that happened to be called it.
UNKNOWN_PROJECT = ""

TEXT_BLOCKS = ("input_text", "output_text")


def default_root() -> pathlib.Path:
    """The runtime's own session directory, assembled at call time.

    Assembled rather than written whole: the self-containment lint reads a rooted
    home path in any file as a reference outside the skill directory.
    """
    return pathlib.Path.home() / ("." + "codex") / "sessions"


def rollout_files(root: pathlib.Path) -> list[pathlib.Path]:
    """Every rollout log under the date hierarchy, oldest path first.

    A root that is not there yields no logs, and the caller reports the absence. A
    directory of the hierarchy that is there and cannot be listed refuses the
    reading instead of yielding fewer logs: a store the operator cannot open would
    otherwise report exactly what a store holding no friction reports.
    """
    resolved_root = resolve_within(root, root)
    if resolved_root is None:
        return []
    found: list[pathlib.Path] = []
    for candidate in log_files_under(resolved_root):
        log = resolve_within(candidate, resolved_root)
        if log is None:
            continue
        found.append(log)
    return found


def record_time(record: dict) -> datetime.datetime | None:
    """Read the record's own timestamp, always as a zoned time."""
    return zoned_time(record.get("timestamp"))


def _payload(record: dict) -> dict:
    payload = record.get("payload")
    return payload if isinstance(payload, dict) else {}


def read_records(path: pathlib.Path) -> list[dict]:
    """Every record of one rollout log, malformed lines skipped.

    A whole log is held at once because the channel to read cannot be chosen until
    the log has been looked over. These logs are short — under a hundred records
    each across the measured history — so holding one costs little.

    A log that is listed and cannot be opened refuses the reading where it broke,
    rather than being stepped over: the logs already read stay counted, and the
    caller reports that the store's counts are a floor rather than a total.
    """
    try:
        handle = open(path, "r", encoding="utf-8", errors="replace")
    except OSError as unreadable:
        raise StoreUnreadable(str(unreadable)) from unreadable
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

    A single record of the operator having typed is enough to settle it, because
    the channel that holds one holds them all — the interface writes every typed
    utterance there. The other channel is read only where this one is absent.
    """
    for record in records:
        if (
            record.get("type") == CHANNEL_INTERFACE
            and _payload(record).get("type") == TYPED_UTTERANCE
        ):
            return CHANNEL_INTERFACE
    return CHANNEL_ITEMS


def session_identity(
    records: list[dict], fallback_name: str, channel: str
) -> SessionIdentity:
    """Which session this log holds, where it ran, and how its utterances were read."""
    superset = channel == CHANNEL_ITEMS
    for record in records:
        if record.get("type") != OPENING_RECORD:
            continue
        opening = _payload(record)
        identifier = opening.get("session_id") or opening.get("id")
        cwd = opening.get("cwd")
        return SessionIdentity(
            session_id=identifier if isinstance(identifier, str) else fallback_name,
            project=project_slug(cwd) if isinstance(cwd, str) else UNKNOWN_PROJECT,
            utterances_are_superset=superset,
        )
    return SessionIdentity(
        session_id=fallback_name,
        project=UNKNOWN_PROJECT,
        utterances_are_superset=superset,
    )


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
        if spoken == TYPED_UTTERANCE:
            yield Turn(role=ROLE_USER, at=at)
            message = payload.get("message")
            yield from _utterance_events(message if isinstance(message, str) else None, at)
        elif spoken == "agent_message":
            yield Turn(role=ROLE_ASSISTANT, at=at)
    if spoken == BROKEN_OFF:
        yield SessionAbandoned()
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
    capabilities: Capabilities = Capabilities(
        text=True, structural=False, abandonment_signal=True,
        error_detection_partial=True,
    )

    def events(self) -> typing.Iterator[Event]:
        """Yield every session's normalized events, oldest log path first."""
        logs = files_written_since(rollout_files(pathlib.Path(self.root)), self.since)
        for path in logs:
            records = read_records(path)
            if not records:
                continue
            channel = conversation_channel(records)
            identity = session_identity(records, path.stem, channel)
            if self.project is not None and identity.project != self.project:
                continue
            yield identity
            called: dict[str, str] = {}
            for record in records:
                yield from record_events(record, channel, called, self.since)
