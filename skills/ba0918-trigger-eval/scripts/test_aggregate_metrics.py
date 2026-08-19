#!/usr/bin/env python3
"""Unit tests for aggregate_metrics.py.

Fixture expected values are hand-computed from metrics-spec.md formulas.

Fixture cases (valid skills = plan, commit, cycle):
  c1 gold=plan   j=[plan, plan]     -> plan TP; stability match
  c2 gold=plan   j=[commit]         -> plan FN, commit FP (misfire attribution)
  c3 gold=commit j=[commit]         -> commit TP
  c4 gold=none   j=[none]           -> specificity numerator
  c5 gold=none   j=[plan]           -> plan FP, specificity denom only
  c6 gold=cycle  j=[banana]         -> INVALID (not in list); cycle FN
  c7 gold=plan   j=[plan, commit]   -> plan TP (j1); stability mismatch
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import aggregate_metrics as am

VALID = ["plan", "commit", "cycle"]
CASES = [
    {"case_id": "c1", "gold": "plan", "judgments": ["plan", "plan"]},
    {"case_id": "c2", "gold": "plan", "judgments": ["commit"]},
    {"case_id": "c3", "gold": "commit", "judgments": ["commit"]},
    {"case_id": "c4", "gold": "none", "judgments": ["none"]},
    {"case_id": "c5", "gold": "none", "judgments": ["plan"]},
    {"case_id": "c6", "gold": "cycle", "judgments": ["banana"]},
    {"case_id": "c7", "gold": "plan", "judgments": ["plan", "commit"]},
]


class TestNormalizeJudgment(unittest.TestCase):
    def setUp(self):
        self.valid = set(VALID) | {"none"}

    def test_valid_skill(self):
        self.assertEqual(am.normalize_judgment("plan", self.valid), "plan")

    def test_none_label(self):
        self.assertEqual(am.normalize_judgment("none", self.valid), "none")

    def test_unknown_skill_is_invalid(self):
        self.assertEqual(am.normalize_judgment("banana", self.valid), "INVALID")

    def test_multiple_skills_is_invalid(self):
        self.assertEqual(am.normalize_judgment(["plan", "commit"], self.valid), "INVALID")

    def test_explicit_invalid(self):
        self.assertEqual(am.normalize_judgment("INVALID", self.valid), "INVALID")

    def test_empty_or_none_is_invalid(self):
        self.assertEqual(am.normalize_judgment("", self.valid), "INVALID")
        self.assertEqual(am.normalize_judgment(None, self.valid), "INVALID")


class TestPerSkill(unittest.TestCase):
    def setUp(self):
        self.r = am.aggregate(CASES, VALID)

    def test_plan(self):
        p = self.r["per_skill"]["plan"]
        self.assertEqual((p["tp"], p["fn"], p["fp"]), (2, 1, 1))
        self.assertAlmostEqual(p["recall"], 2 / 3)
        self.assertAlmostEqual(p["precision"], 2 / 3)

    def test_commit(self):
        p = self.r["per_skill"]["commit"]
        self.assertEqual((p["tp"], p["fn"], p["fp"]), (1, 0, 1))
        self.assertAlmostEqual(p["recall"], 1.0)
        self.assertAlmostEqual(p["precision"], 0.5)

    def test_cycle_precision_undefined(self):
        p = self.r["per_skill"]["cycle"]
        self.assertEqual((p["tp"], p["fn"], p["fp"]), (0, 1, 0))
        self.assertAlmostEqual(p["recall"], 0.0)
        self.assertIsNone(p["precision"])  # TP+FP=0 -> undefined


class TestMacroMicro(unittest.TestCase):
    def setUp(self):
        self.r = am.aggregate(CASES, VALID)

    def test_macro_recall(self):
        self.assertAlmostEqual(self.r["macro"]["recall"], (2 / 3 + 1.0 + 0.0) / 3)

    def test_macro_precision_excludes_undefined(self):
        self.assertAlmostEqual(self.r["macro"]["precision"], (2 / 3 + 0.5) / 2)

    def test_micro(self):
        self.assertAlmostEqual(self.r["micro"]["recall"], 3 / 5)
        self.assertAlmostEqual(self.r["micro"]["precision"], 3 / 5)


class TestSpecificityAndInvalid(unittest.TestCase):
    def setUp(self):
        self.r = am.aggregate(CASES, VALID)

    def test_specificity(self):
        s = self.r["specificity"]
        self.assertEqual((s["num"], s["denom"]), (1, 2))
        self.assertAlmostEqual(s["value"], 0.5)

    def test_invalid_rate(self):
        self.assertEqual(self.r["invalid_count"], 1)
        self.assertAlmostEqual(self.r["invalid_rate"], 1 / 7)


class TestStability(unittest.TestCase):
    def test_full_sample(self):
        r = am.aggregate(CASES, VALID)
        st = r["stability"]
        # c1 match, c7 mismatch -> 1/2
        self.assertEqual(st["sample_size"], 2)
        self.assertEqual(st["matches"], 1)
        self.assertAlmostEqual(st["value"], 0.5)

    def test_restricted_sample(self):
        r = am.aggregate(CASES, VALID, stability_sample_ids=["c1"])
        st = r["stability"]
        self.assertEqual(st["sample_size"], 1)
        self.assertAlmostEqual(st["value"], 1.0)

    def test_no_pairs(self):
        cases = [{"case_id": "x", "gold": "plan", "judgments": ["plan"]}]
        r = am.aggregate(cases, VALID)
        self.assertEqual(r["stability"]["sample_size"], 0)
        self.assertIsNone(r["stability"]["value"])


class TestConfusion(unittest.TestCase):
    def setUp(self):
        self.r = am.aggregate(CASES, VALID)

    def test_cells_nonzero(self):
        cells = {(c["gold"], c["pred"]): c["count"] for c in self.r["confusion"]["cells"]}
        self.assertEqual(cells[("plan", "plan")], 2)
        self.assertEqual(cells[("plan", "commit")], 1)
        self.assertEqual(cells[("cycle", "INVALID")], 1)
        self.assertEqual(cells[("none", "plan")], 1)

    def test_pair_ranking(self):
        pairs = self.r["confusion"]["pairs"]
        top = pairs[0]
        self.assertEqual({top["a"], top["b"]}, {"plan", "commit"})
        self.assertEqual(top["raw"], 1)
        self.assertEqual(top["related"], 4)  # gold plan(3) + gold commit(1)
        self.assertAlmostEqual(top["normalized"], 0.25)

    def test_pairs_sorted_desc(self):
        raws = [p["raw"] for p in self.r["confusion"]["pairs"]]
        self.assertEqual(raws, sorted(raws, reverse=True))


class TestEdgeCases(unittest.TestCase):
    def test_empty_cases(self):
        r = am.aggregate([], VALID)
        self.assertEqual(r["case_count"], 0)
        self.assertEqual(r["invalid_rate"], 0.0)

    def test_no_none_cases_specificity_none(self):
        cases = [{"case_id": "x", "gold": "plan", "judgments": ["plan"]}]
        r = am.aggregate(cases, VALID)
        self.assertIsNone(r["specificity"]["value"])


if __name__ == "__main__":
    unittest.main()
