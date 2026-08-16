#!/usr/bin/env python3
"""Generate, verify, and lint vendored contract copies for skills.

The protocol this tool implements — canonical contract files, digest
normalization, the declaration schema, vendor output, the manifest, and the
exit-code scheme — is specified in contracts/README.md.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Tuple

GENERATOR_NAME = "vendor.py"
GENERATOR_VERSION = "1.0.0"
CONTRACTS_DIR = "contracts"
SKILLS_DIR = "skills"
VENDOR_SUBDIR = "references/vendor"
MANIFEST_NAME = "vendor-manifest.json"
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


class ConfigError(Exception):
    """The tree cannot be processed at all (as opposed to having violations)."""


class Contract(NamedTuple):
    """One canonical contract, loaded and digested."""

    id: str
    version: str
    digest: str
    body: str
    source: str


class SkillDeclarations(NamedTuple):
    """One skill directory together with its parsed contract declarations."""

    name: str
    declarations: List[Declaration]


def load_contracts(root: Path) -> Dict[str, Contract]:
    contracts: Dict[str, Contract] = {}
    contracts_dir = root / CONTRACTS_DIR
    if not contracts_dir.is_dir():
        return contracts
    for path in sorted(contracts_dir.glob("*.md")):
        if path.name == "README.md":
            continue
        text = path.read_text(encoding="utf-8")
        fields = _frontmatter_fields(text)
        contract_id, version = fields.get("id"), fields.get("version")
        if contract_id != path.stem or not is_valid_contract_id(path.stem):
            raise ConfigError(
                f"{path}: frontmatter id must equal the file name and be a valid id"
            )
        if not version:
            raise ConfigError(f"{path}: frontmatter must declare a version")
        contracts[contract_id] = Contract(
            id=contract_id,
            version=version,
            digest=contract_digest(text),
            body=canonical_body(text),
            source=f"{CONTRACTS_DIR}/{path.name}",
        )
    return contracts


def load_skills(root: Path) -> List[SkillDeclarations]:
    skills_dir = root / SKILLS_DIR
    if not skills_dir.is_dir():
        raise ConfigError(f"{root}: no {SKILLS_DIR}/ directory to process")
    skills = []
    for directory in sorted(skills_dir.iterdir()):
        skill_md = directory / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            declarations = parse_declarations(skill_md.read_text(encoding="utf-8"))
        except DeclarationError as error:
            raise ConfigError(f"{skill_md}: {error}") from error
        skills.append(SkillDeclarations(name=directory.name, declarations=declarations))
    return skills


def _frontmatter_fields(text: str) -> Dict[str, str]:
    """Top-level 'key: value' pairs of a frontmatter block."""
    fields = {}
    for line in split_frontmatter(text)[0]:
        if line.startswith((" ", "\t")):
            continue
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip()] = _unquote(value.strip())
    return fields


def render_vendor_file(contract: Contract) -> str:
    # The header carries no source path and no timestamp: a path would break
    # the skill's self-containment and a timestamp would break reproducibility.
    return (
        f"<!-- DO NOT EDIT. Generated by {GENERATOR_NAME}. -->\n"
        f"<!-- contract: {contract.id} -->\n"
        f"<!-- version: {contract.version} -->\n"
        f"<!-- source-digest: {contract.digest} -->\n"
        "\n"
        f"{contract.body}"
    )


def check_declarations(
    skills: List[SkillDeclarations], contracts: Dict[str, Contract]
) -> List[str]:
    """Closure and digest pinning: every declaration resolves, byte-exactly."""
    violations = []
    for skill in skills:
        for declaration in skill.declarations:
            contract = contracts.get(declaration.id)
            if contract is None:
                violations.append(
                    f"closure: {skill.name} declares {declaration.id!r} but "
                    f"{CONTRACTS_DIR}/{declaration.id}.md does not exist"
                )
            elif contract.digest != declaration.digest:
                violations.append(
                    f"digest-mismatch: {skill.name} pins {declaration.id!r} at "
                    f"{declaration.digest} but the canonical contract is "
                    f"{contract.digest}"
                )
    return violations


def expected_vendor_files(
    skills: List[SkillDeclarations], contracts: Dict[str, Contract]
) -> Dict[str, str]:
    """Relative path -> content for every vendor copy the declarations imply."""
    files = {}
    for skill in skills:
        for declaration in skill.declarations:
            contract = contracts[declaration.id]
            path = f"{SKILLS_DIR}/{skill.name}/{VENDOR_SUBDIR}/{contract.id}.md"
            files[path] = render_vendor_file(contract)
    return files


def build_manifest(
    skills: List[SkillDeclarations], contracts: Dict[str, Contract]
) -> dict:
    lock_skills = {}
    used_ids = set()
    for skill in skills:
        if not skill.declarations:
            continue
        lock_skills[skill.name] = [
            {
                "id": declaration.id,
                "version": contracts[declaration.id].version,
                "digest": declaration.digest,
            }
            for declaration in skill.declarations
        ]
        used_ids.update(declaration.id for declaration in skill.declarations)
    return {
        "lock": {"skills": lock_skills},
        "provenance": {
            "contracts": {
                contract_id: {"source": contracts[contract_id].source}
                for contract_id in sorted(used_ids)
            },
            "generator": GENERATOR_NAME,
            "generator_version": GENERATOR_VERSION,
        },
    }


def render_manifest(manifest: dict) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def _existing_vendor_files(root: Path, skills: List[SkillDeclarations]) -> List[Path]:
    found = []
    for skill in skills:
        vendor_dir = root / SKILLS_DIR / skill.name / VENDOR_SUBDIR
        if vendor_dir.is_dir():
            found.extend(sorted(vendor_dir.glob("*.md")))
    return found


def run_gen(root: Path) -> int:
    contracts = load_contracts(root)
    skills = load_skills(root)
    violations = check_declarations(skills, contracts)
    if violations:
        for violation in violations:
            print(violation)
        return 1
    expected = expected_vendor_files(skills, contracts)
    expected_paths = {root / path for path in expected}
    for stale in _existing_vendor_files(root, skills):
        if stale not in expected_paths:
            stale.unlink()
    for relative, content in expected.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    manifest_path = root / MANIFEST_NAME
    manifest_path.write_text(
        render_manifest(build_manifest(skills, contracts)), encoding="utf-8"
    )
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog=GENERATOR_NAME,
        description=(
            "Generate, verify, and lint vendored contract copies. "
            "Exit codes: 0 clean, 1 violations (reported as '<kind>: ...'), "
            "2 configuration or usage error. See contracts/README.md."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("gen", "expand declared contracts into skills and write the manifest"),
        ("verify", "check drift, extra files, closure, digests, and the manifest"),
        ("lint-selfcontain", "check that every skill directory is self-contained"),
    ):
        subparser = subparsers.add_parser(name, help=help_text)
        subparser.add_argument(
            "--root",
            type=Path,
            default=Path("."),
            help="tree containing contracts/ and skills/ (default: cwd)",
        )
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "gen":
            return run_gen(arguments.root)
        raise ConfigError(f"not implemented yet: {arguments.command}")
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
