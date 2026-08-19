"""Tests for convergence.py — empirical-prompt-tuning pure functions."""

import hashlib
import json
import unittest

from convergence import (
    PROTOCOL_FAILURE_TYPES,
    classify_friction,
    compute_instruction_fingerprint,
    detect_bloat,
    has_protocol_failure,
    is_converged,
    is_diverged,
    resolve_exit_verdict,
    resolve_halt_reason,
    validate_checker_output,
    validate_input_range,
    verify_checklist_integrity,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_iter(iteration, precision=0.9, steps=4, duration_ms=20000,
               friction=None, prompt_bytes=1000):
    return {
        "iteration": iteration,
        "prompt_bytes": prompt_bytes,
        "scenarios": [
            {
                "id": "A",
                "success": True,
                "precision": precision,
                "steps": steps,
                "duration_ms": duration_ms,
                "retries": 0,
                "friction": friction or [],
            }
        ],
    }


def _checklist_hash(checklist):
    return hashlib.sha256(
        json.dumps(checklist, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


# ===========================================================================
# is_converged
# ===========================================================================

class TestIsConverged(unittest.TestCase):

    def test_converged_after_two_clear_iterations(self):
        h = [
            _make_iter(1, precision=0.87, friction=[{"category": "ambiguous_term"}]),
            _make_iter(2, precision=0.88),
            _make_iter(3, precision=0.89),
        ]
        self.assertTrue(is_converged(h, window=2))

    def test_not_converged_with_friction_in_last(self):
        h = [
            _make_iter(1, precision=0.85),
            _make_iter(2, precision=0.88),
            _make_iter(3, precision=0.89,
                       friction=[{"category": "missing_premise"}]),
        ]
        self.assertFalse(is_converged(h, window=2))

    def test_not_converged_with_large_precision_jump(self):
        h = [
            _make_iter(1, precision=0.50),
            _make_iter(2, precision=0.85),
            _make_iter(3, precision=0.95),
        ]
        self.assertFalse(is_converged(h, window=2))

    def test_not_converged_insufficient_history(self):
        h = [_make_iter(1, precision=0.90)]
        self.assertFalse(is_converged(h, window=2))

    def test_converged_with_custom_eps(self):
        h = [
            _make_iter(1, precision=0.84),
            _make_iter(2, precision=0.85),
            _make_iter(3, precision=0.86),
        ]
        self.assertFalse(is_converged(h, window=2, precision_delta_eps=0.005))
        self.assertTrue(is_converged(h, window=2, precision_delta_eps=0.02))

    def test_steps_variance_prevents_convergence(self):
        h = [
            _make_iter(1, steps=10),
            _make_iter(2, steps=10),
            _make_iter(3, steps=15),  # +50%
        ]
        self.assertFalse(is_converged(h, window=2))


# ===========================================================================
# is_diverged
# ===========================================================================

class TestIsDiverged(unittest.TestCase):

    def test_diverged_same_category_persists(self):
        friction = [{"category": "ambiguous_term"}]
        h = [
            _make_iter(1, friction=friction),
            _make_iter(2, friction=friction),
            _make_iter(3, friction=friction),
        ]
        self.assertTrue(is_diverged(h, threshold=3))

    def test_not_diverged_when_friction_clears(self):
        h = [
            _make_iter(1, friction=[{"category": "ambiguous_term"}]),
            _make_iter(2, friction=[{"category": "ambiguous_term"}]),
            _make_iter(3),
        ]
        self.assertFalse(is_diverged(h, threshold=3))

    def test_not_diverged_insufficient_history(self):
        friction = [{"category": "ambiguous_term"}]
        h = [_make_iter(1, friction=friction), _make_iter(2, friction=friction)]
        self.assertFalse(is_diverged(h, threshold=3))

    def test_diverged_different_categories_not_counted(self):
        h = [
            _make_iter(1, friction=[{"category": "ambiguous_term"}]),
            _make_iter(2, friction=[{"category": "missing_premise"}]),
            _make_iter(3, friction=[{"category": "contradictory"}]),
        ]
        self.assertFalse(is_diverged(h, threshold=3))


# ===========================================================================
# verify_checklist_integrity
# ===========================================================================

class TestVerifyChecklistIntegrity(unittest.TestCase):

    def test_integrity_ok(self):
        cl = [{"text": "does X", "critical": True}]
        h = _checklist_hash(cl)
        self.assertTrue(verify_checklist_integrity(cl, h))

    def test_integrity_tampered(self):
        cl = [{"text": "does X", "critical": True}]
        h = _checklist_hash(cl)
        cl[0]["critical"] = False
        self.assertFalse(verify_checklist_integrity(cl, h))

    def test_integrity_order_independent(self):
        cl = [
            {"text": "A", "critical": True},
            {"text": "B", "critical": False},
        ]
        h = _checklist_hash(cl)
        self.assertTrue(verify_checklist_integrity(cl, h))


# ===========================================================================
# detect_bloat
# ===========================================================================

class TestDetectBloat(unittest.TestCase):

    def test_no_bloat(self):
        h = [_make_iter(1, prompt_bytes=1000), _make_iter(2, prompt_bytes=1050)]
        self.assertFalse(detect_bloat(h, max_growth_pct=20.0))

    def test_bloat_detected(self):
        h = [_make_iter(1, prompt_bytes=1000), _make_iter(2, prompt_bytes=1300)]
        self.assertTrue(detect_bloat(h, max_growth_pct=20.0))

    def test_single_iteration_no_bloat(self):
        h = [_make_iter(1, prompt_bytes=5000)]
        self.assertFalse(detect_bloat(h))

    def test_shrink_is_not_bloat(self):
        h = [_make_iter(1, prompt_bytes=2000), _make_iter(2, prompt_bytes=1500)]
        self.assertFalse(detect_bloat(h))


# ===========================================================================
# compute_instruction_fingerprint
# ===========================================================================

class TestComputeInstructionFingerprint(unittest.TestCase):

    def test_same_content_same_hash(self):
        fp1 = compute_instruction_fingerprint({"a.md": "hello"})
        fp2 = compute_instruction_fingerprint({"a.md": "hello"})
        self.assertEqual(fp1, fp2)

    def test_different_content_different_hash(self):
        fp1 = compute_instruction_fingerprint({"a.md": "hello"})
        fp2 = compute_instruction_fingerprint({"a.md": "world"})
        self.assertNotEqual(fp1, fp2)

    def test_order_independent(self):
        fp1 = compute_instruction_fingerprint({"a.md": "x", "b.md": "y"})
        fp2 = compute_instruction_fingerprint({"b.md": "y", "a.md": "x"})
        self.assertEqual(fp1, fp2)


# ===========================================================================
# classify_friction
# ===========================================================================

VALID_CATEGORIES = {
    "ambiguous_term", "missing_premise", "contradictory",
    "over_specified", "rationalization_hook", "self_containment_gap",
}

class TestClassifyFriction(unittest.TestCase):

    def test_valid_category_passes_through(self):
        raw = [{"category": "ambiguous_term", "detail": "x"}]
        result = classify_friction(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["category"], "ambiguous_term")

    def test_invalid_category_becomes_uncategorized(self):
        raw = [{"category": "totally_made_up", "detail": "x"}]
        result = classify_friction(raw)
        self.assertEqual(result[0]["category"], "uncategorized")

    def test_missing_category_becomes_uncategorized(self):
        raw = [{"detail": "something unclear"}]
        result = classify_friction(raw)
        self.assertEqual(result[0]["category"], "uncategorized")

    def test_empty_list(self):
        self.assertEqual(classify_friction([]), [])


# ===========================================================================
# resolve_exit_verdict
# ===========================================================================

class TestResolveExitVerdict(unittest.TestCase):

    def test_halt_on_max_iter(self):
        h = [_make_iter(i) for i in range(1, 11)]
        v = resolve_exit_verdict(h, max_iter=10)
        self.assertEqual(v, "halt")

    def test_halt_on_kill_file(self):
        h = [_make_iter(1)]
        v = resolve_exit_verdict(h, kill_file_exists=True)
        self.assertEqual(v, "halt")

    def test_halt_on_wallclock(self):
        h = [_make_iter(1)]
        v = resolve_exit_verdict(h, elapsed_s=4000.0, max_wallclock=3600.0)
        self.assertEqual(v, "halt")

    def test_diverged_takes_priority_over_converged(self):
        friction = [{"category": "ambiguous_term"}]
        h = [_make_iter(i, friction=friction) for i in range(1, 5)]
        v = resolve_exit_verdict(h, max_iter=100)
        self.assertEqual(v, "diverged")

    def test_converged(self):
        h = [
            _make_iter(1, precision=0.88, friction=[{"category": "ambiguous_term"}]),
            _make_iter(2, precision=0.90),
            _make_iter(3, precision=0.91),
        ]
        v = resolve_exit_verdict(h, max_iter=100)
        self.assertEqual(v, "converged")

    def test_continue_when_nothing_triggered(self):
        h = [
            _make_iter(1, friction=[{"category": "ambiguous_term"}]),
            _make_iter(2),
        ]
        v = resolve_exit_verdict(h, max_iter=100)
        self.assertEqual(v, "continue")

    def test_halt_priority_over_diverged(self):
        friction = [{"category": "ambiguous_term"}]
        h = [_make_iter(i, friction=friction) for i in range(1, 11)]
        v = resolve_exit_verdict(h, max_iter=10)
        self.assertEqual(v, "halt")

    def test_bloat_advisory_returned(self):
        h = [_make_iter(1, prompt_bytes=1000), _make_iter(2, prompt_bytes=1500)]
        v = resolve_exit_verdict(h, max_iter=100)
        self.assertEqual(v, "bloat_advisory")


# ===========================================================================
# validate_checker_output
# ===========================================================================

CHECKLIST_TWO = [
    {"text": "req0", "critical": True},
    {"text": "req1", "critical": False},
]


class TestValidateCheckerOutput(unittest.TestCase):

    def test_valid_json_string(self):
        raw = json.dumps({
            "grades": [
                {"requirement_index": 0, "result": "pass", "evidence": "e0"},
                {"requirement_index": 1, "result": "fail", "evidence": "e1"},
            ]
        })
        ok, failure = validate_checker_output(raw, CHECKLIST_TWO)
        self.assertTrue(ok)
        self.assertIsNone(failure)

    def test_valid_dict(self):
        raw = {
            "grades": [
                {"requirement_index": 0, "result": "partial", "evidence": "e0"},
                {"requirement_index": 1, "result": "pass", "evidence": "e1"},
            ]
        }
        ok, failure = validate_checker_output(raw, CHECKLIST_TWO)
        self.assertTrue(ok)

    def test_malformed_string_returns_malformed(self):
        ok, failure = validate_checker_output("{not json", CHECKLIST_TWO)
        self.assertFalse(ok)
        self.assertEqual(failure, "malformed_output")

    def test_none_input_is_malformed(self):
        ok, failure = validate_checker_output(None, CHECKLIST_TWO)
        self.assertFalse(ok)
        self.assertEqual(failure, "malformed_output")

    def test_missing_grades_key_is_malformed(self):
        ok, failure = validate_checker_output({"result": "pass"}, CHECKLIST_TWO)
        self.assertFalse(ok)
        self.assertEqual(failure, "malformed_output")

    def test_missing_grade_for_a_requirement(self):
        raw = {"grades": [{"requirement_index": 0, "result": "pass"}]}
        ok, failure = validate_checker_output(raw, CHECKLIST_TWO)
        self.assertFalse(ok)
        self.assertEqual(failure, "missing_grade")

    def test_extra_grade_beyond_checklist(self):
        raw = {"grades": [
            {"requirement_index": 0, "result": "pass"},
            {"requirement_index": 1, "result": "pass"},
            {"requirement_index": 7, "result": "pass"},
        ]}
        ok, failure = validate_checker_output(raw, CHECKLIST_TWO)
        self.assertFalse(ok)
        self.assertEqual(failure, "extra_grade")

    def test_invalid_result_value(self):
        raw = {"grades": [
            {"requirement_index": 0, "result": "MAYBE"},
            {"requirement_index": 1, "result": "pass"},
        ]}
        ok, failure = validate_checker_output(raw, CHECKLIST_TWO)
        self.assertFalse(ok)
        self.assertEqual(failure, "invalid_result_value")

    def test_non_int_requirement_index_is_malformed(self):
        raw = {"grades": [
            {"requirement_index": "0", "result": "pass"},
            {"requirement_index": 1, "result": "pass"},
        ]}
        ok, failure = validate_checker_output(raw, CHECKLIST_TWO)
        self.assertFalse(ok)
        self.assertEqual(failure, "malformed_output")

    def test_all_failure_types_are_registered(self):
        # every failure type validate_checker_output can emit must be in the
        # public taxonomy so downstream code can enumerate them.
        emitted = {"malformed_output", "missing_grade",
                   "extra_grade", "duplicate_grade",
                   "invalid_result_value", "empty_checklist",
                   "missing_evidence", "missing_isolation_note",
                   "isolation_violation"}
        self.assertTrue(emitted.issubset(PROTOCOL_FAILURE_TYPES))

    def test_duplicate_requirement_index(self):
        raw = {"grades": [
            {"requirement_index": 0, "result": "pass"},
            {"requirement_index": 0, "result": "fail"},
            {"requirement_index": 1, "result": "pass"},
        ]}
        ok, failure = validate_checker_output(raw, CHECKLIST_TWO)
        self.assertFalse(ok)
        self.assertEqual(failure, "duplicate_grade")

    def test_duplicate_index_on_single_item_checklist(self):
        # regression: on a 1-item checklist, seen_indices == expected even
        # with a duplicate, so the missing_grade branch would silently pass.
        raw = {"grades": [
            {"requirement_index": 0, "result": "pass"},
            {"requirement_index": 0, "result": "fail"},
        ]}
        ok, failure = validate_checker_output(raw, [{"text": "x", "critical": True}])
        self.assertFalse(ok)
        self.assertEqual(failure, "duplicate_grade")

    def test_empty_checklist_is_rejected(self):
        ok, failure = validate_checker_output({"grades": []}, [])
        self.assertFalse(ok)
        self.assertEqual(failure, "empty_checklist")


# ===========================================================================
# evidence enforcement
# ===========================================================================

class TestEvidenceValidation(unittest.TestCase):

    def _grades(self, ev0, ev1):
        return {"grades": [
            {"requirement_index": 0, "result": "pass", "evidence": ev0},
            {"requirement_index": 1, "result": "fail", "evidence": ev1},
        ]}

    def test_absent_evidence_key_is_missing_evidence(self):
        raw = {"grades": [
            {"requirement_index": 0, "result": "pass", "evidence": "e0"},
            {"requirement_index": 1, "result": "fail"},
        ]}
        ok, failure = validate_checker_output(raw, CHECKLIST_TWO)
        self.assertFalse(ok)
        self.assertEqual(failure, "missing_evidence")

    def test_empty_evidence_is_missing_evidence(self):
        ok, failure = validate_checker_output(self._grades("e0", ""), CHECKLIST_TWO)
        self.assertFalse(ok)
        self.assertEqual(failure, "missing_evidence")

    def test_whitespace_only_evidence_is_missing_evidence(self):
        ok, failure = validate_checker_output(self._grades("  \n ", "e1"), CHECKLIST_TWO)
        self.assertFalse(ok)
        self.assertEqual(failure, "missing_evidence")

    def test_non_string_evidence_is_missing_evidence(self):
        ok, failure = validate_checker_output(self._grades("e0", 42), CHECKLIST_TWO)
        self.assertFalse(ok)
        self.assertEqual(failure, "missing_evidence")

    def test_structural_failure_outranks_missing_evidence(self):
        # a grade set that is BOTH incomplete and evidence-less reports the
        # structural cause — the implementer fixes coverage, not evidence.
        raw = {"grades": [{"requirement_index": 0, "result": "pass"}]}
        ok, failure = validate_checker_output(raw, CHECKLIST_TWO)
        self.assertEqual(failure, "missing_grade")


# ===========================================================================
# isolation_note (integration fixtures)
# ===========================================================================

VALID_GRADES = {
    "grades": [
        {"requirement_index": 0, "result": "pass", "evidence": "e0"},
        {"requirement_index": 1, "result": "fail", "evidence": "e1"},
    ]
}


class TestIsolationNote(unittest.TestCase):

    def _with_note(self, note):
        return {**VALID_GRADES, "isolation_note": note}

    def test_unit_fixture_does_not_require_isolation_note(self):
        ok, failure = validate_checker_output(VALID_GRADES, CHECKLIST_TWO)
        self.assertTrue(ok)
        self.assertIsNone(failure)

    def test_default_fixture_kind_keeps_legacy_behaviour(self):
        # no fixture_kind passed == pre-existing callers, unchanged
        ok, _ = validate_checker_output(
            self._with_note("read the repo tree"), CHECKLIST_TWO)
        self.assertTrue(ok)

    def test_integration_fixture_requires_the_key(self):
        ok, failure = validate_checker_output(
            VALID_GRADES, CHECKLIST_TWO, fixture_kind="integration")
        self.assertFalse(ok)
        self.assertEqual(failure, "missing_isolation_note")

    def test_integration_null_note_is_clean(self):
        ok, failure = validate_checker_output(
            self._with_note(None), CHECKLIST_TWO, fixture_kind="integration")
        self.assertTrue(ok)
        self.assertIsNone(failure)

    def test_self_reported_note_is_isolation_violation(self):
        ok, failure = validate_checker_output(
            self._with_note("also opened skills/plan/SKILL.md"),
            CHECKLIST_TWO, fixture_kind="integration")
        self.assertFalse(ok)
        self.assertEqual(failure, "isolation_violation")

    def test_blank_note_is_treated_as_no_violation(self):
        ok, failure = validate_checker_output(
            self._with_note("   "), CHECKLIST_TWO, fixture_kind="integration")
        self.assertTrue(ok)

    def test_non_string_note_is_malformed(self):
        ok, failure = validate_checker_output(
            self._with_note(["a"]), CHECKLIST_TWO, fixture_kind="integration")
        self.assertFalse(ok)
        self.assertEqual(failure, "malformed_output")

    def test_isolation_outranks_evidence(self):
        # a contaminated checker's grades are worthless regardless of evidence
        raw = {
            "grades": [
                {"requirement_index": 0, "result": "pass", "evidence": "e0"},
                {"requirement_index": 1, "result": "fail"},
            ],
            "isolation_note": "opened the source tree",
        }
        ok, failure = validate_checker_output(
            raw, CHECKLIST_TWO, fixture_kind="integration")
        self.assertEqual(failure, "isolation_violation")


# ===========================================================================
# validate_input_range
# ===========================================================================

class TestValidateInputRange(unittest.TestCase):

    def test_all_required_keys_present(self):
        ok, failure = validate_input_range(
            {"consumer", "reference"}, ["consumer", "reference"])
        self.assertTrue(ok)
        self.assertIsNone(failure)

    def test_missing_key_is_violation(self):
        ok, failure = validate_input_range({"consumer"}, ["consumer", "reference"])
        self.assertFalse(ok)
        self.assertEqual(failure, "input_range_violation")

    def test_extra_keys_are_allowed(self):
        ok, failure = validate_input_range(
            {"consumer", "reference", "extra"}, ["consumer", "reference"])
        self.assertTrue(ok)

    def test_unit_fixture_without_requirement_passes(self):
        for required in ([], None):
            with self.subTest(required=required):
                ok, failure = validate_input_range(set(), required)
                self.assertTrue(ok)
                self.assertIsNone(failure)

    def test_accepts_any_iterable(self):
        ok, _ = validate_input_range(
            ["consumer", "reference"], ("consumer", "reference"))
        self.assertTrue(ok)

    def test_empty_dispatch_against_requirement_is_violation(self):
        ok, failure = validate_input_range([], ["consumer"])
        self.assertFalse(ok)
        self.assertEqual(failure, "input_range_violation")

    def test_failure_type_is_registered(self):
        self.assertIn("input_range_violation", PROTOCOL_FAILURE_TYPES)


# ===========================================================================
# taxonomy / emitter coverage
# ===========================================================================

# Labeled corpus: one sample per published protocol failure type, plus clean
# samples. Drives the coverage test below AND the measurement harness — if a
# type is published but no library call emits it, harness authors must
# hand-roll the detection (the gap this corpus exists to prevent).
PROTOCOL_CORPUS = [
    # (label, callable -> (ok, failure))
    ("malformed_output",
     lambda: validate_checker_output("{not json", CHECKLIST_TWO)),
    ("missing_grade",
     lambda: validate_checker_output(
         {"grades": [{"requirement_index": 0, "result": "pass", "evidence": "e"}]},
         CHECKLIST_TWO)),
    ("extra_grade",
     lambda: validate_checker_output(
         {"grades": [{"requirement_index": 9, "result": "pass", "evidence": "e"}]},
         CHECKLIST_TWO)),
    ("duplicate_grade",
     lambda: validate_checker_output(
         {"grades": [
             {"requirement_index": 0, "result": "pass", "evidence": "e"},
             {"requirement_index": 0, "result": "fail", "evidence": "e"},
         ]}, CHECKLIST_TWO)),
    ("invalid_result_value",
     lambda: validate_checker_output(
         {"grades": [{"requirement_index": 0, "result": "MAYBE", "evidence": "e"}]},
         CHECKLIST_TWO)),
    ("empty_checklist",
     lambda: validate_checker_output({"grades": []}, [])),
    ("missing_evidence",
     lambda: validate_checker_output(
         {"grades": [
             {"requirement_index": 0, "result": "pass", "evidence": "e"},
             {"requirement_index": 1, "result": "fail", "evidence": ""},
         ]}, CHECKLIST_TWO)),
    ("missing_isolation_note",
     lambda: validate_checker_output(
         VALID_GRADES, CHECKLIST_TWO, fixture_kind="integration")),
    ("isolation_violation",
     lambda: validate_checker_output(
         {**VALID_GRADES, "isolation_note": "opened the repo"},
         CHECKLIST_TWO, fixture_kind="integration")),
    ("input_range_violation",
     lambda: validate_input_range({"consumer"}, ["consumer", "reference"])),
]

CLEAN_CORPUS = [
    ("unit output",
     lambda: validate_checker_output(VALID_GRADES, CHECKLIST_TWO)),
    ("integration output",
     lambda: validate_checker_output(
         {**VALID_GRADES, "isolation_note": None},
         CHECKLIST_TWO, fixture_kind="integration")),
    ("complete input range",
     lambda: validate_input_range(
         {"consumer", "reference"}, ["consumer", "reference"])),
]


class TestTaxonomyEmitterCoverage(unittest.TestCase):

    def test_every_published_type_has_an_emitter(self):
        # AC: publishing a type the library cannot emit pushes detection onto
        # every harness author. Keep PROTOCOL_FAILURE_TYPES and the emitters
        # in lockstep.
        emitted = set()
        for label, call in PROTOCOL_CORPUS:
            ok, failure = call()
            self.assertFalse(ok, label)
            self.assertEqual(failure, label)
            emitted.add(failure)
        self.assertEqual(emitted, set(PROTOCOL_FAILURE_TYPES))

    def test_clean_samples_produce_no_false_positives(self):
        for label, call in CLEAN_CORPUS:
            with self.subTest(label=label):
                ok, failure = call()
                self.assertTrue(ok)
                self.assertIsNone(failure)


# ===========================================================================
# has_protocol_failure / halt on protocol failure
# ===========================================================================

def _iter_with_harness_error(iteration, error_type):
    return {
        "iteration": iteration,
        "prompt_bytes": 1000,
        "scenarios": [
            {
                "id": "A",
                "success": False,
                "precision": 0.0,
                "steps": 3,
                "duration_ms": 5000,
                "retries": 0,
                "friction": [],
                "harness_error": {"type": error_type, "detail": "..."},
            }
        ],
    }


class TestHasProtocolFailure(unittest.TestCase):

    def test_detects_isolation_violation(self):
        rec = _iter_with_harness_error(1, "isolation_violation")
        self.assertTrue(has_protocol_failure(rec))

    def test_detects_input_range_violation(self):
        rec = _iter_with_harness_error(1, "input_range_violation")
        self.assertTrue(has_protocol_failure(rec))

    def test_ignores_unknown_error_type(self):
        rec = _iter_with_harness_error(1, "not_a_protocol_failure")
        self.assertFalse(has_protocol_failure(rec))

    def test_candidate_failure_alone_is_not_protocol_failure(self):
        rec = _make_iter(1, precision=0.0,
                         friction=[{"category": "missing_premise"}])
        rec["scenarios"][0]["success"] = False
        self.assertFalse(has_protocol_failure(rec))

    def test_no_harness_error_field(self):
        rec = _make_iter(1)
        self.assertFalse(has_protocol_failure(rec))


class TestExitVerdictHaltOnProtocolFailure(unittest.TestCase):

    def test_halt_when_latest_iter_has_protocol_failure(self):
        h = [
            _make_iter(1, precision=0.85),
            _iter_with_harness_error(2, "malformed_output"),
        ]
        v = resolve_exit_verdict(h, max_iter=100)
        self.assertEqual(v, "halt")

    def test_reason_reports_checker_protocol_failure(self):
        h = [_iter_with_harness_error(1, "malformed_output")]
        reason = resolve_halt_reason(h, max_iter=100)
        self.assertEqual(reason, "checker_protocol_failure")

    def test_kill_file_beats_protocol_failure(self):
        h = [_iter_with_harness_error(1, "malformed_output")]
        v = resolve_exit_verdict(h, max_iter=100, kill_file_exists=True)
        reason = resolve_halt_reason(h, max_iter=100, kill_file_exists=True)
        self.assertEqual(v, "halt")
        self.assertEqual(reason, "kill_file")

    def test_checklist_tampered_beats_protocol_failure(self):
        h = [_iter_with_harness_error(1, "malformed_output")]
        v = resolve_exit_verdict(h, max_iter=100, checklist_tampered=True)
        reason = resolve_halt_reason(
            h, max_iter=100, checklist_tampered=True,
        )
        self.assertEqual(v, "halt")
        self.assertEqual(reason, "checklist_tampered")

    def test_checklist_tampered_halts_without_history(self):
        # verdict and reason must agree even when the only halt signal is
        # checklist_tampered (no protocol failure, no max_iter).
        v = resolve_exit_verdict([], max_iter=100, checklist_tampered=True)
        reason = resolve_halt_reason([], max_iter=100, checklist_tampered=True)
        self.assertEqual(v, "halt")
        self.assertEqual(reason, "checklist_tampered")

    def test_max_iter_still_halts_reason_is_max_iter(self):
        h = [_make_iter(i) for i in range(1, 11)]
        v = resolve_exit_verdict(h, max_iter=10)
        reason = resolve_halt_reason(h, max_iter=10)
        self.assertEqual(v, "halt")
        self.assertEqual(reason, "max_iter")

    def test_protocol_failure_only_checks_latest_iter(self):
        # a stale protocol failure from an earlier iter must not halt the run
        # forever — the halt fires only on the current iteration.
        h = [
            _iter_with_harness_error(1, "malformed_output"),
            _make_iter(2, precision=0.9),
            _make_iter(3, precision=0.91),
        ]
        v = resolve_exit_verdict(h, max_iter=100)
        # last iter has no protocol failure — converge/continue path applies.
        self.assertNotEqual(v, "halt")


if __name__ == "__main__":
    unittest.main()
