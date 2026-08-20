#!/usr/bin/env python3
"""Unit tests for static_checks.py (the pure-function CA-* rule engine)."""

import importlib.util
import os
import unittest


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


sc = _load("ba0918_context_audit_static_checks", "static_checks.py")


def _abs(*parts: str) -> str:
    """Build a rooted path at run time.

    Assembled rather than written as a literal: the self-containment lint reads a
    rooted path anywhere in a skill's files as a reference outside the skill
    directory, and these stand-in file locations would read exactly like one.
    """
    return "/" + "/".join(parts)


# Assembled so the credential shapes below are not themselves scannable literals.
AWS_KEY = "AK" + "IA" + "IOSFODNN7" + "EXAMPLE"


class TestFindingSchema(unittest.TestCase):
    def test_a_finding_carrying_every_required_field_is_accepted(self):
        finding = sc.make_finding(
            "CA-S001", "WARN", "REPORT_ONLY", "a.md:1",
            what="w", why="y", how="h")
        self.assertEqual(sc.validate_finding_schema(finding), [])

    def test_a_finding_missing_a_required_field_is_told_which_one(self):
        self.assertIn("why", sc.validate_finding_schema({"id": "CA-S001"}))

    def test_a_finding_records_no_fix_when_none_is_offered(self):
        finding = sc.make_finding(
            "CA-S001", "WARN", "REPORT_ONLY", "a.md:1",
            what="w", why="y", how="h")
        self.assertIsNone(finding["fix_action"])


class TestRedactionBeforeSerialization(unittest.TestCase):
    def test_a_credential_quoted_in_a_findings_text_is_replaced(self):
        finding = sc.make_finding(
            "CA-U001", "WARN", "REPORT_ONLY", "a.md:1",
            what=f"line reads {AWS_KEY}", why="y", how="h")
        out = sc.finalize_findings([finding])
        self.assertNotIn(AWS_KEY, repr(out))

    def test_the_file_a_fix_would_open_survives_the_redaction(self):
        target_path = _abs("home", "someuser", "repo", "CLAUDE.md")
        finding = sc.make_finding(
            "CA-S001", "WARN", "AUTO_FIX", "CLAUDE.md:1",
            what="w", why="y", how="h",
            fix_action={"path": target_path, "old": "a.md", "new": "b.md"})
        out = sc.finalize_findings([finding])
        self.assertEqual(out[0]["fix_action"]["path"], target_path)

    def test_the_text_a_fix_replaces_is_redacted(self):
        finding = sc.make_finding(
            "CA-M001", "WARN", "AUTO_FIX", "n.md:1",
            what="w", why="y", how="h",
            fix_action={"path": _abs("home", "someuser", "n.md"),
                        "old": f"x {AWS_KEY}", "new": "x"})
        out = sc.finalize_findings([finding])
        self.assertNotIn(AWS_KEY, out[0]["fix_action"]["old"])


class TestRuleDispatch(unittest.TestCase):
    def _rule(self, rule_id, what):
        def check(targets, ctx):
            return [sc.make_finding(rule_id, "WARN", "REPORT_ONLY", "a.md:1",
                                    what=what, why="y", how="h")]
        return {"category": "stale", "severity": "WARN",
                "action": "REPORT_ONLY", "fn": check}

    def test_a_rule_present_in_the_registry_contributes_its_findings(self):
        rules = {"CA-X001": self._rule("CA-X001", "found")}
        out = sc.run_checks([], {"root": "."}, rules=rules)
        self.assertEqual([f["id"] for f in out], ["CA-X001"])

    def test_rules_are_run_in_identifier_order(self):
        rules = {"CA-X002": self._rule("CA-X002", "b"),
                 "CA-X001": self._rule("CA-X001", "a")}
        out = sc.run_checks([], {"root": "."}, rules=rules)
        self.assertEqual([f["id"] for f in out], ["CA-X001", "CA-X002"])

    def test_a_credential_a_rule_reports_never_reaches_the_returned_findings(self):
        rules = {"CA-X001": self._rule("CA-X001", f"line reads {AWS_KEY}")}
        out = sc.run_checks([], {"root": "."}, rules=rules)
        self.assertNotIn(AWS_KEY, repr(out))


if __name__ == "__main__":
    unittest.main()
