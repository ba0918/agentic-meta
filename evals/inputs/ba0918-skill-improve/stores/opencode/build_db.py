#!/usr/bin/env python3
"""Build the OpenCode store this scenario reads.

The OpenCode runtime keeps its session history in a single SQLite file rather
than in text records, so this input cannot be committed the way the other two
stores are: a binary blob in the repository is an input nobody can review in a
diff. The builder is committed instead, and the database is produced where the
run needs it.

Only the four tables the adapter queries are created — project, session,
message and part. The credential tables of a real OpenCode database have no
counterpart here, which is also why a scenario can never accidentally exercise
a read of one.

Usage: python3 build_db.py [output-path]   (default: opencode.db beside this file)
"""

import datetime
import json
import pathlib
import sqlite3
import sys

SCHEMA = """
CREATE TABLE project (
    id TEXT PRIMARY KEY,
    worktree TEXT NOT NULL,
    name TEXT,
    time_created INTEGER NOT NULL,
    time_updated INTEGER NOT NULL
);
CREATE TABLE session (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    slug TEXT NOT NULL,
    directory TEXT NOT NULL,
    title TEXT NOT NULL,
    version TEXT NOT NULL,
    time_created INTEGER NOT NULL,
    time_updated INTEGER NOT NULL
);
CREATE TABLE message (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    time_created INTEGER NOT NULL,
    time_updated INTEGER NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE part (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    time_created INTEGER NOT NULL,
    time_updated INTEGER NOT NULL,
    data TEXT NOT NULL
);
"""

BASE = datetime.datetime(2026, 8, 15, 11, 0, tzinfo=datetime.timezone.utc)
PROJECT_DIRECTORY = "/demo/project"


def at(minutes):
    """Milliseconds since the epoch — the unit this runtime stores times in."""
    return int((BASE + datetime.timedelta(minutes=minutes)).timestamp() * 1000)


# One session: the operator asks for a check in plain words, the runtime fires
# the skill through its own tool, the run fails, and the operator restates the
# request. The skill is visible on both routes a store of this kind supports.
MESSAGES = [
    ("m1", "user", 0, [{"type": "text", "text": "check the config before we ship"}]),
    ("m2", "assistant", 1, [
        {"type": "tool", "tool": "skill", "callID": "call-1",
         "state": {"status": "completed", "input": {"name": "beta-check"},
                   "title": "beta-check", "output": "3 problems found"}},
    ]),
    ("m3", "assistant", 2, [
        {"type": "tool", "tool": "bash", "callID": "call-2",
         "state": {"status": "error", "input": {"command": "beta-check --fix"},
                   "error": "beta-check: exited with 1"}},
    ]),
    ("m4", "user", 3, [{"type": "text", "text": "it failed again, look at the third one"}]),
    ("m5", "assistant", 4, [{"type": "text", "text": "the third problem is a missing key"}]),
]


def build(path):
    path = pathlib.Path(path)
    if path.exists():
        path.unlink()
    connection = sqlite3.connect(str(path))
    try:
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO project (id, worktree, name, time_created, time_updated)"
            " VALUES (?, ?, ?, ?, ?)",
            ("p1", PROJECT_DIRECTORY, "demo", at(0), at(4)),
        )
        connection.execute(
            "INSERT INTO session"
            " (id, project_id, slug, directory, title, version, time_created, time_updated)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("s1", "p1", "demo-session", PROJECT_DIRECTORY, "config check",
             "0.0.0-demo", at(0), at(4)),
        )
        for index, (message_id, role, offset, parts) in enumerate(MESSAGES):
            connection.execute(
                "INSERT INTO message (id, session_id, time_created, time_updated, data)"
                " VALUES (?, ?, ?, ?, ?)",
                (message_id, "s1", at(offset), at(offset),
                 json.dumps({"role": role, "time": {"created": at(offset)},
                             "agent": "demo", "model": "demo-model"})),
            )
            for part_index, part in enumerate(parts):
                connection.execute(
                    "INSERT INTO part"
                    " (id, message_id, session_id, time_created, time_updated, data)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (f"prt-{index}-{part_index}", message_id, "s1",
                     at(offset), at(offset), json.dumps(part)),
                )
        connection.commit()
    finally:
        connection.close()
    return path


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else str(
        pathlib.Path(__file__).resolve().parent / "opencode.db")
    written = build(target)
    print(f"wrote {written}")
