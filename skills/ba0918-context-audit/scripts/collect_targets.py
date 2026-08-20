#!/usr/bin/env python3
"""ba0918-context-audit: audit-target discovery and classification.

Memory auditing is scoped to the project the audit runs in. The working-directory
to project-key conversion mirrors the runtime's own, and the directory it resolves
to is reverse-verified to sit directly inside the runtime's project store, so a
symlink escape or a key collision is skipped unread rather than followed. The home
that store is looked up under is a parameter, never derived inside the resolution.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# Instruction-bearing files, named one by one. A positive allowlist rather than an
# exclusion list: archival and temporary areas stay out by construction, so a new one
# cannot leak in by being forgotten. Nested directories are out of scope for now.
REPO_FILE_TARGETS: list[tuple[str, str]] = [
    ("CLAUDE.md", "claude_md"),
    ("AGENTS.md", "agents_md"),
    ("PROJECT.md", "project_md"),
]
REPO_DIR_TARGETS: list[tuple[str, str]] = [
    (".claude/rules", "rules"),
    ("rules", "rules"),
]

_SLUG_RE = re.compile(r"[^A-Za-z0-9]")


def slugify_cwd(path: str) -> str:
    """Replicate the runtime's project key: every non-alphanumeric character becomes '-'.

    The conversion is not limited to separators. A leading separator becomes a
    leading hyphen, and every dot and underscore inside the path becomes one too.
    """
    return _SLUG_RE.sub("-", path)


def resolve_memory_dir(cwd: str, home: Path) -> Path | None:
    """Resolve the memory directory of the project at cwd, or None (fail-safe).

    Verifies that the directory exists and that, after symlink resolution, it sits
    directly inside the runtime's project store under the project's own key. Anything
    else is skipped unread rather than guessed at, so one project's audit can never
    read another project's memory.
    """
    projects_root = (home / ".claude" / "projects").resolve()
    candidate = home / ".claude" / "projects" / slugify_cwd(cwd) / "memory"
    if not candidate.is_dir():
        return None
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, ValueError):
        return None
    try:
        relative = resolved.relative_to(projects_root)
    except ValueError:
        return None
    if len(relative.parts) != 2 or relative.parts[1] != "memory":
        return None
    return candidate


def read_target(path: str) -> str | None:
    """Read a file, tolerating bytes that are not UTF-8. None when it cannot be read.

    One file the audit cannot decode or open must not end the audit, so the failure
    is reported as a value for the caller to record and skip.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def _target(path: Path, root: str, kind: str, category: str) -> dict[str, Any]:
    abspath = str(path)
    try:
        rel = os.path.relpath(abspath, root)
    except ValueError:
        rel = abspath
    return {"path": abspath, "rel": rel, "kind": kind, "category": category}


def _markdown_targets(
    directory: Path, root: str, kind: str, category: str
) -> list[dict[str, Any]]:
    return [
        _target(md, root, kind, category)
        for md in sorted(directory.glob("*.md"))
        if md.is_file()
    ]


def collect_repo_targets(root: str) -> dict[str, Any]:
    """Collect the project's own instruction files by allowlist.

    A target that is not there is a normal state, not a failure: it is recorded
    among the skipped and the collection carries on.
    """
    targets: list[dict[str, Any]] = []
    skipped: list[str] = []
    root_path = Path(root)
    for rel, kind in REPO_FILE_TARGETS:
        path = root_path / rel
        if path.is_file():
            targets.append(_target(path, root, kind, "instruction"))
        else:
            skipped.append(rel)
    for rel, kind in REPO_DIR_TARGETS:
        directory = root_path / rel
        if directory.is_dir():
            targets.extend(_markdown_targets(directory, root, kind, "instruction"))
        else:
            skipped.append(rel + "/")
    return {"targets": targets, "skipped": skipped}


def collect_targets(
    root: str, home: Path, cwd: str, include_global: bool = False
) -> dict[str, Any]:
    """Assemble every audit target: the project's instruction files and its memory.

    Files belonging to the whole installation rather than to this project join only
    when they are asked for, so an audit stays inside the project by default.
    """
    result = collect_repo_targets(root)
    targets = result["targets"]
    skipped = result["skipped"]

    memory_dir = resolve_memory_dir(cwd, home)
    if memory_dir is not None:
        targets.extend(_markdown_targets(memory_dir, root, "memory", "memory"))
    else:
        skipped.append("<project-memory>")

    if include_global:
        outer_claude = home / ".claude" / "CLAUDE.md"
        if outer_claude.is_file():
            targets.append(_target(outer_claude, root, "global_claude_md", "instruction"))
        outer_rules = home / ".claude" / "rules"
        if outer_rules.is_dir():
            targets.extend(_markdown_targets(outer_rules, root, "global_rules", "instruction"))

    return {
        "targets": targets,
        "skipped": skipped,
        "memory_dir": str(memory_dir) if memory_dir else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover context-audit targets")
    parser.add_argument("root", nargs="?", default=".", help="Project root (default cwd)")
    parser.add_argument(
        "--home",
        default=None,
        help="Home directory the project memory store is looked up under "
             "(default: the home of the user running the audit)",
    )
    parser.add_argument(
        "--include-global",
        action="store_true",
        help="Also audit the installation-wide instruction file and rules directory",
    )
    parser.add_argument("--output", default=None, help="Output file (default stdout)")
    args = parser.parse_args(argv)

    root = os.path.abspath(args.root)
    home = Path(args.home) if args.home is not None else Path.home()
    result = collect_targets(root, home, root, include_global=args.include_global)

    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
