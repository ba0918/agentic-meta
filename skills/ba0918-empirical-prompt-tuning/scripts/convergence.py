"""Pure functions for empirical-prompt-tuning convergence logic.

All judgment calls (converged / diverged / halt / bloat) are made here,
not by the LLM tuner.  Each function is deterministic and unit-tested.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter

# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------

FRICTION_CATEGORIES = frozenset({
    "ambiguous_term",
    "missing_premise",
    "contradictory",
    "over_specified",
    "rationalization_hook",
    "self_containment_gap",
})

# Protocol failures are checker/harness-side deviations, NOT candidate failures.
# They mean the current iteration is unevaluable and must halt safely instead of
# being recorded as a fail against the candidate prompt.
PROTOCOL_FAILURE_TYPES = frozenset({
    "malformed_output",        # checker output not parseable / schema-invalid
    "missing_grade",           # checker did not grade every requirement
    "extra_grade",             # checker returned grades for non-existent requirements
    "duplicate_grade",         # same requirement graded multiple times
    "invalid_result_value",    # result not in {pass, fail, partial}
    "empty_checklist",         # caller passed a zero-length checklist (fixture load bug)
    "missing_evidence",        # a grade carries no non-empty evidence line
    "missing_isolation_note",  # integration fixture output omits the isolation_note key
    "isolation_violation",     # checker inspected sources beyond the artifact
    "input_range_violation",   # candidate given only a subset of a multi-artifact fixture
})

# ---------------------------------------------------------------------------
# Convergence
# ---------------------------------------------------------------------------

def is_converged(
    history: list[dict],
    *,
    window: int = 2,
    precision_delta_eps: float = 0.03,
    steps_tolerance_pct: float = 0.10,
    duration_tolerance_pct: float = 0.15,
) -> bool:
    if len(history) < window + 1:
        return False
    tail = history[-(window + 1):]
    for rec in tail[-window:]:
        if _has_friction(rec):
            return False
    for i in range(1, len(tail)):
        prev, cur = tail[i - 1], tail[i]
        if not _metrics_saturated(prev, cur, precision_delta_eps,
                                  steps_tolerance_pct, duration_tolerance_pct):
            return False
    return True


def _has_friction(rec: dict) -> bool:
    for sc in rec.get("scenarios", []):
        if sc.get("friction"):
            return True
    return False


def _metrics_saturated(
    prev: dict, cur: dict,
    precision_eps: float, steps_pct: float, duration_pct: float,
) -> bool:
    for sp, sc in zip(prev.get("scenarios", []), cur.get("scenarios", [])):
        if abs(sc.get("precision", 0) - sp.get("precision", 0)) > precision_eps:
            return False
        prev_steps = sp.get("steps", 1) or 1
        if abs(sc.get("steps", 0) - prev_steps) / prev_steps > steps_pct:
            return False
        prev_dur = sp.get("duration_ms", 1) or 1
        if abs(sc.get("duration_ms", 0) - prev_dur) / prev_dur > duration_pct:
            return False
    return True


# ---------------------------------------------------------------------------
# Divergence
# ---------------------------------------------------------------------------

def is_diverged(history: list[dict], threshold: int = 3) -> bool:
    if len(history) < threshold:
        return False
    tail = history[-threshold:]
    category_sets = []
    for rec in tail:
        cats: set[str] = set()
        for sc in rec.get("scenarios", []):
            for f in sc.get("friction", []):
                cats.add(f.get("category", "uncategorized"))
        category_sets.append(cats)
    if not category_sets or not category_sets[0]:
        return False
    common = category_sets[0]
    for cs in category_sets[1:]:
        common = common & cs
    return len(common) > 0


# ---------------------------------------------------------------------------
# Checklist integrity (hash-lock)
# ---------------------------------------------------------------------------

def verify_checklist_integrity(checklist: list[dict], locked_sha256: str) -> bool:
    current = hashlib.sha256(
        json.dumps(checklist, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return current == locked_sha256


# ---------------------------------------------------------------------------
# Bloat detection
# ---------------------------------------------------------------------------

def detect_bloat(history: list[dict], max_growth_pct: float = 20.0) -> bool:
    if len(history) < 2:
        return False
    prev_bytes = history[-2].get("prompt_bytes", 0) or 1
    cur_bytes = history[-1].get("prompt_bytes", 0)
    growth = (cur_bytes - prev_bytes) / prev_bytes * 100
    return growth > max_growth_pct


# ---------------------------------------------------------------------------
# Instruction fingerprint
# ---------------------------------------------------------------------------

def compute_instruction_fingerprint(file_contents: dict[str, str]) -> str:
    h = hashlib.sha256()
    for path in sorted(file_contents.keys()):
        h.update(path.encode())
        h.update(b"\x00")
        h.update(file_contents[path].encode())
        h.update(b"\x00")
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Friction classification
# ---------------------------------------------------------------------------

def classify_friction(raw_points: list[dict]) -> list[dict]:
    result = []
    for pt in raw_points:
        cat = pt.get("category", "")
        if cat not in FRICTION_CATEGORIES:
            cat = "uncategorized"
        result.append({**pt, "category": cat})
    return result


# ---------------------------------------------------------------------------
# Checker protocol validation
# ---------------------------------------------------------------------------

_VALID_RESULT_VALUES = frozenset({"pass", "fail", "partial"})


def validate_input_range(
    dispatch_keys,
    input_range_required,
) -> tuple[bool, str | None]:
    """Pre-dispatch guard: are all declared input_range keys actually being sent?

    Called by the harness immediately *before* dispatching the checker, with
    the artifact keys it is about to hand over. Returns
    (ok, protocol_failure_type) — the same 2-tuple contract as
    validate_checker_output() so both guards are consumed identically.

    An empty / absent `input_range_required` means the fixture declares no
    multi-artifact requirement (`fixture_kind: "unit"`) and always passes.
    Extra keys beyond the declared set are NOT a violation: only missing
    ones are, because a checker given less than the fixture declares cannot
    reproduce the grading. Callers that want the offending keys for
    `harness_error.detail` compute them as
    `set(input_range_required) - set(dispatch_keys)`.
    """
    if not input_range_required:
        return True, None
    if set(input_range_required) - set(dispatch_keys):
        return False, "input_range_violation"
    return True, None


def _validate_isolation_note(parsed: dict) -> tuple[bool, str | None]:
    """Post-dispatch isolation check for integration fixtures.

    Contract (checker-protocol.md): the key must be present. `null` means
    "no out-of-range source was opened"; any non-empty string is the
    checker's own admission that it read beyond the artifact set.
    """
    if "isolation_note" not in parsed:
        return False, "missing_isolation_note"
    note = parsed["isolation_note"]
    if note is None:
        return True, None
    if not isinstance(note, str):
        return False, "malformed_output"
    if note.strip():
        return False, "isolation_violation"
    return True, None


def validate_checker_output(
    raw_output,
    checklist: list[dict],
    *,
    fixture_kind: str | None = None,
) -> tuple[bool, str | None]:
    """Validate a checker's raw output against the iteration-schema contract.

    Returns (ok, protocol_failure_type). When ok is False the caller MUST
    treat this iteration as unevaluable — the returned protocol_failure_type
    is a member of PROTOCOL_FAILURE_TYPES.

    This isolates checker/harness-side deviations from candidate failures
    so that a malformed checker never counts as a fail against the prompt.

    `fixture_kind` takes only the one field the isolation rule needs rather
    than the whole fixture record, so a caller never has to reshape fixture
    metadata to call this. Pass "integration" to additionally require an
    explicit `isolation_note`; the default (None) keeps unit-fixture
    behaviour unchanged.

    Check order is structural-first: parse, then the integration isolation
    contract, then per-grade shape, then coverage, and only finally
    evidence. A structurally broken output therefore reports the structural
    failure rather than the evidence symptom it also exhibits.
    """
    if not checklist:
        # zero-length checklist would make an empty grades list trivially
        # "complete" — surface as protocol failure instead of silent pass.
        return False, "empty_checklist"

    if isinstance(raw_output, str):
        try:
            parsed = json.loads(raw_output)
        except (ValueError, TypeError):
            return False, "malformed_output"
    elif isinstance(raw_output, dict):
        parsed = raw_output
    else:
        return False, "malformed_output"

    grades = parsed.get("grades") if isinstance(parsed, dict) else None
    if not isinstance(grades, list):
        return False, "malformed_output"

    if fixture_kind == "integration":
        ok, failure = _validate_isolation_note(parsed)
        if not ok:
            return False, failure

    expected_indices = set(range(len(checklist)))
    seen_indices: set[int] = set()

    for g in grades:
        if not isinstance(g, dict):
            return False, "malformed_output"
        idx = g.get("requirement_index")
        result = g.get("result")
        if not isinstance(idx, int):
            return False, "malformed_output"
        if idx not in expected_indices:
            return False, "extra_grade"
        if idx in seen_indices:
            return False, "duplicate_grade"
        if result not in _VALID_RESULT_VALUES:
            return False, "invalid_result_value"
        seen_indices.add(idx)

    if seen_indices != expected_indices:
        return False, "missing_grade"

    # Evidence last: only meaningful once the grade set is structurally sound.
    for g in grades:
        evidence = g.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            return False, "missing_evidence"

    return True, None


def has_protocol_failure(iteration_record: dict) -> bool:
    """True if any scenario in the record carries a harness_error whose
    type is a known protocol failure. Candidate `success=False` does NOT
    count — a protocol failure is strictly a checker/harness-side defect.
    """
    for sc in iteration_record.get("scenarios", []):
        err = sc.get("harness_error")
        if isinstance(err, dict) and err.get("type") in PROTOCOL_FAILURE_TYPES:
            return True
    return False


# ---------------------------------------------------------------------------
# Exit verdict
# ---------------------------------------------------------------------------

def resolve_exit_verdict(
    history: list[dict],
    *,
    max_iter: int = 10,
    elapsed_s: float = 0.0,
    max_wallclock: float = 3600.0,
    kill_file_exists: bool = False,
    checklist_tampered: bool = False,
) -> str:
    if (
        kill_file_exists
        or checklist_tampered
        or len(history) >= max_iter
        or elapsed_s >= max_wallclock
    ):
        return "halt"
    if history and has_protocol_failure(history[-1]):
        return "halt"
    if is_diverged(history):
        return "diverged"
    if detect_bloat(history):
        return "bloat_advisory"
    if is_converged(history):
        return "converged"
    return "continue"


def resolve_halt_reason(
    history: list[dict],
    *,
    max_iter: int = 10,
    elapsed_s: float = 0.0,
    max_wallclock: float = 3600.0,
    kill_file_exists: bool = False,
    checklist_tampered: bool = False,
) -> str | None:
    """Return the halt_reason to record when exit_verdict == 'halt', or None
    when the verdict is not halt. Priority mirrors resolve_exit_verdict so
    the reason and the verdict never disagree — callers pass the same kwargs
    to both.
    """
    if kill_file_exists:
        return "kill_file"
    if checklist_tampered:
        return "checklist_tampered"
    if len(history) >= max_iter:
        return "max_iter"
    if elapsed_s >= max_wallclock:
        return "max_wallclock"
    if history and has_protocol_failure(history[-1]):
        return "checker_protocol_failure"
    return None
