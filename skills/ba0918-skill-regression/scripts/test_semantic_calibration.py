#!/usr/bin/env python3
"""Unit tests for semantic_calibration.py.

Letting a judge decide what "does not affect behaviour" means is only defensible
if the judge's own unreliability has been measured first. The dangerous direction
is the false negative — called unaffected while it was not — so that is what the
gate is built around, and these tests hold that shape in place.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lock
import semantic_calibration as sc


def _case(case_id, expected, before="a\n", after="b\n"):
    return {"id": case_id, "expected": expected, "before": before, "after": after,
            "requirements": ["the behaviour under test still holds"]}


def _corpus(root, must_flag=1, must_pass=1, extra=None):
    for side, expected, count in (("must_flag", "must-flag", must_flag),
                                  ("must_pass", "must-pass", must_pass)):
        directory = os.path.join(root, "calibration", side)
        os.makedirs(directory, exist_ok=True)
        for index in range(count):
            case_id = f"{side}-{index:03d}"
            with open(os.path.join(directory, f"{case_id}.json"), "w",
                      encoding="utf-8") as f:
                json.dump(_case(case_id, expected), f)
    for rel, payload in (extra or {}).items():
        path = os.path.join(root, "calibration", rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(payload if isinstance(payload, str) else json.dumps(payload))
    return root


class TestCorpusLoading(unittest.TestCase):
    def test_reads_both_sides(self):
        with tempfile.TemporaryDirectory() as root:
            _corpus(root, must_flag=2, must_pass=3)
            cases, errors = sc.load_corpus(root)
            self.assertEqual(errors, [])
            self.assertEqual(len(cases), 5)

    def test_a_case_missing_a_field_is_reported_and_dropped(self):
        with tempfile.TemporaryDirectory() as root:
            _corpus(root, extra={"must_flag/broken.json": {"id": "broken"}})
            cases, errors = sc.load_corpus(root)
            self.assertNotIn("broken", cases)
            self.assertTrue(errors)

    def test_a_case_whose_expected_contradicts_its_directory_is_reported(self):
        # Letting it through would quietly reverse the direction of the scoring.
        with tempfile.TemporaryDirectory() as root:
            _corpus(root, extra={"must_pass/wrong.json": _case("wrong", "must-flag")})
            _, errors = sc.load_corpus(root)
            self.assertTrue(any("must-flag" in e for e in errors))

    def test_a_duplicate_id_is_reported(self):
        # Ids are the key scoring joins on; a duplicate would drop one verdict.
        with tempfile.TemporaryDirectory() as root:
            _corpus(root, must_flag=1)
            _, errors = sc.load_corpus(
                _corpus(root, extra={"must_flag/copy.json":
                                     _case("must_flag-000", "must-flag")}))
            self.assertTrue(any("must_flag-000" in e for e in errors))

    def test_an_edit_that_changes_nothing_is_reported(self):
        with tempfile.TemporaryDirectory() as root:
            _corpus(root, extra={"must_flag/same.json":
                                 _case("same", "must-flag", before="x\n", after="x\n")})
            _, errors = sc.load_corpus(root)
            self.assertTrue(errors)

    def test_a_thin_corpus_fails_validation(self):
        with tempfile.TemporaryDirectory() as root:
            _corpus(root, must_flag=1, must_pass=1)
            self.assertTrue(sc.validate_corpus(root, min_cases=20))

    def test_the_corpus_fingerprint_is_deterministic_and_content_bound(self):
        with tempfile.TemporaryDirectory() as root:
            _corpus(root, must_flag=2, must_pass=2)
            first = sc.corpus_sha256(root)
            self.assertEqual(first, sc.corpus_sha256(root))
            with open(os.path.join(root, "calibration", "must_flag",
                                   "must_flag-000.json"), "w", encoding="utf-8") as f:
                json.dump(_case("must_flag-000", "must-flag", after="c\n"), f)
            self.assertNotEqual(first, sc.corpus_sha256(root))


class TestScoring(unittest.TestCase):
    def _cases(self):
        return {"f1": _case("f1", "must-flag"), "p1": _case("p1", "must-pass")}

    def test_calling_a_behaviour_change_unaffected_is_a_false_negative(self):
        scored, errors = sc.score(self._cases(),
                                  {"f1": lock.VERDICT_UNAFFECTED,
                                   "p1": lock.VERDICT_UNAFFECTED})
        self.assertEqual(errors, [])
        self.assertEqual(scored["must_flag_fn"], 1)
        self.assertEqual(scored["must_pass_fp"], 0)

    def test_unclear_on_a_behaviour_change_is_not_a_false_negative(self):
        # Unclear goes to a human, so it is not a dangerous miss.
        scored, _ = sc.score(self._cases(),
                             {"f1": lock.VERDICT_UNCLEAR,
                              "p1": lock.VERDICT_UNAFFECTED})
        self.assertEqual(scored["must_flag_fn"], 0)

    def test_anything_but_unaffected_on_a_safe_edit_is_a_false_positive(self):
        for verdict in (lock.VERDICT_UNCLEAR, lock.VERDICT_AFFECTED):
            scored, _ = sc.score(self._cases(),
                                 {"f1": lock.VERDICT_AFFECTED, "p1": verdict})
            self.assertEqual(scored["must_pass_fp"], 1, verdict)

    def test_a_missing_verdict_is_an_error(self):
        # Otherwise a perfect calibration could be built from one judged case.
        _, errors = sc.score(self._cases(), {"f1": lock.VERDICT_AFFECTED})
        self.assertTrue(any("p1" in e for e in errors))

    def test_a_verdict_for_an_unknown_case_is_an_error(self):
        _, errors = sc.score(self._cases(),
                             {"f1": lock.VERDICT_AFFECTED, "p1": lock.VERDICT_UNAFFECTED,
                              "ghost": lock.VERDICT_UNAFFECTED})
        self.assertTrue(any("ghost" in e for e in errors))

    def test_a_verdict_outside_the_three_values_is_an_error(self):
        _, errors = sc.score(self._cases(),
                             {"f1": "maybe", "p1": lock.VERDICT_UNAFFECTED})
        self.assertTrue(errors)


class TestGate(unittest.TestCase):
    def _scored(self, **over):
        scored = {"must_flag_fn": 0, "must_pass_fp": 2, "cases": 50,
                  "must_flag_cases": 24, "must_pass_cases": 26}
        scored.update(over)
        return scored

    def test_a_clean_calibration_opens_the_gate(self):
        self.assertIsNone(sc.gate_reason(self._scored(), errors=[], min_cases=20))

    def test_one_false_negative_closes_it(self):
        self.assertIsNotNone(
            sc.gate_reason(self._scored(must_flag_fn=1), errors=[], min_cases=20))

    def test_a_thin_side_closes_it(self):
        self.assertIsNotNone(
            sc.gate_reason(self._scored(must_pass_cases=3), errors=[], min_cases=20))

    def test_any_scoring_error_closes_it(self):
        self.assertIsNotNone(
            sc.gate_reason(self._scored(), errors=["a case went unjudged"], min_cases=20))

    def test_false_positives_alone_do_not_close_it(self):
        # A false positive only costs a rerun; it never records an unsafe pass.
        self.assertIsNone(
            sc.gate_reason(self._scored(must_pass_fp=9), errors=[], min_cases=20))


class TestPermissionBoundary(unittest.TestCase):
    def test_the_module_cannot_start_anything(self):
        """The judge never launches anything, in any direction.

        Holding that with a promise in prose would leave it to be re-broken by
        the next edit; holding it by the absence of the dependency cannot be.
        """
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "semantic_calibration.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        for forbidden in ("subprocess", "os.system", "os.popen", "os.exec",
                          "os.spawn", "multiprocessing", "socket", "urllib",
                          "http.client"):
            self.assertNotIn(forbidden, source, forbidden)


class TestPortedCorpus(unittest.TestCase):
    def test_the_shipped_corpus_validates(self):
        skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assertEqual(sc.validate_corpus(skill_dir, min_cases=20), [])


if __name__ == "__main__":
    unittest.main()
