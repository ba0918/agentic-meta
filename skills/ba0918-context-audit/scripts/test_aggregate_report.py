#!/usr/bin/env python3
"""Unit tests for aggregate_report.py (baseline suppression and the report skeleton)."""

import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path


def _load(module_name: str, filename: str):
    """Load a script sitting beside this file under a name unique to this skill.

    Not a plain `import` of the basename: another skill in this repository carries a
    script of the same name, and one test session keeps only the first module bound to
    a given name, so the plain form would hand one skill's tests the other skill's
    module. Loading from the file path lets each skill name its own copy.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ar = _load("ba0918_context_audit_aggregate_report", "aggregate_report.py")


def _abs(*parts: str) -> str:
    """Build a rooted path at run time.

    Assembled rather than written as a literal: the self-containment lint reads a
    rooted path anywhere in a skill's files as a reference outside the skill
    directory, and these stand-in file locations would read exactly like one.
    """
    return "/" + "/".join(parts)


def finding(rule_id="CA-S001", severity="WARN", action="NEEDS_JUDGMENT",
            where="a.md:1", what="w", fix_action=None):
    return {"id": rule_id, "severity": severity, "action": action, "where": where,
            "what": what, "why": "y", "how": "h", "fix_action": fix_action}


class TestFindingIdentifier(unittest.TestCase):
    def test_the_same_finding_always_gets_the_same_identifier(self):
        one = finding()
        self.assertEqual(ar.finding_id(one), ar.finding_id(dict(one)))

    def test_the_identifier_gives_away_nothing_about_what_was_found(self):
        identifier = ar.finding_id(finding(what="a secret-ish detail"))
        self.assertNotIn("secret-ish detail", identifier)
        self.assertTrue(all(char in "0123456789abcdef" for char in identifier))

    def test_two_findings_at_different_places_get_different_identifiers(self):
        self.assertNotEqual(
            ar.finding_id(finding(where="a.md:1")),
            ar.finding_id(finding(where="a.md:2")),
        )


class TestSuppression(unittest.TestCase):
    def test_a_finding_listed_in_the_baseline_is_withheld_and_counted(self):
        first, second = finding(where="a.md:1"), finding(where="a.md:2")
        baseline = {"suppressions": [ar.finding_id(first)]}
        kept, suppressed = ar.apply_suppression([first, second], baseline)
        self.assertEqual([f["where"] for f in kept], ["a.md:2"])
        self.assertEqual(suppressed, 1)

    def test_without_a_baseline_nothing_is_withheld(self):
        findings = [finding(where="a.md:1"), finding(where="a.md:2")]
        kept, suppressed = ar.apply_suppression(findings, None)
        self.assertEqual(len(kept), 2)
        self.assertEqual(suppressed, 0)


class TestCounting(unittest.TestCase):
    def test_findings_are_counted_by_how_they_may_be_fixed(self):
        counts = ar.summarize([finding(action="AUTO_FIX"), finding(action="AUTO_FIX"),
                               finding(action="REPORT_ONLY")])
        self.assertEqual(counts["AUTO_FIX"], 2)
        self.assertEqual(counts["REPORT_ONLY"], 1)
        self.assertEqual(counts["NEEDS_JUDGMENT"], 0)

    def test_findings_are_counted_by_severity(self):
        counts = ar.summarize([finding(severity="BLOCK"), finding(severity="WARN")])
        self.assertEqual(counts["by_severity"], {"BLOCK": 1, "WARN": 1})


class TestReport(unittest.TestCase):
    def test_the_summary_counts_what_was_kept_and_what_was_withheld(self):
        findings = [finding(action="AUTO_FIX", where="a.md:1"),
                    finding(action="NEEDS_JUDGMENT", where="a.md:2")]
        baseline = {"suppressions": [ar.finding_id(findings[0])]}
        summary = ar.build_report(findings, baseline)["summary"]
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["suppressed"], 1)
        self.assertEqual(summary["NEEDS_JUDGMENT"], 1)

    def test_the_way_a_finding_may_be_fixed_is_carried_over_untouched(self):
        found = finding(rule_id="CA-M001", action="AUTO_FIX",
                        fix_action={"path": "n.md", "old": "a", "new": "b"})
        report = ar.build_report([found], None)
        self.assertEqual(report["findings"][0]["action"], "AUTO_FIX")

    def test_the_report_withholds_the_text_a_fix_would_replace(self):
        found = finding(rule_id="CA-M001", action="AUTO_FIX",
                        fix_action={"path": "n.md", "old": "name:   a note",
                                    "new": "name: a note"})
        report = ar.build_report([found], None)
        self.assertNotIn("name:   a note", json.dumps(report))
        self.assertNotIn("name:   a note", json.dumps(report["groups"]))

    def test_withholding_it_leaves_the_findings_the_fixes_are_applied_from_alone(self):
        found = finding(rule_id="CA-M001", action="AUTO_FIX",
                        fix_action={"path": "n.md", "old": "name:   a note",
                                    "new": "name: a note"})
        ar.build_report([found], None)
        self.assertEqual(found["fix_action"]["old"], "name:   a note")

    def test_the_gravest_findings_are_listed_first(self):
        findings = [finding(severity="INFO", where="a.md:1"),
                    finding(severity="BLOCK", where="a.md:2"),
                    finding(severity="WARN", where="a.md:3")]
        report = ar.build_report(findings, None)
        self.assertEqual([f["severity"] for f in report["findings"]],
                         ["BLOCK", "WARN", "INFO"])

    def test_the_same_findings_always_produce_the_same_report(self):
        findings = [finding(where="a.md:1"), finding(where="b.md:2", severity="BLOCK")]
        self.assertEqual(ar.build_report(findings, None), ar.build_report(findings, None))

    def test_every_reported_finding_carries_its_identifier(self):
        report = ar.build_report([finding()], None)
        self.assertIn("finding_id", report["findings"][0])

    def test_findings_are_gathered_under_the_rule_that_found_them(self):
        report = ar.build_report(
            [finding(rule_id="CA-S001", where="a.md:1"),
             finding(rule_id="CA-S001", where="a.md:2"),
             finding(rule_id="CA-U001", where="b.md:1")], None)
        self.assertEqual([(g["rule_id"], g["count"]) for g in report["groups"]],
                         [("CA-S001", 2), ("CA-U001", 1)])


class TestMemoryProvenance(unittest.TestCase):
    def test_the_memory_directory_that_was_read_is_named_in_full(self):
        memory = _abs("store", "projects", "a-project", "memory")
        report = ar.build_report([finding()], None, memory_dir=memory)
        self.assertEqual(report["memory_dir"], memory)
        self.assertIn(memory, ar.render_markdown(report))

    def test_a_report_given_no_memory_location_says_so_rather_than_staying_silent(self):
        report = ar.build_report([finding()], None, memory_dir=None)
        self.assertIsNone(report["memory_dir"])
        self.assertIn("no location reported", ar.render_markdown(report))

    def test_the_memory_directory_is_taken_from_the_collected_targets(self):
        memory = _abs("store", "projects", "a-project", "memory")
        with tempfile.TemporaryDirectory() as work:
            targets = Path(work) / "targets.json"
            targets.write_text(json.dumps({"targets": [], "memory_dir": memory}),
                               encoding="utf-8")
            findings = Path(work) / "findings.json"
            findings.write_text(json.dumps({"findings": [finding()]}), encoding="utf-8")
            output = Path(work) / "report.md"
            ar.main([str(findings), "--targets", str(targets),
                     "--markdown", "--output", str(output)])
            self.assertIn(memory, output.read_text(encoding="utf-8"))


class TestRenderedReport(unittest.TestCase):
    def test_the_counts_lead_the_report_before_any_finding(self):
        report = ar.build_report([finding(action="AUTO_FIX"),
                                  finding(action="REPORT_ONLY", where="a.md:2")], None)
        lines = ar.render_markdown(report).splitlines()
        headline = next(line for line in lines if "AUTO_FIX" in line)
        first_finding = next(line for line in lines if line.startswith("- ["))
        self.assertIn("2 findings", headline)
        self.assertIn("1 AUTO_FIX", headline)
        self.assertIn("1 REPORT_ONLY", headline)
        self.assertLess(lines.index(headline), lines.index(first_finding))

    def test_a_run_that_found_nothing_reports_that_it_found_nothing(self):
        rendered = ar.render_markdown(ar.build_report([], None))
        self.assertIn("0 findings", rendered)


class TestWhatTheRunCovered(unittest.TestCase):
    """A report is read as a statement about the whole instruction layer, so it has to
    carry what was checked, what was passed over, and how far its mask reaches."""

    def test_the_report_names_the_checks_that_ran(self):
        rendered = ar.render_markdown(
            ar.build_report([], None, rules_run=["CA-S001", "CA-U001"]))
        self.assertIn("CA-S001", rendered)
        self.assertIn("CA-U001", rendered)

    def test_the_report_names_the_targets_that_were_passed_over(self):
        rendered = ar.render_markdown(
            ar.build_report([], None, skipped=["PROJECT.md", "<project-memory>"]))
        self.assertIn("PROJECT.md", rendered)
        self.assertIn("<project-memory>", rendered)

    def test_a_run_that_passed_over_nothing_says_so_rather_than_staying_silent(self):
        self.assertIn("skipped: none",
                      ar.render_markdown(ar.build_report([], None, skipped=[])))

    def test_the_report_states_that_the_mask_it_relies_on_is_incomplete(self):
        self.assertIn("blocklist", ar.render_markdown(ar.build_report([], None)))

    def test_the_structured_form_states_it_as_well_rather_than_the_prose_form_alone(self):
        self.assertIn("blocklist", json.dumps(ar.build_report([], None)))

    def test_both_forms_state_it_in_the_same_words(self):
        report = ar.build_report([], None)
        self.assertIn(report["mask_is_incomplete"], ar.render_markdown(report))

    def test_what_ran_and_what_was_passed_over_come_from_the_two_input_files(self):
        with tempfile.TemporaryDirectory() as work:
            targets = Path(work) / "targets.json"
            targets.write_text(
                json.dumps({"targets": [], "skipped": ["PROJECT.md"],
                            "memory_dir": None}), encoding="utf-8")
            findings = Path(work) / "findings.json"
            findings.write_text(
                json.dumps({"findings": [finding(rule_id="CA-U001")],
                            "rules_run": ["CA-S001", "CA-U001"]}), encoding="utf-8")
            output = Path(work) / "report.md"
            ar.main([str(findings), "--targets", str(targets),
                     "--markdown", "--output", str(output)])
            rendered = output.read_text(encoding="utf-8")
            self.assertIn("PROJECT.md", rendered)
            self.assertIn("CA-S001", rendered)


class TestBaselineWriting(unittest.TestCase):
    def test_the_baseline_holds_identifiers_and_nothing_else(self):
        written = ar.build_baseline([finding(where="a.md:1", what="sensitive detail"),
                                     finding(where="a.md:2")])
        self.assertEqual(written["version"], 1)
        self.assertEqual(len(written["suppressions"]), 2)
        self.assertNotIn("sensitive detail", repr(written))
        self.assertNotIn("a.md", repr(written))

    def test_findings_written_to_a_baseline_are_all_withheld_afterwards(self):
        findings = [finding(where="a.md:1"), finding(where="a.md:2")]
        kept, suppressed = ar.apply_suppression(findings, ar.build_baseline(findings))
        self.assertEqual(kept, [])
        self.assertEqual(suppressed, 2)

    def test_the_order_the_findings_arrive_in_does_not_change_the_baseline(self):
        findings = [finding(where="b.md:9"), finding(where="a.md:1")]
        self.assertEqual(ar.build_baseline(findings),
                         ar.build_baseline(list(reversed(findings))))


class TestBaselineOverPartOfWhatWasFound(unittest.TestCase):
    """A first run may keep reporting the heaviest findings and settle for baselining
    the rest, so a baseline has to be writable over a part of what was found."""

    def test_a_finding_as_grave_as_the_cut_stays_out_of_the_baseline(self):
        self.assertEqual(ar.findings_below([finding(severity="WARN")], "WARN"), [])

    def test_a_baseline_cut_at_a_severity_withholds_only_the_lighter_findings(self):
        heavy, light = finding(severity="BLOCK", where="a.md:1"), \
            finding(severity="INFO", where="a.md:2")
        written = ar.build_baseline(ar.findings_below([heavy, light], "WARN"))
        kept, suppressed = ar.apply_suppression([heavy, light], written)
        self.assertEqual([f["severity"] for f in kept], ["BLOCK"])
        self.assertEqual(suppressed, 1)

    def test_a_severity_no_finding_can_carry_is_refused_rather_than_acted_on(self):
        """A cut nothing can fall under produces an empty baseline, which reads exactly
        like a run that found the project already settled. Refused at the argument."""
        with tempfile.TemporaryDirectory() as work:
            findings = Path(work) / "findings.json"
            findings.write_text(json.dumps({"findings": [finding(severity="INFO")]}),
                                encoding="utf-8")
            baseline = Path(work) / "baseline.json"
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    ar.main([str(findings), "--update-baseline", str(baseline),
                             "--baseline-below", "warn"])
            self.assertFalse(baseline.exists())

    def test_the_baseline_the_script_writes_honours_the_cut_it_was_given(self):
        heavy, light = finding(severity="BLOCK", where="a.md:1"), \
            finding(severity="INFO", where="a.md:2")
        with tempfile.TemporaryDirectory() as work:
            findings = Path(work) / "findings.json"
            findings.write_text(json.dumps({"findings": [heavy, light]}),
                                encoding="utf-8")
            baseline = Path(work) / "baseline.json"
            ar.main([str(findings), "--update-baseline", str(baseline),
                     "--baseline-below", "WARN"])
            written = json.loads(baseline.read_text(encoding="utf-8"))
            self.assertEqual(written["suppressions"], [ar.finding_id(light)])


if __name__ == "__main__":
    unittest.main()
