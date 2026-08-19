#!/usr/bin/env python3
"""A reader for the block YAML subset a scenario declaration is written in.

Scenario files are read by people and by this instrument alike, so the format is
YAML rather than JSON. Parsing it with a general YAML library would add a
dependency a skill installed by copy cannot count on, and would accept
constructs — tags, aliases, merge keys — whose whole point is to make a document
mean something other than what it literally says.

This reader therefore accepts only what a scenario needs: block mappings, block
sequences, literal block scalars, and plain, single-quoted or double-quoted
scalars. Everything else raises. Refusing loudly is the design: a construct read
wrongly would silently change what a scenario declares, and there is no way to
construct an arbitrary object through this reader at all.

Accepted, in full:
  - `key: value` mappings, nested by indentation (spaces only)
  - `- item` sequences, indented under their key or at the key's own indentation
  - `key: |` and `key: |-` literal blocks, kept exactly as written
  - scalars: text, integers, `true` / `false`, empty meaning nothing
  - `#` comments on their own line or after whitespace
"""
import re

__all__ = ["YamlSubsetError", "load"]


class YamlSubsetError(Exception):
    """The document used something outside the accepted subset."""


_KEY_RE = re.compile(r"^([A-Za-z0-9_./-]+):\s*(.*)$")
_INT_RE = re.compile(r"^-?\d+$")
_REFUSED_SCALAR_STARTS = {
    "{": "a flow mapping",
    "[": "a flow sequence",
    "&": "an anchor",
    "*": "an alias",
    "!": "a tag",
    ">": "a folded block scalar, which would rewrite the line breaks",
    "|": "a block scalar header other than `|` or `|-`",
}


def _fail(lineno, what):
    raise YamlSubsetError(f"line {lineno}: {what}")


def _indent_of(raw, lineno):
    n = 0
    for ch in raw:
        if ch == " ":
            n += 1
        elif ch == "\t":
            _fail(lineno, "tab indentation is not accepted; use spaces")
        else:
            break
    return n


def _strip_comment(text):
    """Drop a trailing comment. A `#` needs whitespace before it to start one."""
    out = []
    for i, ch in enumerate(text):
        if ch == "#" and (i == 0 or text[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


def _unquote(text, lineno):
    quote = text[0]
    if len(text) < 2 or text[-1] != quote:
        _fail(lineno, "a quoted scalar is not closed")
    inner = text[1:-1]
    if quote == "'":
        return inner.replace("''", "'")
    return (inner.replace("\\n", "\n").replace("\\t", "\t")
                 .replace('\\"', '"').replace("\\\\", "\\"))


def _scalar(text, lineno):
    text = text.strip()
    if text[:1] in ("'", '"'):
        return _unquote(text, lineno)
    text = _strip_comment(text)
    if text == "":
        return None
    refused = _REFUSED_SCALAR_STARTS.get(text[0])
    if refused is not None:
        _fail(lineno, f"{refused} is not accepted")
    if text in ("true", "false"):
        return text == "true"
    if _INT_RE.match(text):
        return int(text)
    return text


class _Reader:
    def __init__(self, text):
        self.lines = text.split("\n")
        self.i = 0

    def peek(self):
        """Next significant line as (indent, content, lineno), or None at the end."""
        j = self.i
        while j < len(self.lines):
            raw = self.lines[j]
            if raw.strip() == "" or raw.lstrip().startswith("#"):
                j += 1
                continue
            lineno = j + 1
            indent = _indent_of(raw, lineno)
            self.i = j
            return indent, raw[indent:].rstrip(), lineno
        self.i = j
        return None

    def advance(self):
        self.i += 1

    def parse_mapping(self, indent):
        result = {}
        while True:
            node = self.peek()
            if node is None:
                break
            ind, content, lineno = node
            if ind < indent:
                break
            if ind > indent:
                _fail(lineno, "indentation does not line up with the block it is in")
            if content == "-" or content.startswith("- "):
                _fail(lineno, "a sequence entry where a `key:` was expected")
            m = _KEY_RE.match(content)
            if m is None:
                _fail(lineno, f"not a `key: value` line: {content!r}")
            key, rest = m.group(1), m.group(2)
            if key in result:
                _fail(lineno, f"duplicate key {key!r}")
            self.advance()
            result[key] = self.parse_value(rest, indent, lineno)
        return result

    def parse_value(self, rest, indent, lineno):
        if rest in ("|", "|-"):
            return self.parse_block_scalar(indent, strip=(rest == "|-"))
        if rest.strip() != "":
            return _scalar(rest, lineno)
        node = self.peek()
        if node is None:
            return None
        ind, content, _ = node
        is_entry = content == "-" or content.startswith("- ")
        if ind > indent:
            return self.parse_sequence(ind) if is_entry else self.parse_mapping(ind)
        if ind == indent and is_entry:
            return self.parse_sequence(ind)
        return None

    def parse_sequence(self, indent):
        items = []
        while True:
            node = self.peek()
            if node is None:
                break
            ind, content, lineno = node
            if ind != indent or not (content == "-" or content.startswith("- ")):
                break
            rest = content[2:] if content.startswith("- ") else ""
            if rest.strip() == "":
                self.advance()
                items.append(self.parse_value("", indent, lineno))
                continue
            if _KEY_RE.match(rest):
                # A mapping opening on the entry line: re-read the line as the
                # first key of a mapping indented to where the entry's text began.
                inner = indent + 2
                self.lines[self.i] = " " * inner + rest
                items.append(self.parse_mapping(inner))
                continue
            self.advance()
            items.append(_scalar(rest, lineno))
        return items

    def parse_block_scalar(self, parent_indent, strip):
        collected = []
        block_indent = None
        while self.i < len(self.lines):
            raw = self.lines[self.i]
            if raw.strip() == "":
                collected.append("")
                self.i += 1
                continue
            ind = _indent_of(raw, self.i + 1)
            if ind <= parent_indent:
                break
            if block_indent is None:
                block_indent = ind
            collected.append(raw[block_indent:])
            self.i += 1
        while collected and collected[-1] == "":
            collected.pop()
        if not collected:
            return ""
        text = "\n".join(collected)
        return text if strip else text + "\n"


def load(text):
    """Read the document and return the mapping it declares."""
    reader = _Reader(text)
    node = reader.peek()
    if node is None:
        raise YamlSubsetError("the document declares nothing")
    indent, content, lineno = node
    if indent != 0:
        _fail(lineno, "the document does not start at the left margin")
    if content == "-" or content.startswith("- "):
        _fail(lineno, "the document is a sequence; a scenario declares one mapping")
    value = reader.parse_mapping(0)
    trailing = reader.peek()
    if trailing is not None:
        _fail(trailing[2], f"unexpected content after the document: {trailing[1]!r}")
    return value
