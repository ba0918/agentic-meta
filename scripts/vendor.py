#!/usr/bin/env python3
"""Generate, verify, and lint vendored contract copies for skills.

The protocol this tool implements — canonical contract files, digest
normalization, the declaration schema, vendor output, the manifest, and the
exit-code scheme — is specified in contracts/README.md.
"""

import hashlib
import re
from typing import List, NamedTuple, Tuple

DIGEST_PREFIX = "sha256:"
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
CONTRACT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
CONTRACT_ID_LIMIT = 64
FRONTMATTER_DELIMITER = "---"


class DeclarationError(ValueError):
    """A skill's contract declaration does not follow the documented schema."""


class Declaration(NamedTuple):
    """One pinned contract dependency declared by a skill."""

    id: str
    digest: str


def is_valid_contract_id(contract_id: str) -> bool:
    """True when the id is safe to embed in a path (allowlist, no traversal)."""
    return (
        len(contract_id) <= CONTRACT_ID_LIMIT
        and ".." not in contract_id
        and bool(CONTRACT_ID_PATTERN.match(contract_id))
    )


def split_frontmatter(text: str) -> Tuple[List[str], str]:
    """Split a document into (frontmatter_lines, body_text).

    The frontmatter block is the leading '---' line through the closing '---'
    line; blank lines immediately after it belong to the separator, not the
    body. A document without frontmatter is all body.
    """
    normalized = text.replace("\r\n", "\n")
    lines = normalized.split("\n")
    if not lines or lines[0] != FRONTMATTER_DELIMITER:
        return [], normalized
    for index in range(1, len(lines)):
        if lines[index] == FRONTMATTER_DELIMITER:
            body_lines = lines[index + 1 :]
            while body_lines and body_lines[0] == "":
                body_lines = body_lines[1:]
            return lines[1:index], "\n".join(body_lines)
    return [], normalized


def canonical_body(text: str) -> str:
    """Frontmatter stripped, LF endings, exactly one trailing newline."""
    _, body = split_frontmatter(text)
    return body.rstrip("\n") + "\n"


def contract_digest(text: str) -> str:
    """Digest of the canonical body, in 'sha256:<hex>' form."""
    digest = hashlib.sha256(canonical_body(text).encode("utf-8")).hexdigest()
    return DIGEST_PREFIX + digest


def parse_declarations(skill_md_text: str) -> List[Declaration]:
    """Read metadata.contracts from a SKILL.md's frontmatter.

    The accepted shape is deliberately narrow — a block-style list of mappings
    with exactly the keys id and digest (see contracts/README.md). Anything
    else raises DeclarationError so a typo cannot silently drop a pin.
    """
    frontmatter, _ = split_frontmatter(skill_md_text)
    entries = _contract_entry_lines(frontmatter)
    declarations = []
    for entry in entries:
        keys = dict(entry)
        if set(keys) != {"id", "digest"}:
            raise DeclarationError(
                "a contracts entry must have exactly the keys id and digest, "
                f"got: {sorted(keys)}"
            )
        contract_id, digest = keys["id"], keys["digest"]
        if not is_valid_contract_id(contract_id):
            raise DeclarationError(f"invalid contract id: {contract_id!r}")
        if not DIGEST_PATTERN.match(digest):
            raise DeclarationError(
                f"digest for {contract_id!r} must match 'sha256:<64 hex>', got: {digest!r}"
            )
        declarations.append(Declaration(id=contract_id, digest=digest))
    return declarations


def _contract_entry_lines(frontmatter_lines: List[str]) -> List[List[tuple]]:
    """Collect the key/value pairs of each '- ' item under metadata.contracts."""
    entries: List[List[tuple]] = []
    in_metadata = False
    in_contracts = False
    for raw in frontmatter_lines:
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if not line:
            continue
        if indent == 0:
            in_metadata = line == "metadata:"
            in_contracts = False
            continue
        if in_metadata and indent == 2:
            in_contracts = line == "contracts:"
            continue
        if not in_contracts:
            continue
        if line.startswith("- "):
            entries.append([])
            line = line[2:].strip()
        if not entries:
            raise DeclarationError(f"unexpected line under contracts: {raw!r}")
        key, separator, value = line.partition(":")
        if not separator:
            raise DeclarationError(f"expected 'key: value' under contracts: {raw!r}")
        entries[-1].append((key.strip(), _unquote(value.strip())))
    return entries


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value
