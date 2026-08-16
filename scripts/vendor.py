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
import shutil
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

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
CONFORMANCE_SUBDIR = "conformance"
BYTECODE_CACHE_DIR = "__pycache__"


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
    seen_ids = set()
    for entry in entries:
        if len(entry) != len({key for key, _ in entry}):
            raise DeclarationError(
                "a contracts entry repeats a key, so one value would silently "
                f"override the other: {[key for key, _ in entry]}"
            )
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
        if contract_id in seen_ids:
            raise DeclarationError(f"contract {contract_id!r} is declared twice")
        seen_ids.add(contract_id)
        declarations.append(Declaration(id=contract_id, digest=digest))
    return declarations


def _contract_entry_lines(frontmatter_lines: List[str]) -> List[List[tuple]]:
    """Collect the key/value pairs of each '- ' item under metadata.contracts."""
    entries: List[List[tuple]] = []
    in_metadata = False
    in_contracts = False
    saw_contracts_key = False
    for raw in frontmatter_lines:
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if not line:
            continue
        key, separator, _ = line.partition(":")
        if separator and key.strip() == "contracts":
            saw_contracts_key = True
        if indent == 0:
            in_metadata = line == "metadata:"
            in_contracts = False
            continue
        if in_metadata and indent == 2:
            if in_contracts and line.startswith("- "):
                raise DeclarationError(
                    f"contracts entries must be indented under the contracts key: {raw!r}"
                )
            key, separator, value = line.partition(":")
            if separator and key.strip() == "contracts":
                if value.strip():
                    raise DeclarationError(
                        f"contracts must be a block-style list, not an inline value: {raw!r}"
                    )
                in_contracts = True
            else:
                in_contracts = False
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
    # Fail-loud backstop: an unrecognized-but-valid-YAML shape (for example
    # 4-space indentation under metadata, or a trailing comment on the
    # metadata: line) must not silently drop every pin.
    if saw_contracts_key and not entries:
        raise DeclarationError(
            "frontmatter contains a 'contracts:' key but no declaration was "
            "recognized; contracts must be a block-style list under "
            "'metadata:' with 2-space indentation"
        )
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
    conformance_digest: Optional[str]


class SkillDeclarations(NamedTuple):
    """One skill directory together with its parsed contract declarations."""

    name: str
    declarations: List[Declaration]


def conformance_digest(root: Path, contract_id: str) -> Optional[str]:
    """Digest pinning contracts/<id>/conformance/**, or None without that dir.

    Deterministic: files are fed sorted by path, each framed as
    'relative-posix-path NUL size NUL content' so file boundaries cannot be
    confused. Contents are hashed as raw bytes, not canonicalized text,
    because conformance tests execute byte-exactly. __pycache__ is excluded:
    merely running the tests would otherwise change the digest.
    """
    conformance_dir = root / CONTRACTS_DIR / contract_id / CONFORMANCE_SUBDIR
    if not conformance_dir.is_dir():
        return None
    hasher = hashlib.sha256()
    for path in sorted(conformance_dir.rglob("*")):
        relative = path.relative_to(conformance_dir)
        if BYTECODE_CACHE_DIR in relative.parts:
            continue
        if not path.is_file():
            continue
        content = path.read_bytes()
        hasher.update(f"{relative.as_posix()}\0{len(content)}\0".encode("utf-8"))
        hasher.update(content)
    return DIGEST_PREFIX + hasher.hexdigest()


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
            conformance_digest=conformance_digest(root, contract_id),
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
            contract = contracts.get(declaration.id)
            # An unresolvable declaration is already reported as a closure
            # violation; skipping it here keeps regeneration total on broken
            # trees so the remaining checks still run.
            if contract is None:
                continue
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
        # The lock records the canonical digest (what the vendor copy was
        # generated from); gen refuses when a declaration pins anything else,
        # so a digest drift in a declaration cannot leak into the lock.
        entries = [
            {
                "id": declaration.id,
                "version": contracts[declaration.id].version,
                "digest": contracts[declaration.id].digest,
            }
            for declaration in skill.declarations
            if declaration.id in contracts
        ]
        if entries:
            lock_skills[skill.name] = entries
        used_ids.update(
            declaration.id
            for declaration in skill.declarations
            if declaration.id in contracts
        )
    return {
        "lock": {
            # Conformance is pinned per contract, not per skill: the tests
            # belong to the contract, so one digest covers every dependent.
            # A contract without a conformance directory is omitted.
            "conformance": {
                contract_id: contracts[contract_id].conformance_digest
                for contract_id in sorted(used_ids)
                if contracts[contract_id].conformance_digest is not None
            },
            "skills": lock_skills,
        },
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


def _existing_vendor_files(root: Path) -> List[Path]:
    """Every entry directly under any skill's vendor directory.

    Scans all directories under skills/ — not just the ones with a SKILL.md —
    so leftovers of a removed or renamed skill are still found, and lists
    every entry (non-.md files and subdirectories included), because nothing
    but generated vendor copies belongs there.
    """
    found = []
    skills_dir = root / SKILLS_DIR
    if not skills_dir.is_dir():
        return found
    for directory in sorted(skills_dir.iterdir()):
        vendor_dir = directory / VENDOR_SUBDIR
        if vendor_dir.is_dir():
            found.extend(sorted(vendor_dir.iterdir()))
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
    for stale in _existing_vendor_files(root):
        if stale not in expected_paths:
            if stale.is_dir():
                shutil.rmtree(stale)
            else:
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


def run_verify(root: Path) -> int:
    contracts = load_contracts(root)
    skills = load_skills(root)
    violations = check_declarations(skills, contracts)

    expected = expected_vendor_files(skills, contracts)
    for relative, content in expected.items():
        path = root / relative
        if not path.is_file():
            violations.append(f"drift: {relative} is missing; run gen to restore it")
        elif path.read_bytes() != content.encode("utf-8"):
            violations.append(f"drift: {relative} differs from its regenerated content")

    declared_paths = {
        root / SKILLS_DIR / skill.name / VENDOR_SUBDIR / f"{declaration.id}.md"
        for skill in skills
        for declaration in skill.declarations
    }
    for actual in _existing_vendor_files(root):
        if actual not in declared_paths:
            violations.append(
                f"extra: {actual.relative_to(root)} is not declared by any skill"
            )

    expected_manifest = build_manifest(skills, contracts)
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        violations.append(f"manifest: {MANIFEST_NAME} is missing; run gen to create it")
    else:
        disk_bytes = manifest_path.read_bytes()
        locked = _locked_conformance(disk_bytes)
        comparison = expected_manifest
        if locked is not None:
            violations.extend(
                _conformance_violations(locked, expected_manifest["lock"]["conformance"])
            )
            # The byte comparison runs against the locked conformance map, so
            # a divergence already reported above is not double-reported as a
            # manifest violation on top.
            comparison = {
                **expected_manifest,
                "lock": {**expected_manifest["lock"], "conformance": locked},
            }
        if disk_bytes != render_manifest(comparison).encode("utf-8"):
            violations.append(f"manifest: {MANIFEST_NAME} differs from regeneration")

    for violation in violations:
        print(violation)
    return 1 if violations else 0


def _locked_conformance(manifest_bytes: bytes) -> Optional[Dict[str, str]]:
    """The lock.conformance map of an on-disk manifest.

    None when the manifest does not parse into that shape — the byte
    comparison against regeneration then reports it as a manifest violation.
    """
    try:
        manifest = json.loads(manifest_bytes)
    except ValueError:
        return None
    lock = manifest.get("lock") if isinstance(manifest, dict) else None
    conformance = lock.get("conformance") if isinstance(lock, dict) else None
    if not isinstance(conformance, dict):
        return None
    if not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in conformance.items()
    ):
        return None
    return conformance


def _conformance_violations(
    locked: Dict[str, str], current: Dict[str, str]
) -> List[str]:
    """Divergence between locked and current conformance digests, per contract."""
    violations = []
    for contract_id in sorted(set(locked) | set(current)):
        locked_digest = locked.get(contract_id)
        current_digest = current.get(contract_id)
        if locked_digest == current_digest:
            continue
        if locked_digest is None:
            detail = "conformance tests exist but are not locked; run gen to lock them"
        elif current_digest is None:
            detail = (
                "locked conformance tests are missing from "
                f"{CONTRACTS_DIR}/{contract_id}/{CONFORMANCE_SUBDIR}/"
            )
        else:
            detail = "conformance content differs from the locked digest"
        violations.append(f"conformance-mismatch: {contract_id}: {detail}")
    return violations


PARENT_ESCAPE_TOKENS = ("../", "..\\")
# A token counts as an absolute path when it starts at a reference boundary
# (start of line, whitespace, quotes, '=', '(', '[', ',' or ';') and is rooted
# outside the skill: '/' with at least two segments (so prose like '/help' is
# not a path), '~/', or a Windows drive. ':' is deliberately not a boundary:
# it precedes '//' in URLs, and URL safety relies on no boundary appearing
# before a URL's slashes.
ABSOLUTE_PATH_PATTERN = re.compile(
    r"""(?:^|(?<=[\s"'`=(\[,;]))"""
    r"""(?:/[^\s"'`)\]/]+/[^\s"'`)\]]+|~/[^\s"'`)\]]*|[A-Za-z]:[\\/][^\s"'`)\]]+)"""
)


def lint_lines(relative_path: str, lines: List[str]) -> List[str]:
    """Self-containment violations of one file, as '<kind>: <site>: <detail>'."""
    violations = []
    for number, line in enumerate(lines, start=1):
        site = f"{relative_path}:{number}"
        if any(token in line for token in PARENT_ESCAPE_TOKENS):
            violations.append(
                f"parent-escape: {site}: reference above the skill directory"
            )
        # A shebang names an interpreter for the OS, not a file the skill
        # reads, so the interpreter token cannot break self-containment.
        # Only that token is exempt — any later absolute path on the same
        # line is a real reference. Blanking the token with spaces keeps
        # column positions and leaves a whitespace boundary before the rest.
        if number == 1 and line.startswith("#!"):
            interpreter = re.match(r"#!\s*\S*", line)
            line = " " * interpreter.end() + line[interpreter.end() :]
        # URLs need no special case: their slashes are never preceded by a
        # reference boundary, so the pattern cannot match inside them.
        for match in ABSOLUTE_PATH_PATTERN.finditer(line):
            violations.append(
                f"absolute-path: {site}: absolute reference {match.group(0)!r}"
            )
    return violations


def run_lint_selfcontain(root: Path) -> int:
    skills_dir = root / SKILLS_DIR
    if not skills_dir.is_dir():
        raise ConfigError(f"{root}: no {SKILLS_DIR}/ directory to lint")
    violations = []
    for path in sorted(skills_dir.rglob("*")):
        # A symlink is checked by where it resolves, not by its text content:
        # a link whose target lies outside the skill directory is an escape
        # even though no path string appears in any file.
        if path.is_symlink():
            skill_dir = skills_dir / path.relative_to(skills_dir).parts[0]
            if not path.resolve().is_relative_to(skill_dir.resolve()):
                violations.append(
                    f"symlink-escape: {path.relative_to(root)}: "
                    "symlink resolves outside the skill directory"
                )
            continue
        if not path.is_file():
            continue
        data = path.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            # The violation patterns are pure ASCII, and latin-1 maps every
            # byte to a character, so this fallback scans the whole file
            # instead of silently skipping non-UTF-8 content. UTF-8 is tried
            # first only so that reported snippets stay readable.
            text = data.decode("latin-1")
        violations.extend(
            lint_lines(str(path.relative_to(root)), text.split("\n"))
        )
    for violation in violations:
        print(violation)
    return 1 if violations else 0


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
        if arguments.command == "verify":
            return run_verify(arguments.root)
        return run_lint_selfcontain(arguments.root)
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
