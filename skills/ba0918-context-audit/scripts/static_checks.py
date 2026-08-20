#!/usr/bin/env python3
"""ba0918-context-audit: the pure-function CA-* rule engine.

Every rule is a pure function `check(targets, ctx) -> list[Finding]` listed in RULES,
and this module is the dispatcher over that list. Adding a rule is writing the
function, listing it, and adding its tests; no existing rule is touched.

A finding carries, whichever rule produced it:
  id, severity, action, where(file:line), what, why, how, fix_action({old,new,path}|None)

Every text a finding carries is passed through the credential mask before it leaves
this module, so a value detected in an instruction file never reaches the findings
that get written out. The masking happens in one place, finalize_findings.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, NamedTuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import secret_detect  # noqa: E402

# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

CANONICAL_FINDING_FIELDS = ("id", "severity", "action", "where", "what", "why",
                            "how", "fix_action")

_MASKED_FINDING_FIELDS = ("where", "what", "why", "how")


def make_finding(rule_id, severity, action, where, what, why, how, fix_action=None):
    return {"id": rule_id, "severity": severity, "action": action, "where": where,
            "what": what, "why": why, "how": how, "fix_action": fix_action}


def validate_finding_schema(finding: dict) -> list[str]:
    """Name the required fields the finding does not carry (empty list = complete)."""
    return [key for key in CANONICAL_FINDING_FIELDS if key not in finding]


# What a finding says instead of the line, when the line came out of a memory. A memory
# is written mid-session and reviewed by nobody, so it accumulates the vocabulary of the
# work itself — a customer's name, an internal hostname. The mask below is a blocklist
# and knows neither shape, so a transcribed memory line would carry both into whatever
# reads the finding afterwards. The place, the kind and the direction are enough to act
# on and disclose nothing the line itself holds.
MEMORY_LINE_WITHHELD = "(a line in a memory; its text is withheld)"


def _is_memory(target: dict) -> bool:
    return target.get("kind") == "memory"


def _mask_fix_action(fix_action: dict) -> dict:
    # 'path' names the file a fix opens, and one of the credential patterns matches a
    # path under a user's home directory. Masking it would leave a fix pointing at a
    # placeholder, so only the text a fix carries is masked, never its destination.
    return {
        key: (secret_detect.mask_secrets(value)
              if key != "path" and isinstance(value, str) else value)
        for key, value in fix_action.items()
    }


def finalize_findings(findings: list[dict]) -> list[dict]:
    """Mask credentials in every text a finding carries, including its fix."""
    masked = []
    for finding in findings:
        out = dict(finding)
        for key in _MASKED_FINDING_FIELDS:
            if isinstance(out.get(key), str):
                out[key] = secret_detect.mask_secrets(out[key])
        if isinstance(out.get("fix_action"), dict):
            out["fix_action"] = _mask_fix_action(out["fix_action"])
        masked.append(out)
    return masked



# ---------------------------------------------------------------------------
# Reading references out of instruction text
# ---------------------------------------------------------------------------

_LINK_RE = re.compile(r"\]\(([^)\s#]+)\)")
_CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
_GENERATED_NAME_RE = re.compile(r"^\d{8,}")
_PATH_ALPHABET_RE = re.compile(r"^[A-Za-z0-9_./-]+$")
_EXTENSION_RE = re.compile(r"\.[A-Za-z0-9]+$")


def _is_pathish(ref: str) -> bool:
    """Whether the text reads as a path this audit can check for existence."""
    if not _PATH_ALPHABET_RE.match(ref):
        return False
    if ref.startswith(("http://", "https://", "mailto:", "#", "/")):
        return False
    if "{" in ref or "*" in ref:
        return False
    if _GENERATED_NAME_RE.match(os.path.basename(ref)):
        return False
    if "/" not in ref:
        return False
    return bool(_EXTENSION_RE.search(os.path.basename(ref))) or ref.endswith("/")


def _extract_path_refs(content: str) -> list[tuple[str, int, str]]:
    """Every path-shaped reference as (ref, line number, how it was written).

    A markdown link and a code span are told apart because they carry different
    intent: a link is written to be followed, while a code span is as often an
    illustration in prose. Consumers filter the two differently.
    """
    refs: list[tuple[str, int, str]] = []
    for lineno, line in enumerate(content.splitlines(), start=1):
        for match in _LINK_RE.finditer(line):
            if _is_pathish(match.group(1)):
                refs.append((match.group(1), lineno, "link"))
        for match in _CODE_SPAN_RE.finditer(line):
            ref = match.group(1).strip()
            if _is_pathish(ref):
                refs.append((ref, lineno, "code_span"))
    return refs


_INDEX_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
                    "vendor", ".claude", "target", "dist", "build"}
_INDEX_MAX_FILES = 20000


def _basename_index(root: str) -> tuple[frozenset[str], bool]:
    """Every filename in the tree, and whether the walk got through all of it.

    The walk is bounded, so a huge tree cannot stall the audit. An incomplete index
    makes the caller fail safe: an unknown name is treated as one that exists.
    """
    names: set[str] = set()
    complete = True
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _INDEX_SKIP_DIRS]
        names.update(filenames)
        if len(names) > _INDEX_MAX_FILES:
            complete = False
            break
    return frozenset(names), complete


def _code_span_is_checkable(root: str, ref: str,
                            basename_index: tuple[frozenset[str], bool]) -> bool:
    """Whether a reference written as a code span is a claim about a real file.

    Precision is chosen over recall here, because a code span is as often prose. A
    reference without a file extension names a directory in passing. A reference whose
    parent directory is missing while its filename exists elsewhere in the tree is
    shorthand for that file. Only a name found nowhere is the deleted-directory case,
    which has to stay checkable or the rule misses what it exists for.
    """
    if not _EXTENSION_RE.search(os.path.basename(ref)):
        return False
    parent = os.path.normpath(os.path.join(root, os.path.dirname(ref)))
    if os.path.isdir(parent):
        return True
    names, complete = basename_index
    if not complete:
        return False
    return os.path.basename(ref) not in names


def _ref_exists(root: str, ref: str) -> bool:
    return os.path.exists(os.path.normpath(os.path.join(root, ref)))


def _within_one_edit(a: str, b: str) -> bool:
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(1 for x, y in zip(a, b) if x != y) == 1
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    i = j = 0
    edited = False
    while i < len(shorter) and j < len(longer):
        if shorter[i] != longer[j]:
            if edited:
                return False
            edited = True
            j += 1
        else:
            i += 1
            j += 1
    return True


def _unique_near_neighbour(root: str, ref: str) -> str | None:
    """The one existing file beside the reference whose name is a single edit away."""
    parent = os.path.dirname(ref)
    parent_abs = os.path.normpath(os.path.join(root, parent))
    if not os.path.isdir(parent_abs):
        return None
    base = os.path.basename(ref)
    candidates = [name for name in os.listdir(parent_abs) if _within_one_edit(base, name)]
    if len(candidates) != 1:
        return None
    return os.path.join(parent, candidates[0]).replace(os.sep, "/") if parent \
        else candidates[0]


# ---------------------------------------------------------------------------
# CA-S001: a reference to a file that is not there
# ---------------------------------------------------------------------------

_STALE_REF_WHY = ("an instruction file pointing at a file that is not there "
                  "misleads the agent that reads it")


def check_ca_s001(targets, ctx):
    findings = []
    root = ctx["root"]
    basename_index = None
    for t in targets:
        if t["category"] != "instruction":
            continue
        for ref, lineno, written_as in _extract_path_refs(t["content"]):
            if written_as == "code_span":
                if basename_index is None:
                    basename_index = _basename_index(root)
                if not _code_span_is_checkable(root, ref, basename_index):
                    continue
            if _ref_exists(root, ref):
                continue
            where = f"{t['rel']}:{lineno}"
            neighbour = _unique_near_neighbour(root, ref)
            if neighbour is not None:
                findings.append(make_finding(
                    "CA-S001", "WARN", "AUTO_FIX", where,
                    what=f"reference to a path that does not exist `{ref}`, "
                         f"with one near neighbour that does",
                    why=_STALE_REF_WHY,
                    how=f"replace `{ref}` with `{neighbour}`",
                    fix_action={"path": t["path"], "old": ref, "new": neighbour}))
            else:
                findings.append(make_finding(
                    "CA-S001", "WARN", "NEEDS_JUDGMENT", where,
                    what=f"reference to a path that does not exist `{ref}`",
                    why=_STALE_REF_WHY,
                    how="correct the path, or remove the reference"))
    return findings



# ---------------------------------------------------------------------------
# CA-S002: a reference to a skill directory that is not there
# ---------------------------------------------------------------------------

_SKILL_DIR_REF_RE = re.compile(r"\bskills/([a-z][a-z0-9-]*)/")

# The directory skills share holds helpers, not a skill, so it is never a name the
# audit can look up among the skills.
_NOT_A_SKILL_NAME = {"shared"}


def check_ca_s002(targets, ctx):
    findings = []
    known = ctx["skill_names"]
    for t in targets:
        if t["category"] != "instruction":
            continue
        for lineno, line in enumerate(t["content"].splitlines(), start=1):
            for match in _SKILL_DIR_REF_RE.finditer(line):
                name = match.group(1)
                if name in _NOT_A_SKILL_NAME or name in known:
                    continue
                findings.append(make_finding(
                    "CA-S002", "WARN", "NEEDS_JUDGMENT", f"{t['rel']}:{lineno}",
                    what=f"reference to a skill directory that does not exist "
                         f"`skills/{name}/`",
                    why="a mention of a skill that is not there is a sign the "
                        "instructions have gone stale",
                    how="correct the skill name, or remove the mention"))
    return findings



# ---------------------------------------------------------------------------
# CA-U001: wording that permits skipping a confirmation or destroying something
# ---------------------------------------------------------------------------

# The vocabulary is matched in the language instruction files are written in, so the
# Japanese phrasings sit beside the English ones rather than being translated away.
_UNSAFE_PATTERNS = [
    ("skipped confirmation",
     re.compile(r"確認(?:なし|せず|を省略|不要|を飛ば)")),
    ("destructive operation",
     re.compile(r"rm\s+-rf|--force\b|--no-verify\b|force\s*push"
                r"|強制(?:削除|プッシュ|的に削除)")),
    ("unconditional permission",
     re.compile(r"無条件で|without confirmation|skip confirmation|auto-?approve"
                r"|bypass(?:ing)?\s+permission", re.IGNORECASE)),
]


def check_ca_u001(targets, ctx):
    findings = []
    for t in targets:
        excerpt = MEMORY_LINE_WITHHELD if _is_memory(t) else None
        for lineno, line in enumerate(t["content"].splitlines(), start=1):
            for label, pattern in _UNSAFE_PATTERNS:
                if not pattern.search(line):
                    continue
                findings.append(make_finding(
                    "CA-U001", "WARN", "REPORT_ONLY", f"{t['rel']}:{lineno}",
                    what=f"wording that permits a {label}: "
                         f"{excerpt if excerpt else line.strip()}",
                    why="permitting unconfirmed or destructive operations raises the "
                        "risk of an accident, so the intent behind it needs checking",
                    how="keep it where it is deliberate, otherwise state the "
                        "confirmation step the instruction leaves out"))
                break  # one line, one finding: the rest of the line says the same thing
    return findings



# ---------------------------------------------------------------------------
# CA-D001: one runtime's tool vocabulary in a file meant to hold none
# ---------------------------------------------------------------------------

_CLAUDE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit", "TodoWrite")
_TOOL_NAMES = "|".join(_CLAUDE_TOOLS)
_CLAUDE_TOOL_RE = re.compile(
    r"`(" + _TOOL_NAMES + r")`"
    r"|\b(" + _TOOL_NAMES + r")\s+tool\b"
    # The same phrase in Japanese, which the English form above does not cover.
    r"|\b(" + _TOOL_NAMES + r")\s*ツール"
)

# The files whose instructions are supposed to hold for any runtime. The file a
# specific runtime reads is left out: its own tool names belong there.
_TOOL_INDEPENDENT_KINDS = ("agents_md", "project_md")


def check_ca_d001(targets, ctx):
    findings = []
    for t in targets:
        if t["kind"] not in _TOOL_INDEPENDENT_KINDS:
            continue
        for lineno, line in enumerate(t["content"].splitlines(), start=1):
            match = _CLAUDE_TOOL_RE.search(line)
            if not match:
                continue
            tool = match.group(1) or match.group(2) or match.group(3)
            findings.append(make_finding(
                "CA-D001", "INFO", "REPORT_ONLY", f"{t['rel']}:{lineno}",
                what=f"tool vocabulary specific to one runtime `{tool}` in "
                     f"{t['rel']}, which is meant to hold for any of them",
                why="another runtime names its own tools differently, so an "
                    "instruction written around one runtime's tool does not carry",
                how="reword it in terms of the operation rather than one runtime's "
                    "tool name"))
    return findings



# ---------------------------------------------------------------------------
# CA-D002: a skill the instruction files never mention
# ---------------------------------------------------------------------------

def check_ca_d002(targets, ctx):
    known = ctx["skill_names"]
    if not known:
        return []
    instructions = "\n".join(
        t["content"] for t in targets if t["category"] == "instruction")
    findings = []
    for name in sorted(known):
        # A skill name may hold hyphens, so the boundary excludes them as well: without
        # that, 'planning' would count as a mention of a skill called 'plan'.
        mentioned = re.search(
            r"(?<![A-Za-z0-9-])" + re.escape(name) + r"(?![A-Za-z0-9-])", instructions)
        if mentioned:
            continue
        findings.append(make_finding(
            "CA-D002", "WARN", "NEEDS_JUDGMENT", "<instruction-files>:0",
            what=f"skill `{name}` is not recorded in the instruction files",
            why="a gap in the skill listing is instruction decay, though the "
                "omission may equally have been deliberate",
            how="add it to the listing, or ignore the finding where leaving it out "
                "was the intent"))
    return findings



# ---------------------------------------------------------------------------
# CA-C001: a prohibition and a permission over the same subject
# ---------------------------------------------------------------------------

# The polarity vocabulary is read in the languages instruction files are written in.
# English negates by turning a modal negative, and the negative form contains the
# affirmative one: 'must not' holds 'must', "shouldn't" holds 'should'. Matched first
# and taken out of the line, so the modal inside a negation is never read afterwards
# as the permission it would be on its own.
_NEGATED_MODAL_RE = re.compile(
    r"\b(?:must|should|shall|may|can|will)\s+not\b"
    r"|\b(?:must|should|shall|can|will|do|does|did)n['’]t\b"
    r"|\bcannot\b", re.IGNORECASE)
_PROHIBIT_RE = re.compile(
    r"するな|しない(?:こと)?|禁止|してはならない|べきでない"
    r"|never\b|don't\b|do not\b|avoid\b", re.IGNORECASE)
_ALLOW_RE = re.compile(
    r"してよい|してもよい|許可|するべき|すること(?:$|。)"
    r"|always\b|must\b|should\b|allowed\b", re.IGNORECASE)

_WORD_RE = re.compile(r"[a-z0-9]{2,}")
# A run of Japanese script, which is written without spaces between words.
_JAPANESE_RUN_RE = re.compile(r"[぀-ヿ一-鿿]+")
# Words that say which way a claim points rather than what it is about. Left in the
# subject they would make every prohibition share a subject with every permission.
_POLARITY_WORDS = {"する", "しない", "してよい", "するな", "こと", "must", "not",
                   "should", "never", "avoid", "always", "don", "allowed"}

_CANDIDATE_OVERLAP = 0.2


class Claim(NamedTuple):
    """One line asserting that something is or is not to be done."""

    rel: str
    line: int
    polarity: str
    subjects: frozenset[str]
    text: str
    from_memory: bool = False


_POLARITY_NOUN = {"prohibit": "prohibition", "allow": "permission"}


def _claim_excerpt(claim: Claim) -> str:
    """How one side of a candidate pair is put to the reader.

    Held back per claim rather than per finding: a pair may put a memory's line beside
    an instruction file's, and dropping both would cost the reading the one side it was
    free to see. The subjects are not offered in the withheld line's place either —
    they are cut from the line itself, so quoting them would hand over the same words
    the line was held back for.
    """
    body = MEMORY_LINE_WITHHELD if claim.from_memory else f"`{claim.text}`"
    return f"{_POLARITY_NOUN[claim.polarity]} {body}"


def _subjects_of(line: str) -> frozenset[str]:
    """What a line is about, as a set of words and Japanese character pairs.

    Japanese is written without spaces, so a run of it is cut into overlapping pairs
    rather than words. Two claims about one subject then share pairs even when neither
    the whole run nor its word boundaries agree.
    """
    words = set(_WORD_RE.findall(line.lower()))
    for run in _JAPANESE_RUN_RE.findall(line):
        for i in range(len(run) - 1):
            words.add(run[i:i + 2])
    return frozenset(w for w in words if w not in _POLARITY_WORDS)


def _polarity_of(line: str) -> str | None:
    """Which way a line points, or None when it points both ways or neither."""
    negated = bool(_NEGATED_MODAL_RE.search(line))
    remainder = _NEGATED_MODAL_RE.sub(" ", line)
    prohibits = negated or bool(_PROHIBIT_RE.search(remainder))
    allows = bool(_ALLOW_RE.search(remainder))
    if prohibits and not allows:
        return "prohibit"
    if allows and not prohibits:
        return "allow"
    return None


def index_claims_by_subject(claims: list[Claim]) -> dict[str, list[int]]:
    """Where each subject is claimed, so pairing can start from a shared subject."""
    grouped: dict[str, list[int]] = {}
    for position, claim in enumerate(claims):
        for subject in claim.subjects:
            grouped.setdefault(subject, []).append(position)
    return grouped


def candidate_pairs(claims: list[Claim]) -> set[tuple[int, int]]:
    """Opposing claim pairs, drawn only from claims that share a subject.

    Pairs are formed inside a subject group rather than over every pair of claims:
    an all-pairs sweep grows with the square of the number of claims, and almost all
    of those pairs are about unrelated things.
    """
    pairs: set[tuple[int, int]] = set()
    for positions in index_claims_by_subject(claims).values():
        for i in range(len(positions)):
            for j in range(i + 1, len(positions)):
                x, y = positions[i], positions[j]
                if claims[x].polarity != claims[y].polarity:
                    pairs.add((min(x, y), max(x, y)))
    return pairs


def _claims_in(targets) -> list[Claim]:
    claims = []
    for t in targets:
        from_memory = _is_memory(t)
        for lineno, line in enumerate(t["content"].splitlines(), start=1):
            if not line.strip():
                continue
            polarity = _polarity_of(line)
            if polarity is None:
                continue
            subjects = _subjects_of(line)
            if subjects:
                claims.append(Claim(t["rel"], lineno, polarity, subjects,
                                    line.strip(), from_memory))
    return claims


def check_ca_c001(targets, ctx):
    claims = _claims_in(targets)
    findings = []
    for x, y in sorted(candidate_pairs(claims)):
        first, second = claims[x], claims[y]
        union = first.subjects | second.subjects
        shared = len(first.subjects & second.subjects) / len(union) if union else 0.0
        # A generous cut on purpose. Whether a pair is a real contradiction is decided
        # downstream by a reader, so the only pairs dropped here are the ones with
        # almost nothing in common; a tighter cut would hide real conflicts that happen
        # to be worded differently.
        if shared < _CANDIDATE_OVERLAP:
            continue
        findings.append(make_finding(
            "CA-C001", "WARN", "REPORT_ONLY",
            f"{first.rel}:{first.line} vs {second.rel}:{second.line}",
            what=f"contradiction candidate, two claims pointing opposite ways over one "
                 f"subject (overlap {shared:.2f}): {_claim_excerpt(first)} vs "
                 f"{_claim_excerpt(second)}",
            why="opposing instructions over one subject make an agent's behaviour "
                "depend on which one it happens to read",
            how="classify the pair as a contradiction, a deliberate difference, an "
                "already-resolved precedence, or undecidable"))
    return findings



# ---------------------------------------------------------------------------
# CA-M001: the shape of a memory's frontmatter
# ---------------------------------------------------------------------------

# Kept here rather than shared with the other skills that parse frontmatter: a skill
# in this repository carries everything it runs on, and only the raw-line form below
# is needed, which the shared parsers do not all return.
_FRONTMATTER_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(.*)$")

_REQUIRED_MEMORY_KEYS = ("name", "description")
_KNOWN_MEMORY_TYPES = {"user", "feedback", "reference", "project", "session"}


def _frontmatter_lines(text: str) -> list[tuple[str, str, str]] | None:
    """Top-level entries as (key, value, the line as written), or None if there is none.

    The line as written is kept because normalising the formatting is the fix this rule
    offers, and the fix has to name the exact text it replaces.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for end, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            break
    else:
        return None  # no closing delimiter: there is no frontmatter block
    entries = []
    for line in lines[1:end]:
        match = _FRONTMATTER_KEY_RE.match(line)
        if match:
            entries.append((match.group(1), match.group(2).strip(), line))
    return entries


def _line_of(content: str, needle: str) -> int:
    for lineno, line in enumerate(content.splitlines(), start=1):
        if needle in line:
            return lineno
    return 1


def check_ca_m001(targets, ctx):
    findings = []
    for t in targets:
        if t["kind"] != "memory":
            continue
        entries = _frontmatter_lines(t["content"])
        if entries is None:
            continue
        present = {key for key, _, _ in entries}
        for required in _REQUIRED_MEMORY_KEYS:
            if required in present:
                continue
            findings.append(make_finding(
                "CA-M001", "WARN", "NEEDS_JUDGMENT", f"{t['rel']}:1",
                what=f"memory frontmatter carries no `{required}`",
                why="a memory is defined by its name and its description, so a "
                    "missing one leaves the definition incomplete",
                how=f"supply `{required}`, or exclude the file when it is not a memory"))
        for key, value, raw in entries:
            if key == "type" and value and value not in _KNOWN_MEMORY_TYPES:
                findings.append(make_finding(
                    "CA-M001", "WARN", "NEEDS_JUDGMENT",
                    f"{t['rel']}:{_line_of(t['content'], raw)}",
                    what=f"unknown memory type `{value}`",
                    why="the type follows the runtime's own convention, so a value "
                        "outside it may mean the runtime has moved on",
                    how="correct it to a known type, or accept it where the runtime "
                        "has genuinely gained one (judge conservatively)"))
            canonical = f"{key}: {value}" if value != "" else f"{key}:"
            if raw == canonical or raw.rstrip() == canonical:
                continue
            findings.append(make_finding(
                "CA-M001", "WARN", "AUTO_FIX",
                f"{t['rel']}:{_line_of(t['content'], raw)}",
                what=f"frontmatter entry is not in canonical form: `{raw}`",
                why="drift in how keys are written hinders both reading and "
                    "machine processing",
                how=f"rewrite `{raw}` as `{canonical}`, leaving the body untouched",
                fix_action={"path": t["path"], "old": raw, "new": canonical}))
    return findings



# ---------------------------------------------------------------------------
# CA-M101: a path a memory names that is not there
# ---------------------------------------------------------------------------

def check_ca_m101(targets, ctx):
    findings = []
    root = ctx["root"]
    for t in targets:
        if t["kind"] != "memory":
            continue
        for ref, lineno, _written_as in _extract_path_refs(t["content"]):
            if _ref_exists(root, ref):
                continue
            findings.append(make_finding(
                "CA-M101", "WARN", "NEEDS_JUDGMENT", f"{t['rel']}:{lineno}",
                what=f"memory names a path that does not exist `{ref}`",
                why="a memory carrying a stale reference is trusted as much as the "
                    "rest of it, so the stale part spreads",
                how="update the reference, or revisit the memory that holds it"))
    return findings



# ---------------------------------------------------------------------------
# CA-M301: a memory line suspected of holding a credential or personal data
# ---------------------------------------------------------------------------

# An address and a home path identify a person rather than granting access, so a line
# holding one is not treated as gravely as a leaked credential. Without the split every
# memory that legitimately notes where a file lives would report at the top severity.
_PERSONAL_DATA_KINDS = {"email", "home_path"}

_SECRET_HOW = ("read the line and remove the value, or move it behind the "
               "environment; it is deliberately not masked in place, because masking "
               "a live credential hides the leak without revoking it")


def check_ca_m301(targets, ctx):
    findings = []
    for t in targets:
        if t["kind"] != "memory":
            continue
        for lineno, line in enumerate(t["content"].splitlines(), start=1):
            kinds = sorted({hit["type"] for hit in secret_detect.detect_secrets(line)})
            if not kinds:
                continue
            holds_credential = any(k not in _PERSONAL_DATA_KINDS for k in kinds)
            severity, subject, why = (
                ("BLOCK", "a credential",
                 "a credential inside a memory travels wherever the memory does; "
                 "the value itself is not transcribed here")
                if holds_credential else
                ("WARN", "personal data",
                 "personal data inside a memory leaks when the memory is shared; "
                 "the value itself is not transcribed here"))
            findings.append(make_finding(
                "CA-M301", severity, "REPORT_ONLY", f"{t['rel']}:{lineno}",
                what=f"pattern suspected of holding {subject}: {', '.join(kinds)}",
                why=why, how=_SECRET_HOW))
    return findings


# ---------------------------------------------------------------------------
# Registry (dispatch by listing, not by editing the dispatcher)
# ---------------------------------------------------------------------------

RULES: dict[str, dict[str, Any]] = {
    "CA-S001": {"category": "stale", "severity": "WARN",
                "action": "AUTO_FIX / NEEDS_JUDGMENT", "fn": check_ca_s001},
    "CA-S002": {"category": "stale", "severity": "WARN",
                "action": "NEEDS_JUDGMENT", "fn": check_ca_s002},
    "CA-U001": {"category": "unsafe", "severity": "WARN",
                "action": "REPORT_ONLY", "fn": check_ca_u001},
    "CA-D001": {"category": "drift", "severity": "INFO",
                "action": "REPORT_ONLY", "fn": check_ca_d001},
    "CA-D002": {"category": "drift", "severity": "WARN",
                "action": "NEEDS_JUDGMENT", "fn": check_ca_d002},
    "CA-C001": {"category": "contradiction", "severity": "WARN",
                "action": "REPORT_ONLY", "fn": check_ca_c001},
    "CA-M001": {"category": "memory", "severity": "WARN",
                "action": "AUTO_FIX / NEEDS_JUDGMENT", "fn": check_ca_m001},
    "CA-M101": {"category": "memory", "severity": "WARN",
                "action": "NEEDS_JUDGMENT", "fn": check_ca_m101},
    "CA-M301": {"category": "memory", "severity": "BLOCK / WARN",
                "action": "REPORT_ONLY", "fn": check_ca_m301},
}


def run_checks(targets: list[dict], ctx: dict, rules: dict | None = None) -> list[dict]:
    """Run every listed rule in identifier order and mask what they report."""
    listed = RULES if rules is None else rules
    findings: list[dict] = []
    for rule_id in sorted(listed):
        findings.extend(listed[rule_id]["fn"](targets, ctx))
    return finalize_findings(findings)


def build_context(root: str, targets: list[dict]) -> dict:
    root = os.path.abspath(root)
    skill_names = set()
    skills_dir = os.path.join(root, "skills")
    if os.path.isdir(skills_dir):
        skill_names = {
            name for name in os.listdir(skills_dir)
            if os.path.isdir(os.path.join(skills_dir, name)) and name != "shared"
        }
    return {"root": root, "skill_names": skill_names}


def _attach_content(targets: list[dict]) -> list[dict]:
    attached = []
    for target in targets:
        content = target.get("content")
        if content is None:
            try:
                with open(target["path"], encoding="utf-8", errors="replace") as handle:
                    content = handle.read()
            except OSError:
                continue
        attached.append({**target, "content": content})
    return attached


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the context-audit static checks")
    parser.add_argument("targets_json", help="collect_targets.py output (path or '-')")
    parser.add_argument("--root", default=".", help="Project root")
    parser.add_argument("--output", default=None, help="Output file (default stdout)")
    args = parser.parse_args(argv)

    raw = sys.stdin.read() if args.targets_json == "-" \
        else Path(args.targets_json).read_text(encoding="utf-8")
    data = json.loads(raw)
    targets = _attach_content(data["targets"] if isinstance(data, dict) else data)
    ctx = build_context(args.root, targets)
    findings = run_checks(targets, ctx)

    rendered = json.dumps(
        # The rules that ran travel with the findings because the report has to say
        # which checks a clean result came out of; a count of zero on its own cannot be
        # told from a check that never happened.
        {"finding_count": len(findings), "rules_run": sorted(RULES),
         "findings": findings},
        indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
