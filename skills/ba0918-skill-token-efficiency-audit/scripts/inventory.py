#!/usr/bin/env python3
"""Emit a stable, read-only structural inventory for a skill."""

import argparse
import json
import os
import re
from pathlib import Path

SKIP_DIRS = {"node_modules"}
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
DYNAMIC_RE = re.compile(r"(?:\$\{[^}]+\}|\{[^}]+\})/[^\s`'\"]+")
PATH_RE = re.compile(r"(?<![\w:/.-])(?:references|scripts|evals)/[\w./-]+")
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def _ignored(path: Path, root: Path) -> bool:
    return any(part.startswith(".") or part in SKIP_DIRS for part in path.relative_to(root).parts)


def _skill_md_files(root: Path):
    for path in root.rglob("SKILL.md"):
        if not _ignored(path, root):
            yield path


def _frontmatter(path: Path):
    fallback = path.parent.name
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return fallback, None, "unreadable"
    if not text.startswith("---\n"):
        return fallback, None, "absent"
    end = text.find("\n---", 4)
    if end < 0:
        return fallback, None, "invalid"
    values = {}
    for line in text[4:end].splitlines():
        if not line.strip() or line.startswith((" ", "\t")):
            continue
        if ":" not in line:
            return fallback, None, "invalid"
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values.get("name") or fallback, values.get("description"), "parsed"


def resolve_skills(target):
    root = Path(target).resolve()
    layers = []
    conventional = root / "skills"
    layers.append(sorted(conventional.glob("*/SKILL.md")) if conventional.is_dir() else [])
    layers.append([root / "SKILL.md"] if (root / "SKILL.md").is_file() else [])
    layers.append(sorted(path for path in root.glob("*/SKILL.md") if not _ignored(path, root)))
    recursive = []
    selected_roots = set()
    for path in sorted(_skill_md_files(root)):
        if any(parent in selected_roots for parent in path.parents):
            continue
        recursive.append(path)
        selected_roots.add(path.parent)
    layers.append(recursive)
    paths = next((layer for layer in layers if layer), [])
    result = []
    for path in paths:
        if _ignored(path, root):
            continue
        name, description, observation = _frontmatter(path)
        result.append({
            "name": name,
            "description": description,
            "frontmatter": observation,
            "path": path.parent.relative_to(root).as_posix() or ".",
            "directory": path.parent,
        })
    return sorted(result, key=lambda item: (item["path"], item["name"]))


def _references(text: str):
    explicit = [match.split("#", 1)[0].strip() for match in LINK_RE.findall(text)]
    shaped = PATH_RE.findall(text)
    dynamic = DYNAMIC_RE.findall(text)
    return sorted(set(x for x in explicit + shaped if x)), sorted(set(dynamic))


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def inventory_skill(skill_dir):
    root = Path(skill_dir).resolve()
    entry = root / "SKILL.md"
    if not entry.is_file():
        raise ValueError(f"required target is missing: {entry}")
    queue = [entry]
    visited = set()
    files = []
    edges = []
    cycles = []
    unresolved = []
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        relative = current.relative_to(root).as_posix()
        try:
            raw = current.read_bytes()
        except OSError:
            files.append({
                "path": relative,
                "bytes": None,
                "text": None,
                "lines": None,
                "headings": [],
                "readable": False,
            })
            continue
        try:
            text = raw.decode("utf-8")
            is_text = "\x00" not in text
        except UnicodeDecodeError:
            text, is_text = "", False
        files.append({
            "path": relative,
            "bytes": len(raw),
            "text": is_text,
            "lines": len(text.splitlines()) if is_text else None,
            "headings": HEADING_RE.findall(text) if is_text else [],
            "readable": True,
        })
        if not is_text:
            continue
        references, dynamic = _references(text)
        unresolved.extend({"from": relative, "reference": item, "kind": "dynamic"} for item in dynamic)
        for reference in references:
            if reference.startswith(("http://", "https://", "mailto:")):
                unresolved.append({"from": relative, "reference": reference, "kind": "unsupported"})
                continue
            candidate = Path(reference)
            if candidate.is_absolute():
                unresolved.append({"from": relative, "reference": reference, "kind": "containment"})
                continue
            candidate = (current.parent / candidate).resolve()
            if not _within(candidate, root):
                unresolved.append({"from": relative, "reference": reference, "kind": "containment"})
            elif not candidate.is_file():
                unresolved.append({"from": relative, "reference": reference, "kind": "missing"})
            else:
                destination = candidate.relative_to(root).as_posix()
                edges.append({"from": relative, "to": destination})
                if candidate in visited or candidate in queue:
                    cycles.append({"from": relative, "to": destination})
                else:
                    queue.append(candidate)
        queue.sort(key=lambda path: path.relative_to(root).as_posix())
    return {
        "root": ".",
        "files": sorted(files, key=lambda item: item["path"]),
        "edges": sorted(edges, key=lambda item: (item["from"], item["to"])),
        "cycles": sorted(cycles, key=lambda item: (item["from"], item["to"])),
        "unresolved": sorted(unresolved, key=lambda item: (item["from"], item["reference"], item["kind"])),
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("target")
    parser.add_argument("--name")
    args = parser.parse_args(argv)
    resolved = resolve_skills(args.target)
    if args.name:
        resolved = [item for item in resolved if item["name"] == args.name]
    if len(resolved) != 1:
        parser.error(f"target must resolve to exactly one skill; found {len(resolved)}")
    result = inventory_skill(resolved[0]["directory"])
    result["skill"] = {key: value for key, value in resolved[0].items() if key != "directory"}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
