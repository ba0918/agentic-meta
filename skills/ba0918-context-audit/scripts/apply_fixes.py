#!/usr/bin/env python3
"""
context-audit: applying the fixes a check already decided are automatic.

Given a file's content and the findings targeting it, produce the new content. Only a
finding whose action is AUTO_FIX and which carries a fix_action is applied, and there
are two shapes of fix:

  - a stale path reference: replace the reference inside markdown links and code spans.
  - a memory frontmatter key: normalise one key line inside the frontmatter block only,
    so the body is left byte for byte as it was.

Every replacement is idempotent: applying the result again changes nothing. The
replacement strings are computed by static_checks.py, which is where the single source
of truth for them lives; this module never synthesises content, it only substitutes
one string for another.
"""

import argparse
import json
import sys
from pathlib import Path


def _frontmatter_bounds(lines: list[str]) -> tuple[int, int] | None:
    """Line indices bounding the frontmatter body, or None when no block is closed."""
    if not lines or lines[0].strip() != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return (1, index)
    return None


def _apply_frontmatter(content: str, old: str, new: str) -> str:
    lines = content.split("\n")
    bounds = _frontmatter_bounds(lines)
    if bounds is None:
        return content
    start, end = bounds
    for index in range(start, end):
        # Matched with and without a trailing carriage return, and the terminator is
        # carried over: rewriting the line as plain text would rewrite the line endings
        # of a file that uses carriage returns, which is a change nobody asked for.
        if lines[index] == old:
            lines[index] = new
            break
        if lines[index] == old + "\r":
            lines[index] = new + "\r"
            break
    return "\n".join(lines)


def _apply_reference(content: str, old: str, new: str) -> str:
    content = content.replace(f"]({old})", f"]({new})")
    return content.replace(f"`{old}`", f"`{new}`")


def _apply_one(content: str, finding: dict) -> str:
    if finding.get("action") != "AUTO_FIX":
        return content
    fix = finding.get("fix_action")
    if not isinstance(fix, dict) or "old" not in fix or "new" not in fix:
        return content
    old, new = fix["old"], fix["new"]
    if old == new:
        return content
    if str(finding.get("id", "")).startswith("CA-M001"):
        return _apply_frontmatter(content, old, new)
    return _apply_reference(content, old, new)


def apply_fixes(content: str, findings: list[dict]) -> str:
    """Apply every automatic fix among the findings, in order."""
    for finding in findings:
        content = _apply_one(content, finding)
    return content


def group_by_path(findings: list[dict]) -> dict[str, list[dict]]:
    """Gather the automatic fixes under the file each one opens."""
    groups: dict[str, list[dict]] = {}
    for finding in findings:
        if finding.get("action") != "AUTO_FIX":
            continue
        fix = finding.get("fix_action") or {}
        path = fix.get("path")
        if path:
            groups.setdefault(path, []).append(finding)
    return groups


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply the context-audit findings marked as automatic fixes")
    parser.add_argument("findings_json", help="static_checks.py output (path or '-')")
    parser.add_argument("--write", action="store_true",
                        help="Rewrite the files (default: only count what would change)")
    args = parser.parse_args(argv)

    raw = sys.stdin.read() if args.findings_json == "-" \
        else Path(args.findings_json).read_text(encoding="utf-8")
    data = json.loads(raw)
    findings = data["findings"] if isinstance(data, dict) else data
    groups = group_by_path(findings)

    changed = 0
    for path, group in sorted(groups.items()):
        try:
            content = Path(path).read_text(encoding="utf-8")
        except OSError:
            continue
        rewritten = apply_fixes(content, group)
        if rewritten != content:
            changed += 1
            if args.write:
                Path(path).write_text(rewritten, encoding="utf-8")
    print(json.dumps({"files_changed": changed, "auto_fix_files": len(groups)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
