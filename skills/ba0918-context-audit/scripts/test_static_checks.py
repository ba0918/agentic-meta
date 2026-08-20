#!/usr/bin/env python3
"""Unit tests for static_checks.py (the pure-function CA-* rule engine)."""

import importlib.util
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

# The home root as it is spelt inside a project key, where the conversion to the key has
# turned every separator into a hyphen. Assembled for the same reason as the paths above.
HOME_SLUG = "-" + "home"


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

    def test_the_home_a_project_key_spells_with_hyphens_is_redacted(self):
        key = HOME_SLUG + "-someuser-develop-proj"
        finding = sc.make_finding(
            "CA-M101", "WARN", "NEEDS_JUDGMENT",
            f".claude/projects/{key}/memory/note.md:2",
            what="w", why="y", how="h")
        out = sc.finalize_findings([finding])
        self.assertNotIn(HOME_SLUG, out[0]["where"])
        self.assertIn("[REDACTED:home_path]", out[0]["where"])


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


class TestInstallationWideTargets(unittest.TestCase):
    """A file belonging to the installation rather than to the audited project makes no
    claim about that project's tree, so a name it writes is not judged against it: the
    near neighbour such a judgment finds sits in another tree entirely, and offering it
    as a correction would put a fix on a file every project shares."""

    def _root(self, tmp):
        root = Path(tmp)
        (root / "docs").mkdir()
        (root / "docs" / "setup.md").write_text("x", encoding="utf-8")
        return root

    def test_a_reference_written_outside_the_project_is_not_judged_against_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            t = target("global_claude_md", "see [setup](docs/setups.md)",
                       path="outer-claude.md")
            self.assertEqual(findings_for("CA-S001", [t], ctx(root=str(root))), [])

    def test_the_projects_own_file_is_still_judged_when_a_global_one_is_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            outer = target("global_claude_md", "see [setup](docs/setups.md)",
                           path="outer-claude.md")
            own = target("claude_md", "see [setup](docs/setups.md)", path="CLAUDE.md")
            f = findings_for("CA-S001", [outer, own], ctx(root=str(root)))
            self.assertEqual([x["where"] for x in f], ["CLAUDE.md:1"])
            self.assertEqual(f[0]["fix_action"]["path"], "CLAUDE.md")


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

    def test_the_line_an_instruction_file_holds_is_quoted_in_the_finding(self):
        t = target("claude_md", "drop the staging tables without confirmation")
        f = findings_for("CA-U001", [t], ctx())
        self.assertIn("drop the staging tables", f[0]["what"])

    def test_the_line_a_memory_holds_is_reported_without_being_transcribed(self):
        t = target("memory", "---\nname: n\ndescription: d\n---\n"
                             "drop the acmecorp tables without confirmation",
                   path="n.md")
        f = findings_for("CA-U001", [t], ctx())
        self.assertEqual(len(f), 1)
        self.assertIn("n.md:5", f[0]["where"])
        self.assertNotIn("acmecorp", repr(f))


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


class TestContradictionCandidatePairing(unittest.TestCase):
    """Claims are grouped by the subjects they name and paired only inside a group,
    so the scan does not grow with the square of the number of claims."""

    def _claim(self, path, polarity, subjects):
        return sc.Claim(path, 1, polarity, frozenset(subjects), "text")

    def test_claims_are_grouped_by_the_subjects_they_name(self):
        claims = [self._claim("a.md", "prohibit", {"テス", "スト"}),
                  self._claim("b.md", "allow", {"テス", "実行"}),
                  self._claim("c.md", "allow", {"独立"})]
        grouped = sc.index_claims_by_subject(claims)
        self.assertEqual(sorted(grouped["テス"]), [0, 1])
        self.assertEqual(grouped["独立"], [2])

    def test_only_claims_naming_a_subject_in_common_are_ever_paired(self):
        claims = [self._claim("a.md", "prohibit", {"aa", "bb"}),
                  self._claim("b.md", "allow", {"aa", "bb"}),
                  self._claim("c.md", "allow", {"zz"})]
        self.assertEqual(sc.candidate_pairs(claims), {(0, 1)})


class TestContradictionCandidates(unittest.TestCase):
    # Japanese input on purpose: the polarity vocabulary this rule reads is the
    # vocabulary instruction files are written in, and translating it removes the
    # coverage these cases exist for.

    def test_a_prohibition_and_a_permission_over_one_subject_become_a_candidate(self):
        a = target("claude_md", "テストをスキップしてよい", path="a.md")
        b = target("rules", "テストをスキップするな", path="b.md")
        f = findings_for("CA-C001", [a, b], ctx())
        self.assertTrue(f)
        self.assertEqual(f[0]["action"], "REPORT_ONLY")

    def test_two_claims_pointing_the_same_way_do_not_become_a_candidate(self):
        a = target("claude_md", "テストをスキップするな", path="a.md")
        b = target("rules", "テストをスキップしてはならない", path="b.md")
        self.assertEqual(findings_for("CA-C001", [a, b], ctx()), [])

    def test_claims_with_no_subject_in_common_do_not_become_a_candidate(self):
        a = target("claude_md", "テストをスキップしてよい", path="a.md")
        b = target("rules", "コミットは日本語で書くな", path="b.md")
        self.assertEqual(findings_for("CA-C001", [a, b], ctx()), [])

    def test_claims_whose_subjects_only_partly_overlap_still_become_a_candidate(self):
        a = target("claude_md", "main ブランチへの直接コミットを禁止する", path="a.md")
        b = target("rules", "軽微な修正は main に直接コミットしてよい", path="b.md")
        f = findings_for("CA-C001", [a, b], ctx())
        self.assertTrue(f)
        self.assertEqual(f[0]["action"], "REPORT_ONLY")

    def test_a_candidate_names_where_both_claims_were_written(self):
        a = target("claude_md", "テストをスキップしてよい", path="a.md")
        b = target("rules", "テストをスキップするな", path="b.md")
        f = findings_for("CA-C001", [a, b], ctx())
        self.assertIn("a.md:1", f[0]["where"])
        self.assertIn("b.md:1", f[0]["where"])


class TestContradictionCandidateFromAMemory(unittest.TestCase):
    """A candidate pair may mix a memory's line with an instruction file's. The
    memory's line is the one nobody reviews, and the finding it lands in is what the
    contradiction reading receives, so only the memory's side is held back."""

    def _pair(self):
        memory = target("memory", "---\nname: n\ndescription: d\n---\n"
                                  "deploying to acmecorp hosts is always allowed",
                        path="n.md")
        instruction = target("claude_md", "never deploy to those hosts", path="a.md")
        return findings_for("CA-C001", [memory, instruction], ctx())

    def test_the_memorys_line_is_not_transcribed_into_the_candidate(self):
        f = self._pair()
        self.assertEqual(len(f), 1)
        self.assertNotIn("acmecorp", repr(f))

    def test_the_instruction_files_line_is_kept_rather_than_dropped_with_it(self):
        self.assertIn("never deploy to those hosts", self._pair()[0]["what"])

    def test_the_withheld_side_still_carries_its_place_and_its_direction(self):
        f = self._pair()
        self.assertIn("n.md:5", f[0]["where"])
        self.assertIn("permission", f[0]["what"])
        self.assertIn("prohibition", f[0]["what"])


class TestContradictionPolarityInEnglish(unittest.TestCase):
    """An instruction file written in English negates in two places — the modal
    (`must not`, `can't`) and the predicate (`is not allowed`) — so which way those
    point decides whether this rule works at all on a repository whose instruction
    files are English."""

    def test_a_prohibition_written_as_a_negated_modal_is_not_read_as_a_permission(self):
        a = target("agents_md", "Never delete the cache directory", path="a.md")
        b = target("rules", "You should not delete the cache directory", path="b.md")
        self.assertEqual(findings_for("CA-C001", [a, b], ctx()), [])

    def test_a_prohibition_written_with_must_not_still_pairs_with_a_permission(self):
        a = target("agents_md", "You must not commit directly to main", path="a.md")
        b = target("rules", "Committing directly to main is always allowed", path="b.md")
        self.assertTrue(findings_for("CA-C001", [a, b], ctx()))

    def test_a_prohibition_written_as_a_contraction_pairs_with_a_permission(self):
        a = target("agents_md", "You shouldn't run the migration by hand", path="a.md")
        b = target("rules", "Running the migration by hand is always allowed",
                   path="b.md")
        self.assertTrue(findings_for("CA-C001", [a, b], ctx()))

    def test_a_prohibition_written_as_cannot_pairs_with_a_permission(self):
        a = target("agents_md", "The build directory cannot be edited by hand",
                   path="a.md")
        b = target("rules", "Editing the build directory by hand is always allowed",
                   path="b.md")
        self.assertTrue(findings_for("CA-C001", [a, b], ctx()))

    # One case per contraction: the spellings are irregular (`can't` is not `can` plus
    # `n't`), so a single case standing in for all of them leaves the others unread.

    def test_a_prohibition_written_as_cant_pairs_with_a_permission(self):
        a = target("agents_md", "You can't commit directly to the main branch",
                   path="a.md")
        b = target("rules", "Committing directly to the main branch is always allowed",
                   path="b.md")
        self.assertTrue(findings_for("CA-C001", [a, b], ctx()))

    def test_a_prohibition_written_as_wont_pairs_with_a_permission(self):
        a = target("agents_md", "You won't rewrite the release notes by hand",
                   path="a.md")
        b = target("rules", "Rewriting the release notes by hand is always allowed",
                   path="b.md")
        self.assertTrue(findings_for("CA-C001", [a, b], ctx()))

    def test_a_prohibition_written_as_shant_pairs_with_a_permission(self):
        a = target("agents_md", "You shan't deploy the release on a Friday", path="a.md")
        b = target("rules", "Deploying the release on a Friday is always allowed",
                   path="b.md")
        self.assertTrue(findings_for("CA-C001", [a, b], ctx()))

    # The other way English negates: the predicate carries the negation, so the
    # affirmative word sits after it rather than inside it.

    def test_a_prohibition_written_as_a_negated_predicate_pairs_with_a_permission(self):
        a = target("agents_md", "Committing directly to main is not allowed", path="a.md")
        b = target("rules", "Committing directly to main is always allowed", path="b.md")
        self.assertTrue(findings_for("CA-C001", [a, b], ctx()))

    def test_a_prohibition_written_as_a_negated_predicate_is_not_read_as_a_permission(self):
        a = target("agents_md", "Never commit directly to main", path="a.md")
        b = target("rules", "Committing directly to main is not allowed", path="b.md")
        self.assertEqual(findings_for("CA-C001", [a, b], ctx()), [])

    def test_a_prohibition_written_as_a_negated_permission_pairs_with_a_permission(self):
        a = target("agents_md", "Direct commits to main are not permitted", path="a.md")
        b = target("rules", "Direct commits to main are always allowed", path="b.md")
        self.assertTrue(findings_for("CA-C001", [a, b], ctx()))


class TestMemoryFrontmatterShape(unittest.TestCase):
    def test_a_memory_missing_a_required_key_is_left_to_a_human(self):
        t = target("memory", "---\ndescription: a note\n---\nbody", path="note.md")
        f = findings_for("CA-M001", [t], ctx())
        self.assertTrue(any(x["action"] == "NEEDS_JUDGMENT" for x in f))
        self.assertTrue(any("name" in x["what"] for x in f))

    def test_a_missing_key_is_never_supplied_automatically(self):
        t = target("memory", "---\ndescription: a note\n---\nbody", path="note.md")
        f = [x for x in findings_for("CA-M001", [t], ctx()) if "name" in x["what"]]
        self.assertIsNone(f[0]["fix_action"])

    def test_a_key_written_without_the_canonical_spacing_is_fixed_automatically(self):
        t = target("memory", "---\nname:note\ndescription: a note\n---\nbody",
                   path="note.md")
        f = [x for x in findings_for("CA-M001", [t], ctx()) if x["action"] == "AUTO_FIX"]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["fix_action"]["old"], "name:note")
        self.assertEqual(f[0]["fix_action"]["new"], "name: note")

    def test_the_automatic_fix_names_only_the_frontmatter_line_it_normalises(self):
        body = "name:not-frontmatter"
        t = target("memory", f"---\nname:note\ndescription: a note\n---\n{body}",
                   path="note.md")
        f = [x for x in findings_for("CA-M001", [t], ctx()) if x["action"] == "AUTO_FIX"]
        self.assertEqual([x["fix_action"]["old"] for x in f], ["name:note"])

    def test_an_unknown_memory_type_is_left_to_a_human(self):
        t = target("memory", "---\nname: n\ndescription: d\ntype: invented\n---\nbody",
                   path="note.md")
        f = [x for x in findings_for("CA-M001", [t], ctx()) if "type" in x["what"]]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["action"], "NEEDS_JUDGMENT")

    def _leaky(self):
        # What a memory accumulates while nobody reviews it: a customer's name and an
        # internal hostname, sitting in an entry that also misses the canonical spacing.
        return target("memory",
                      "---\nname: n\ndescription:   acmecorp internal-db-01 note\n"
                      "---\nbody", path="n.md")

    def _canonical_form_finding(self, memory):
        found = [x for x in findings_for("CA-M001", [memory], ctx())
                 if x["action"] == "AUTO_FIX"]
        self.assertEqual(len(found), 1)
        return found[0]

    def test_the_entry_a_memory_holds_is_named_without_its_value_being_transcribed(self):
        f = self._canonical_form_finding(self._leaky())
        self.assertIn("description", f["what"])
        described = " ".join(f[key] for key in ("where", "what", "why", "how"))
        self.assertNotIn("acmecorp", described)
        self.assertNotIn("internal-db-01", described)

    def test_the_fix_offered_still_carries_the_line_it_would_replace(self):
        fix = self._canonical_form_finding(self._leaky())["fix_action"]
        self.assertEqual(fix["old"], "description:   acmecorp internal-db-01 note")
        self.assertEqual(fix["new"], "description: acmecorp internal-db-01 note")

    def test_the_type_a_memory_names_is_not_transcribed_into_the_finding(self):
        t = target("memory", "---\nname: n\ndescription: d\ntype: acmecorp-session\n"
                             "---\nbody", path="n.md")
        f = [x for x in findings_for("CA-M001", [t], ctx()) if "type" in x["what"]]
        self.assertEqual(len(f), 1)
        self.assertNotIn("acmecorp", repr(f))
        self.assertIn("reference", f[0]["how"])  # the known types the fix may choose from

    def test_a_memory_written_in_the_expected_form_is_not_reported(self):
        t = target("memory", "---\nname: note\ndescription: a note\ntype: reference\n"
                             "---\nbody", path="note.md")
        self.assertEqual(findings_for("CA-M001", [t], ctx()), [])

    def test_a_file_carrying_no_frontmatter_block_is_not_reported(self):
        t = target("memory", "just a body with no frontmatter", path="note.md")
        self.assertEqual(findings_for("CA-M001", [t], ctx()), [])


class TestMemoryReference(unittest.TestCase):
    def test_a_path_a_memory_names_that_is_not_there_is_left_to_a_human(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = target("memory", "---\nname: n\ndescription: d\n---\n"
                                 "see `skills/ghost/SKILL.md`", path="n.md")
            f = findings_for("CA-M101", [t], ctx(root=tmp))
            self.assertEqual(len(f), 1)
            self.assertEqual(f[0]["action"], "NEEDS_JUDGMENT")

    def test_a_path_a_memory_names_is_never_rewritten_automatically(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = target("memory", "---\nname: n\ndescription: d\n---\n"
                                 "see `skills/ghost/SKILL.md`", path="n.md")
            f = findings_for("CA-M101", [t], ctx(root=tmp))
            self.assertIsNone(f[0]["fix_action"])

    def test_the_path_a_memory_names_is_not_transcribed_into_the_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = target("memory", "---\nname: n\ndescription: d\n---\n"
                                 "see `docs/acmecorp/migration-runbook.md`", path="n.md")
            f = findings_for("CA-M101", [t], ctx(root=tmp))
            self.assertEqual(len(f), 1)
            self.assertIn("n.md:5", f[0]["where"])
            self.assertNotIn("acmecorp", repr(f))

    def test_a_path_a_memory_names_that_exists_is_not_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "docs").mkdir()
            (Path(tmp) / "docs" / "real.md").write_text("x", encoding="utf-8")
            t = target("memory", "---\nname: n\ndescription: d\n---\n"
                                 "see `docs/real.md`", path="n.md")
            self.assertEqual(findings_for("CA-M101", [t], ctx(root=tmp)), [])


class TestMemorySecretSuspicion(unittest.TestCase):
    def _memory(self, body):
        return target("memory", f"---\nname: n\ndescription: d\n---\n{body}",
                      path="n.md")

    def test_a_suspected_credential_is_reported_and_nothing_is_changed(self):
        f = findings_for("CA-M301", [self._memory(f"aws key {AWS_KEY}")], ctx())
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["severity"], "BLOCK")
        self.assertEqual(f[0]["action"], "REPORT_ONLY")
        self.assertIsNone(f[0]["fix_action"])

    def test_the_detected_value_never_reaches_the_finding(self):
        produced = sc.run_checks([self._memory(f"aws key {AWS_KEY}")], ctx())
        self.assertNotIn(AWS_KEY, repr(produced))

    def test_personal_data_is_reported_one_step_below_a_credential(self):
        f = findings_for("CA-M301", [self._memory("mail alice" + "@" + "example.com")],
                         ctx())
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["severity"], "WARN")
        self.assertIn("personal data", f[0]["what"])

    def test_a_line_holding_both_takes_the_heavier_severity(self):
        f = findings_for(
            "CA-M301", [self._memory(f"{AWS_KEY} mail a" + "@" + "b.co")], ctx())
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["severity"], "BLOCK")

    def test_one_kind_found_several_times_on_a_line_is_reported_once(self):
        f = findings_for("CA-M301", [self._memory(f"{AWS_KEY} and {AWS_KEY}")], ctx())
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["what"].count("aws_key"), 1)

    def test_a_memory_holding_no_such_pattern_is_not_reported(self):
        self.assertEqual(findings_for("CA-M301", [self._memory("an ordinary note")],
                                      ctx()), [])


class TestEngineOutput(unittest.TestCase):
    def test_every_finding_the_engine_produces_carries_the_required_fields(self):
        t = target("claude_md", "確認なしで rm -rf を実行してよい")
        produced = sc.run_checks([t], ctx())
        self.assertTrue(produced)
        for f in produced:
            self.assertEqual(sc.validate_finding_schema(f), [], f["id"])
            self.assertIn(":", f["where"])


class TestEmittedOutput(unittest.TestCase):
    """What the engine writes out is the only place downstream can learn which checks
    ran, so a clean report can be told apart from a check that never happened."""

    def test_the_output_names_the_checks_that_ran(self):
        with tempfile.TemporaryDirectory() as work:
            targets = Path(work) / "targets.json"
            targets.write_text(json.dumps({"targets": [
                {"path": os.path.join(work, "CLAUDE.md"), "rel": "CLAUDE.md",
                 "kind": "claude_md", "category": "instruction",
                 "content": "ordinary prose"}]}), encoding="utf-8")
            out = Path(work) / "findings.json"
            sc.main([str(targets), "--root", work, "--output", str(out)])
            emitted = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(emitted["rules_run"], sorted(sc.RULES))


class TestRegistry(unittest.TestCase):
    def test_every_rule_the_audit_defines_is_listed(self):
        self.assertEqual(set(sc.RULES), {
            "CA-S001", "CA-S002", "CA-U001", "CA-D001", "CA-D002",
            "CA-C001", "CA-M001", "CA-M101", "CA-M301"})

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

    def test_the_checks_reported_as_run_are_the_ones_that_were_dispatched(self):
        """Not the registry read back: what a run is asked for and what it did are two
        statements, and only the second can report a rule that was listed and skipped."""
        rules = {"CA-X002": self._rule("CA-X002", "b"),
                 "CA-X001": self._rule("CA-X001", "a")}
        audited = sc.run_audit([], {"root": "."}, rules=rules)
        self.assertEqual(audited["rules_run"], ["CA-X001", "CA-X002"])
        self.assertEqual([f["id"] for f in audited["findings"]],
                         ["CA-X001", "CA-X002"])


if __name__ == "__main__":
    unittest.main()
