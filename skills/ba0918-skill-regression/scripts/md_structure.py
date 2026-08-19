#!/usr/bin/env python3
"""Structural fingerprint of a markdown text (pure functions).

Used to decide mechanically that a change is prose-only. Machine-parsed tokens
are extracted in order of appearance and the sha256 of that sequence is the
fingerprint: two revisions agreeing on it differ in prose alone.

The error directions are asymmetric. Over-extraction (treating prose as a token)
only falls to the heavy side, while under-extraction lets a behaviour change pass
as prose and ride the light approval rail. The reading is therefore an
allow-list, not a deny-list of token syntaxes: only a plain running-text line
counts as prose, and a line carrying any sign of structure — a leading marker,
indentation, a backtick, a bracket, a pipe, something tag-shaped, a setext
underline — is tokenised whole. Unknown and variant markdown syntax falls to the
structural side by default, so no individual syntax can be missed. A deny-list
implementation was shown to miss list items, setext headings, tables without a
leading pipe, tab indentation, HTML, multi-backtick spans and quadruple fences.
"""
import hashlib
import re

# Signs that a line is not running text: inline code, links and references
# (brackets in general — a shortcut reference cannot be told apart from plain
# brackets, so both are taken), table cell separators, emphasis and
# strikethrough delimiters (rewriting a normative **MUST**, or lifting a
# ~~withdrawn instruction~~, changes behaviour), and anything tag-shaped,
# comment-shaped or processing-instruction-shaped (only when `<` is directly
# followed by a letter, `/`, `!` or `?`, so that "a < b" stays prose).
_INLINE_STRUCTURE_RE = re.compile(r"[`\[|*_~]|<[A-Za-z!/?]")

# Leading list marker, ordered or unordered. A list item is where instructions
# themselves are written, so it never counts as prose.
_LIST_RE = re.compile(r"^ {0,3}(?:[-*+]|\d{1,9}[.)])(?:\s|$)")

# Setext heading underline or thematic break: a line of only `=` or only `-`.
_SETEXT_RE = re.compile(r"^ {0,3}(=+|-+)\s*$")

# Opening code fence. Three or more backticks or tildes, as CommonMark has it.
_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")

# Candidate closing fence. A closer is indented 3 columns or fewer; 4 or more is
# a code line inside the fence. Judging after stripping would close the fence
# early and drop everything after it from the fingerprint.
_FENCE_CLOSE_RE = re.compile(r"^ {0,3}(`+|~+)\s*$")


def _indent_columns(line):
    """Leading indentation in columns, tabs expanded on a 4-column tab stop."""
    col = 0
    for ch in line:
        if ch == " ":
            col += 1
        elif ch == "\t":
            col = (col // 4 + 1) * 4
        else:
            break
    return col


def _is_prose(line):
    """True for a plain running-text line — the only kind the fingerprint ignores."""
    if _indent_columns(line) >= 4:
        return False  # indented code, mixed spaces and tabs expanded alike
    stripped = line.strip()
    if not stripped:
        return True  # a blank line separates paragraphs and carries no structure
    if stripped[0] in "#>|":
        return False  # ATX heading, blockquote, table
    if _LIST_RE.match(line) or _SETEXT_RE.match(line):
        return False
    if _INLINE_STRUCTURE_RE.search(line):
        return False
    return True


def structural_tokens(text):
    """Machine-parsed tokens as a list of (kind, value), in order of appearance."""
    tokens = []
    lines = text.split("\n")
    i = 0

    if lines and lines[0].strip() == "---":
        for j in range(1, len(lines)):
            if lines[j].strip() == "---":
                tokens.append(("frontmatter", "\n".join(lines[: j + 1])))
                i = j + 1
                break

    fence_char = None
    fence_len = 0
    fence_buf = []
    prose_para = []  # the prose paragraph in progress, a setext heading candidate
    for ln in lines[i:]:
        if fence_char is not None:
            fence_buf.append(ln)
            # A closer matches the opener's character, runs at least as long, and
            # is indented 3 columns or fewer. Reading a shorter inner run or a
            # deeply indented one as the closer would drop the rest of the text.
            m = _FENCE_CLOSE_RE.match(ln)
            if m and m.group(1)[0] == fence_char and len(m.group(1)) >= fence_len:
                tokens.append(("fence", "\n".join(fence_buf)))
                fence_buf = []
                fence_char = None
            continue
        m = _FENCE_OPEN_RE.match(ln)
        if m:
            fence_char = m.group(1)[0]
            fence_len = len(m.group(1))
            fence_buf = [ln]
            prose_para = []
            continue
        # A setext underline takes the whole preceding paragraph with it as the
        # heading text: CommonMark lets a setext heading span lines, so pairing
        # only the last line would read a first-line edit as prose.
        if _SETEXT_RE.match(ln) and prose_para:
            tokens.append(("heading", "\n".join(prose_para) + "\n" + ln.strip()))
            prose_para = []
            continue
        if _is_prose(ln):
            if ln.strip():
                prose_para.append(ln)
            else:
                prose_para = []  # a blank line ends the paragraph an underline could attach to
            continue
        tokens.append(("line", ln))
        prose_para = []
    if fence_char is not None:
        # An unclosed fence swallows the remainder as code, the heavy side.
        tokens.append(("fence", "\n".join(fence_buf)))
    return tokens


def structural_fingerprint(text):
    """The sha256 hex of the token sequence. Equal fingerprints mean a prose-only diff."""
    h = hashlib.sha256()
    for kind, value in structural_tokens(text):
        h.update(f"{kind}\x1f{value}\x1e".encode("utf-8"))
    return h.hexdigest()
