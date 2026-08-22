#!/usr/bin/env python3
"""Emit a stable, read-only structural inventory for a skill."""

import argparse
import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {"node_modules"}
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
DYNAMIC_RE = re.compile(r"(?:\$\{[^}]+\}|\{[^}]+\})/[^\s`'\"]+")
PATH_RE = re.compile(r"(?<![\w:/.-])(?:references|scripts|evals)/[\w./-]+")
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
IMPLICIT_NON_STRING_WORDS = {"~", "null", "true", "false", "yes", "no", "on", "off"}


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
    lines = text.splitlines()
    try:
        end = lines.index("---", 1)
    except ValueError:
        return fallback, None, "invalid"

    values = {}
    observation = "parsed"
    body = lines[1:end]
    index = 0
    while index < len(body):
        line = body[index]
        if not line.strip() or line.startswith((" ", "\t")):
            index += 1
            continue
        if line.startswith("#"):
            index += 1
            continue
        if ":" not in line:
            return fallback, None, "invalid"
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key not in {"name", "description"}:
            index += 1
            continue

        block_header = re.fullmatch(r"([|>][+-]?)(?:\s+#.*)?", value)
        if block_header:
            block = []
            index += 1
            while index < len(body) and (not body[index].strip() or body[index].startswith((" ", "\t"))):
                block.append(body[index])
                index += 1
            parsed, status = _block_scalar(block_header.group(1), block)
        else:
            parsed, status = _inline_scalar(value)
            index += 1
            continuation = []
            while index < len(body) and (
                not body[index].strip() or body[index].startswith((" ", "\t"))
            ):
                continuation.append(body[index])
                index += 1
            status = _status_with_continuation(value, continuation, status)

        if status == "invalid":
            return fallback, None, "invalid"
        if status == "unsupported":
            observation = "unsupported"
            continue
        values[key] = parsed

    return values.get("name") or fallback, values.get("description"), observation


def _inline_scalar(value: str):
    if not value:
        return None, "unsupported"
    if value[0] in "[{":
        return None, _flow_collection_status(value)
    if value[0] in "|>":
        if re.fullmatch(r"[|>](?:[1-9][+-]?|[+-][1-9])(?:\s+#.*)?", value):
            return None, "unsupported"
        return None, "invalid"
    if value[0] == "'":
        index = 1
        result = []
        while index < len(value):
            if value[index] != "'":
                result.append(value[index])
                index += 1
                continue
            if index + 1 < len(value) and value[index + 1] == "'":
                result.append("'")
                index += 2
                continue
            if _only_comment(value[index + 1:]):
                return "".join(result), "parsed"
            return None, "invalid"
        return None, "invalid"
    if value[0] == '"':
        closing = _double_quote_end(value)
        if closing is None or not _only_comment(value[closing + 1:]):
            return None, "invalid"
        try:
            return json.loads(value[:closing + 1]), "parsed"
        except json.JSONDecodeError:
            return None, "unsupported"
    if value[0] in "!&*":
        return None, "unsupported"
    plain = _strip_plain_comment(value)
    if not plain:
        return None, "unsupported"
    if re.search(r":(?:\s|$)", plain) or plain.startswith(
        ("- ", "? ", ": ", ",", "]", "}", "%", "@", "`")
    ):
        return None, "invalid"
    if not _plain_scalar_is_proven_string(plain):
        return None, "unsupported"
    return plain, "parsed"


def _plain_scalar_is_proven_string(value: str) -> bool:
    candidate = value.lower()
    if candidate in IMPLICIT_NON_STRING_WORDS:
        return False
    if candidate.startswith(("+", "-")):
        candidate = candidate[1:]
    if candidate[:1].isdigit():
        return False
    if candidate.startswith("."):
        suffix = candidate[1:]
        return not suffix[:1].isdigit() and suffix not in {"inf", "nan"}
    return True


def _status_with_continuation(value: str, lines, status: str) -> str:
    content = [line for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if not content:
        return status
    if status != "invalid":
        return "unsupported"
    combined = "\n".join([value, *(line.lstrip() for line in content)])
    return "unsupported" if _inline_scalar(combined)[1] != "invalid" else "invalid"


def _flow_collection_status(value: str) -> str:
    pairs = {"[": "]", "{": "}"}
    stack = []
    quote = None
    escaped = False
    index = 0
    while index < len(value):
        character = value[index]
        if quote == '"':
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
        elif quote == "'":
            if character == quote and index + 1 < len(value) and value[index + 1] == quote:
                index += 1
            elif character == quote:
                quote = None
        elif character in "'\"":
            quote = character
        elif character in pairs:
            stack.append(pairs[character])
        elif character in "]}":
            if not stack or stack.pop() != character:
                return "invalid"
            if not stack:
                return "unsupported" if _only_comment(value[index + 1:]) else "invalid"
        index += 1
    return "invalid"


def _double_quote_end(value: str):
    escaped = False
    for index, character in enumerate(value[1:], 1):
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == '"':
            return index
    return None


def _only_comment(remainder: str) -> bool:
    return not remainder.strip() or (remainder[:1].isspace() and remainder.lstrip().startswith("#"))


def _strip_plain_comment(value: str) -> str:
    if value.startswith("#"):
        return ""
    match = re.search(r"\s+#", value)
    return value[:match.start()].rstrip() if match else value.strip()


def _block_scalar(indicator: str, lines):
    nonempty = [line for line in lines if line.strip()]
    if not nonempty:
        value = ""
    else:
        indents = [len(line) - len(line.lstrip(" ")) for line in nonempty]
        if any(line.startswith("\t") for line in nonempty) or min(indents) == 0:
            return None, "invalid"
        indent = min(indents)
        deindented = [line[indent:] if line.strip() else "" for line in lines]
        if indicator.startswith("|"):
            value = "\n".join(deindented)
        else:
            value = _fold_block_lines(deindented)
    if indicator.endswith("-"):
        value = value.rstrip("\n")
    elif indicator.endswith("+"):
        value += "\n"
    else:
        value = value.rstrip("\n") + "\n" if lines else ""
    return value, "parsed"


def _fold_block_lines(lines):
    parts = []
    for index, line in enumerate(lines):
        parts.append(line)
        if index + 1 == len(lines):
            continue
        following = lines[index + 1]
        if not line:
            parts.append("\n")
        elif not following:
            continue
        elif line.startswith(" ") or following.startswith(" "):
            parts.append("\n")
        else:
            parts.append(" ")
    return "".join(parts)


def resolve_skills(target):
    root = Path(target).resolve()
    layers = []
    conventional = root / "skills"
    layers.append(sorted(conventional.glob("*/SKILL.md")) if conventional.is_dir() else [])
    layers.append([root / "SKILL.md"] if (root / "SKILL.md").is_file() else [])
    layers.append(sorted(path for path in root.glob("*/SKILL.md") if not _ignored(path, root)))
    recursive = []
    selected_roots = set()
    for path in _valid_skill_paths(_skill_md_files(root), root):
        if any(parent in selected_roots for parent in path.parents):
            continue
        recursive.append(path)
        selected_roots.add(path.parent)
    layers.append(recursive)
    paths = next((filtered for layer in layers if (filtered := _valid_skill_paths(layer, root))), [])
    result = []
    for path in paths:
        name, description, observation = _frontmatter(path)
        result.append({
            "name": name,
            "description": description,
            "frontmatter": observation,
            "path": path.parent.relative_to(root).as_posix() or ".",
            "directory": path.parent,
        })
    return sorted(result, key=lambda item: (item["path"], item["name"]))


def _valid_skill_paths(paths, root: Path):
    valid = []
    for path in sorted(paths):
        if _ignored(path, root):
            continue
        try:
            resolved = path.resolve()
            is_file = path.is_file()
        except (OSError, RuntimeError):
            continue
        if _within(resolved, root) and is_file:
            valid.append(path)
    return valid


def _references(text: str):
    explicit = [match.split("#", 1)[0].strip() for match in LINK_RE.findall(text)]
    shaped = PATH_RE.findall(LINK_RE.sub("", text))
    dynamic = DYNAMIC_RE.findall(text)
    references = {(item, "markdown") for item in explicit if item}
    references.update((item, "procedural") for item in shaped if item)
    return sorted(references), sorted(set(dynamic))


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _cycle_edges(edges):
    adjacency = {}
    for edge in edges:
        adjacency.setdefault(edge["from"], []).append(edge["to"])
    for destinations in adjacency.values():
        destinations.sort()

    state = {}
    cycles = []

    for source in sorted(set(adjacency).union(destination for values in adjacency.values() for destination in values)):
        if source in state:
            continue
        state[source] = "active"
        stack = [(source, iter(adjacency.get(source, [])))]
        while stack:
            current, destinations = stack[-1]
            try:
                destination = next(destinations)
            except StopIteration:
                state[current] = "complete"
                stack.pop()
                continue
            if state.get(destination) == "active":
                cycles.append({"from": current, "to": destination})
            elif destination not in state:
                state[destination] = "active"
                stack.append((destination, iter(adjacency.get(destination, []))))
    return cycles


def inventory_skill(skill_dir):
    root = Path(skill_dir).resolve()
    entry = root / "SKILL.md"
    if not _within(entry.resolve(), root):
        raise ValueError(f"required target escapes granted directory: {entry}")
    if not entry.is_file():
        raise ValueError(f"required target is missing: {entry}")
    queue = [entry]
    visited = set()
    files = []
    edges = []
    unresolved = []
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        relative = current.relative_to(root).as_posix()
        try:
            raw = current.read_bytes()
        except OSError as error:
            files.append({
                "path": relative,
                "bytes": None,
                "text": None,
                "lines": None,
                "headings": [],
                "readable": False,
                "reason": _io_reason(error),
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
        for reference, reference_kind in references:
            if reference.startswith(("http://", "https://", "mailto:")):
                unresolved.append({"from": relative, "reference": reference, "kind": "unsupported"})
                continue
            reference_path = Path(reference)
            if reference_path.is_absolute():
                unresolved.append({"from": relative, "reference": reference, "kind": "containment"})
                continue
            bases = [current.parent] if reference_kind == "markdown" else [root, current.parent]
            candidates = sorted(set((base / reference_path).resolve() for base in bases))
            contained = [candidate for candidate in candidates if _within(candidate, root)]
            existing = [candidate for candidate in contained if candidate.is_file()]
            if len(existing) > 1:
                unresolved.append({
                    "from": relative,
                    "reference": reference,
                    "kind": "ambiguous",
                    "candidates": sorted(candidate.relative_to(root).as_posix() for candidate in existing),
                })
                continue
            if not contained:
                unresolved.append({"from": relative, "reference": reference, "kind": "containment"})
                continue
            if not existing:
                unresolved.append({"from": relative, "reference": reference, "kind": "missing"})
                continue
            candidate = existing[0]
            destination = candidate.relative_to(root).as_posix()
            edges.append({"from": relative, "to": destination})
            if candidate not in visited and candidate not in queue:
                queue.append(candidate)
        queue.sort(key=lambda path: path.relative_to(root).as_posix())
    return {
        "root": ".",
        "files": sorted(files, key=lambda item: item["path"]),
        "edges": sorted(edges, key=lambda item: (item["from"], item["to"])),
        "cycles": sorted(_cycle_edges(edges), key=lambda item: (item["from"], item["to"])),
        "unresolved": sorted(unresolved, key=lambda item: (item["from"], item["reference"], item["kind"])),
    }


def _io_reason(error: OSError) -> str:
    if isinstance(error, PermissionError):
        return "permission-denied"
    if isinstance(error, FileNotFoundError):
        return "not-found"
    return "io-error"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("target")
    parser.add_argument("--name")
    args = parser.parse_args(argv)
    resolved = resolve_skills(args.target)
    if args.name:
        resolved = [item for item in resolved if item["name"] == args.name]
    if len(resolved) != 1:
        error = "ambiguous-target" if len(resolved) > 1 else "target-not-found"
        candidates = [
            {"name": item["name"], "path": item["path"]}
            for item in resolved
        ]
        print(json.dumps({"error": error, "candidates": candidates}, sort_keys=True), file=sys.stderr)
        return 2
    result = inventory_skill(resolved[0]["directory"])
    result["skill"] = {key: value for key, value in resolved[0].items() if key != "directory"}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
