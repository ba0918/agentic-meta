"""Shared YAML frontmatter parser (pure functions, no PyYAML dependency).

Kept beside the scripts that use it so this skill carries everything it needs
to run. Correctness here is load-bearing: a description this parser reads
wrongly becomes a measurement of the wrong text.

Parsing rules:
- Frontmatter runs from a leading `---` line to the next `---`. Without a
  closing delimiter there is no frontmatter (None / empty dict).
- A top-level key matches `[A-Za-z_][A-Za-z0-9_-]*` at column 0. YAML list
  lines (`- item:`), digit-leading lines and indented lines are not keys.
"""
import re

_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(.*)$")
_BLOCK_SCALARS = (">", "|", ">-", "|-")


def _block_lines(text):
    """Return the lines inside the frontmatter block, or None if there is none."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return lines[1:i]
    return None  # no closing delimiter = no frontmatter


def parse_frontmatter_lines(text):
    """Return top-level keys as [(key, value, raw_line)], or None if there is none.

    raw_line is retained so a caller checking formatting normalization can
    detect non-canonical spellings such as `key:value`.
    """
    body = _block_lines(text)
    if body is None:
        return None
    out = []
    for line in body:
        m = _KEY_RE.match(line)
        if m:
            out.append((m.group(1), m.group(2).strip(), line))
    return out


def parse_frontmatter_fields(text):
    """Return top-level `key: value` pairs as a dict; empty dict without frontmatter."""
    fm = parse_frontmatter_lines(text)
    if fm is None:
        return {}
    return {key: value for key, value, _ in fm}


def extract_description(text):
    """Return the full description, or None if absent (multi-line block scalars included).

    Continuation lines of a `description: >` form are collected up to the next
    top-level key, then joined with spaces after dropping blank lines.
    """
    body = _block_lines(text)
    if body is None:
        return None
    desc_lines = []
    in_desc = False
    for line in body:
        m = _KEY_RE.match(line)
        if m:
            if m.group(1) == "description":
                in_desc = True
                desc_lines.append(m.group(2).strip())
            elif in_desc:
                break  # the next top-level key ends the description
            continue
        if in_desc:
            desc_lines.append(line.strip())
    if not in_desc:
        return None
    if desc_lines and desc_lines[0] in _BLOCK_SCALARS:
        desc_lines = desc_lines[1:]
    return " ".join(l for l in desc_lines if l).strip()


def parse_name_and_description(text):
    """Return {name, description}, or None if there is no frontmatter.

    A missing key yields an empty string (the collect_descriptions contract).
    """
    fm = parse_frontmatter_lines(text)
    if fm is None:
        return None
    name = next((value for key, value, _ in fm if key == "name"), "")
    return {"name": name, "description": extract_description(text) or ""}
