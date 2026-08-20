#!/usr/bin/env python3
"""Unit tests for static_checks.py (the pure-function CA-* rule engine)."""

import importlib.util
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


def target(kind, content, path="x.md", category=None):
    if category is None:
        category = "memory" if kind == "memory" else "instruction"
    return {"path": path, "rel": path, "kind": kind, "category": category,
            "content": content}


def ctx(root=".", skill_names=None):
    return {"root": root, "skill_names": set(skill_names or [])}


def findings_for(rule_id, targets, context):
    return [f for f in sc.run_checks(targets, context) if f["id"] == rule_id]


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


class TestStaleFileReference(unittest.TestCase):
    def _root(self, tmp):
        root = Path(tmp)
        (root / "references").mkdir()
        (root / "references" / "foo.md").write_text("x", encoding="utf-8")
        return root

    def test_a_reference_to_a_file_that_exists_is_not_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            t = target("claude_md", "see [foo](references/foo.md) here")
            self.assertEqual(findings_for("CA-S001", [t], ctx(root=str(root))), [])

    def test_a_misspelling_with_one_near_neighbour_is_offered_as_an_automatic_fix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            t = target("claude_md", "see [foo](references/foow.md) here")
            f = findings_for("CA-S001", [t], ctx(root=str(root)))
            self.assertEqual(len(f), 1)
            self.assertEqual(f[0]["action"], "AUTO_FIX")
            self.assertEqual(f[0]["fix_action"]["new"], "references/foo.md")

    def test_a_reference_with_no_near_neighbour_is_left_to_a_human(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            t = target("claude_md", "see [x](nope/gone.md) here")
            f = findings_for("CA-S001", [t], ctx(root=str(root)))
            self.assertEqual(len(f), 1)
            self.assertEqual(f[0]["action"], "NEEDS_JUDGMENT")
            self.assertIsNone(f[0]["fix_action"])

    def test_a_placeholder_standing_in_for_a_generated_name_is_not_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            t = target("claude_md", "see `.agents/artifacts/plans/{timestamp}_{slug}.md`")
            self.assertEqual(findings_for("CA-S001", [t], ctx(root=str(root))), [])

    def test_a_bare_filename_carrying_no_separator_is_not_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            t = target("claude_md", "see [x](gone.md) here")
            self.assertEqual(findings_for("CA-S001", [t], ctx(root=str(root))), [])

    def test_a_directory_named_in_a_code_span_is_read_as_prose_not_a_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            t = target("claude_md", "each skill has a `nonexistent-dir/` layout")
            self.assertEqual(findings_for("CA-S001", [t], ctx(root=str(root))), [])

    def test_a_code_span_whose_name_exists_elsewhere_is_read_as_shorthand(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            (root / "tools").mkdir()
            (root / "tools" / "collect.py").write_text("x", encoding="utf-8")
            t = target("claude_md", "see `ghostdir/collect.py` for details")
            self.assertEqual(findings_for("CA-S001", [t], ctx(root=str(root))), [])

    def test_a_code_span_naming_a_file_found_nowhere_in_the_tree_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            t = target("claude_md", "the specification is in `docs/spec.md`")
            f = findings_for("CA-S001", [t], ctx(root=str(root)))
            self.assertEqual(len(f), 1)
            self.assertEqual(f[0]["action"], "NEEDS_JUDGMENT")

    def test_a_code_span_anchored_to_a_real_directory_with_a_missing_leaf_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            t = target("claude_md", "see `references/gone.md` for details")
            self.assertEqual(len(findings_for("CA-S001", [t], ctx(root=str(root)))), 1)

    def test_a_markdown_link_to_a_missing_directory_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            t = target("claude_md", "see [dir](nonexistent-dir/) here")
            self.assertEqual(len(findings_for("CA-S001", [t], ctx(root=str(root)))), 1)


class TestStaleSkillReference(unittest.TestCase):
    def test_a_reference_to_a_skill_directory_that_is_not_there_is_left_to_a_human(self):
        t = target("claude_md", "the `skills/ghostskill/` directory does things")
        f = findings_for("CA-S002", [t], ctx(skill_names={"plan", "commit"}))
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["action"], "NEEDS_JUDGMENT")

    def test_a_reference_to_a_skill_directory_that_exists_is_not_reported(self):
        t = target("claude_md", "the skills/plan/ directory")
        self.assertEqual(findings_for("CA-S002", [t], ctx(skill_names={"plan"})), [])

    def test_the_directory_skills_share_is_not_read_as_a_missing_skill(self):
        t = target("claude_md", "helpers live in `skills/shared/scripts/`")
        self.assertEqual(findings_for("CA-S002", [t], ctx(skill_names={"plan"})), [])


class TestUnsafeVocabulary(unittest.TestCase):
    def test_wording_that_permits_a_forced_push_without_confirming_is_reported(self):
        t = target("claude_md", "always use `git push --force` without confirmation")
        f = findings_for("CA-U001", [t], ctx())
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["action"], "REPORT_ONLY")

    def test_wording_that_permits_deleting_without_confirming_is_reported(self):
        # Japanese input on purpose: this rule reads instruction files written in the
        # language their author used, and translating the input removes the coverage.
        t = target("claude_md", "確認なしで削除してよい")
        self.assertEqual(len(findings_for("CA-U001", [t], ctx())), 1)

    def test_ordinary_prose_is_not_reported(self):
        t = target("claude_md", "write clear and helpful documentation")
        self.assertEqual(findings_for("CA-U001", [t], ctx()), [])

    def test_one_line_holding_several_such_phrases_is_reported_once(self):
        t = target("claude_md", "rm -rf without confirmation and --force too")
        self.assertEqual(len(findings_for("CA-U001", [t], ctx())), 1)


class TestToolVocabularyDrift(unittest.TestCase):
    def test_a_runtime_specific_tool_name_in_the_behaviour_file_is_reported(self):
        t = target("agents_md", "use the `Edit` tool to change the file", path="AGENTS.md")
        f = findings_for("CA-D001", [t], ctx())
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["action"], "REPORT_ONLY")

    def test_a_runtime_specific_tool_name_in_the_project_context_file_is_reported(self):
        t = target("project_md", "use the `Edit` tool to change the file", path="PROJECT.md")
        f = findings_for("CA-D001", [t], ctx())
        self.assertEqual(len(f), 1)
        self.assertIn("PROJECT.md", f[0]["where"])

    def test_the_same_tool_name_in_the_runtime_own_file_is_not_reported(self):
        t = target("claude_md", "use the `Edit` tool", path="CLAUDE.md")
        self.assertEqual(findings_for("CA-D001", [t], ctx()), [])

    def test_the_japanese_wording_naming_a_tool_is_reported_as_well(self):
        # Japanese input on purpose: 「Edit ツール」 is the wording this rule exists to
        # catch, and translating it deletes the coverage.
        t = target("agents_md", "ファイル修正には Edit ツールと Write ツールを使うこと",
                   path="AGENTS.md")
        f = findings_for("CA-D001", [t], ctx())
        self.assertTrue(f)
        self.assertIn("Edit", f[0]["what"])

    def test_one_line_naming_several_tools_is_reported_once(self):
        t = target("agents_md", "use the `Edit` tool then `Write` the file", path="AGENTS.md")
        self.assertEqual(len(findings_for("CA-D001", [t], ctx())), 1)


class TestSkillListingCoverage(unittest.TestCase):
    def test_a_skill_missing_from_the_instruction_files_is_left_to_a_human(self):
        t = target("claude_md", "we have the plan skill documented")
        f = findings_for("CA-D002", [t], ctx(skill_names={"plan", "commit"}))
        self.assertEqual(len(f), 1)
        self.assertIn("commit", f[0]["what"])
        self.assertEqual(f[0]["action"], "NEEDS_JUDGMENT")

    def test_a_name_appearing_only_inside_a_longer_word_is_not_a_mention(self):
        t = target("claude_md", "we are planning things")
        f = findings_for("CA-D002", [t], ctx(skill_names={"plan"}))
        self.assertTrue(any("plan" in x["what"] for x in f))

    def test_a_repository_validation_script_does_not_change_what_is_reported(self):
        def reported(with_script):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "skills" / "plan").mkdir(parents=True)
                (root / "skills" / "commit").mkdir(parents=True)
                if with_script:
                    (root / "scripts").mkdir()
                    (root / "scripts" / "validate_repo.py").write_text("x", encoding="utf-8")
                t = target("claude_md", "we have the plan skill documented")
                context = sc.build_context(str(root), [t])
                return [x["what"] for x in findings_for("CA-D002", [t], context)]

        self.assertTrue(reported(with_script=True))
        self.assertEqual(reported(with_script=True), reported(with_script=False))


class TestEngineOutput(unittest.TestCase):
    def test_every_finding_the_engine_produces_carries_the_required_fields(self):
        t = target("claude_md", "確認なしで rm -rf を実行してよい")
        produced = sc.run_checks([t], ctx())
        self.assertTrue(produced)
        for f in produced:
            self.assertEqual(sc.validate_finding_schema(f), [], f["id"])
            self.assertIn(":", f["where"])


class TestRegistry(unittest.TestCase):
    def test_every_listed_rule_declares_its_category_severity_action_and_function(self):
        for rule_id, meta in sc.RULES.items():
            self.assertIn("category", meta, rule_id)
            self.assertIn("severity", meta, rule_id)
            self.assertIn("action", meta, rule_id)
            self.assertTrue(callable(meta["fn"]), rule_id)


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
