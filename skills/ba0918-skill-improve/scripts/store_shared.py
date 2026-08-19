#!/usr/bin/env python3
"""What every store adapter needs before it can produce a single event.

Three runtimes keep their history three ways, but each adapter has to answer the
same four questions first: does this path stay inside what the caller allowed, was
this file touched inside the period, what time is this record, and does this
utterance fire a skill by slash command.

These live in one place rather than in each adapter for two different reasons. The
containment check is a security boundary, and a boundary check kept in three copies
drifts until one copy is weaker than the others. The other three are conversions,
and a conversion spelled two ways does not fail loudly — it makes one thing read as
two.

An adapter depends on this module; no adapter depends on another adapter.
"""

import datetime
import pathlib
import re
import typing

# /<plugin>:<skill-name> in an utterance, with no whitelist of plugin names.
SLASH_SKILL_RE = re.compile(r"/([a-z][a-z0-9-]*):([a-z][a-z0-9-]*)")


def resolve_within(path: pathlib.Path, root: pathlib.Path) -> pathlib.Path | None:
    """Resolve links and return the path only if it stays inside root.

    Containment is decided on the resolved paths by path components rather than by
    string prefix: a directory beside the root whose name merely extends it shares
    the prefix and would otherwise be read as part of the root.
    """
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
    """Drop files last written before the period, without opening any of them.

    A file untouched since before the period holds no record inside it, so its
    contents are never loaded. A file whose write time cannot be read is kept: the
    per-record filter downstream still applies, so keeping it costs a read, while
    dropping it would silently lose a session.
    """
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


def zoned_time(raw: typing.Any) -> datetime.datetime | None:
    """Read a written timestamp as a zoned time, or None if it is not one.

    A time written without a zone is read as UTC. The runtimes write zoned times,
    so this covers a malformed line rather than a real difference between them.
    """
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def slash_skill_in(text: str) -> str | None:
    """The skill a slash command in this text fires, stripped of its plugin prefix."""
    found = SLASH_SKILL_RE.search(text)
    return found.group(2) if found else None
