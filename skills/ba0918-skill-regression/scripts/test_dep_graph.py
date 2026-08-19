#!/usr/bin/env python3
"""Unit tests for dep_graph.py.

Covers the behaviour surface of one skill (its own files plus what its markdown
reaches in one hop) and the reverse lookup from changed files to affected skills.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dep_graph

# The self-containment lint reads a literal parent step or a rooted path inside a
# skill directory as an escape, so fixtures needing one assemble it at run time.
PARENT = ".."
OUTSIDE = os.path.join(os.sep, "completely", "outside", "path.md")


def _write(root, rel, content=""):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _repo(root):
    """A minimal test repository: skills a and b both cite a shared contract."""
    _write(root, "skills/a/SKILL.md",
           f"[gate]({PARENT}/shared/references/gate.md) [own](references/own.md)")
    _write(root, "skills/a/references/own.md", "own ref")
    _write(root, "skills/a/references/unlinked.md", "unlinked, still on the surface")
    _write(root, "skills/a/scripts/helper.py", "print('x')")
    _write(root, "skills/a/scripts/test_helper.py", "# test")
    _write(root, "skills/a/scripts/__pycache__/helper.cpython-312.pyc", "bin")
    _write(root, "skills/b/SKILL.md", f"[gate]({PARENT}/shared/references/gate.md)")
    _write(root, "skills/c/SKILL.md", "no links")
    _write(root, "skills/shared/references/gate.md", "contract")


class TestBehaviorSurface(unittest.TestCase):
    def test_includes_skill_dir_files_and_linked_contracts(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            surface = dep_graph.behavior_surface(root, "a")
            self.assertIn("skills/a/SKILL.md", surface)
            self.assertIn("skills/a/references/own.md", surface)
            self.assertIn("skills/a/references/unlinked.md", surface)
            self.assertIn("skills/a/scripts/helper.py", surface)
            self.assertIn("skills/shared/references/gate.md", surface)

    def test_excludes_tests_and_pycache(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            surface = dep_graph.behavior_surface(root, "a")
            self.assertNotIn("skills/a/scripts/test_helper.py", surface)
            self.assertTrue(all("__pycache__" not in p for p in surface), surface)

    def test_sorted_and_deduped(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            surface = dep_graph.behavior_surface(root, "a")
            self.assertEqual(surface, sorted(set(surface)))

    def test_verification_lock_at_the_repository_root_is_not_on_the_surface(self):
        """The lock records verification, not behaviour.

        On the surface it would make every update change the surface it was
        recorded against, so a run would leave its own skill stale again.
        Keeping the lock outside the skill directories is what prevents that,
        with no exclusion list to maintain.
        """
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/a/SKILL.md", "body")
            _write(root, "regression-lock.json", "{}")
            surface = dep_graph.behavior_surface(root, "a")
            self.assertIn("skills/a/SKILL.md", surface)
            self.assertNotIn("regression-lock.json", surface)

    def test_evaluation_assets_are_not_on_the_surface(self):
        """Scenarios live outside the skill directories, so editing one cannot
        make its own skill stale — even when the skill's text names the path."""
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/a/SKILL.md",
                   "Scenarios live at `evals/cases/a/s1.md`")
            _write(root, "evals/cases/a/s1.md", "scenario")
            surface = dep_graph.behavior_surface(root, "a")
            self.assertNotIn("evals/cases/a/s1.md", surface)

    def test_does_not_traverse_out_of_external_files(self):
        # One related-reading link out of a shared contract would otherwise put
        # skills whose execution paths never meet onto the same surface.
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/a/SKILL.md",
                   f"[gate]({PARENT}/shared/references/gate.md)")
            _write(root, "skills/shared/references/gate.md",
                   "related: [pattern](pattern.md)")
            _write(root, "skills/shared/references/pattern.md",
                   f"[unrelated]({PARENT}/{PARENT}/z/SKILL.md)")
            _write(root, "skills/z/SKILL.md", "an unrelated skill")
            surface = dep_graph.behavior_surface(root, "a")
            self.assertIn("skills/shared/references/gate.md", surface)
            self.assertNotIn("skills/shared/references/pattern.md", surface)
            self.assertNotIn("skills/z/SKILL.md", surface)

    def test_own_references_reach_their_direct_contracts(self):
        # A skill's own references are starts, so their one hop is on the surface.
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/a/SKILL.md", "[own](references/own.md)")
            _write(root, "skills/a/references/own.md",
                   f"[gate]({PARENT}/{PARENT}/shared/references/gate.md)")
            _write(root, "skills/shared/references/gate.md", "contract")
            self.assertIn("skills/shared/references/gate.md",
                          dep_graph.behavior_surface(root, "a"))

    def test_bare_path_reference_in_prompt_is_a_dependency(self):
        # Procedural text names a contract as a bare path, not a markdown link.
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/a/SKILL.md",
                   "Prompt: follow `skills/shared/references/tdd-contract.md`")
            _write(root, "skills/shared/references/tdd-contract.md", "contract")
            self.assertIn("skills/shared/references/tdd-contract.md",
                          dep_graph.behavior_surface(root, "a"))

    def test_runtime_artifact_paths_are_not_dependencies(self):
        # A file rewritten at run time would leave the skill permanently stale.
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/a/SKILL.md", "Update `.agents/artifacts/status.md`")
            _write(root, ".agents/artifacts/status.md", "runtime")
            self.assertNotIn(".agents/artifacts/status.md",
                             dep_graph.behavior_surface(root, "a"))

    def test_bare_path_py_reference_is_a_dependency(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/a/SKILL.md",
                   "Run `python3 skills/shared/scripts/checkpoint.py classify`")
            _write(root, "skills/shared/scripts/checkpoint.py", "# script")
            self.assertIn("skills/shared/scripts/checkpoint.py",
                          dep_graph.behavior_surface(root, "a"))

    def test_bare_path_sh_reference_is_a_dependency(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/a/SKILL.md",
                   "Execute `skills/shared/scripts/run.sh`")
            _write(root, "skills/shared/scripts/run.sh", "#!/bin/sh")
            self.assertIn("skills/shared/scripts/run.sh",
                          dep_graph.behavior_surface(root, "a"))

    def test_bare_path_test_py_is_excluded(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/a/SKILL.md",
                   "See `skills/shared/scripts/test_checkpoint.py`")
            _write(root, "skills/shared/scripts/test_checkpoint.py", "# test")
            self.assertNotIn("skills/shared/scripts/test_checkpoint.py",
                             dep_graph.behavior_surface(root, "a"))

    def test_shared_script_change_impacts_referencing_skill(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/a/SKILL.md",
                   "`python3 skills/shared/scripts/checkpoint.py skeleton`")
            _write(root, "skills/shared/scripts/checkpoint.py", "# script")
            _write(root, "skills/b/SKILL.md", "no refs")
            graph = dep_graph.build_graph(root)
            skills, _ = dep_graph.impacted_skills(
                graph, ["skills/shared/scripts/checkpoint.py"], root)
            self.assertEqual(skills, ["a"])

    def test_bare_path_re_matches_py_paths(self):
        matches = dep_graph._BARE_PATH_RE.findall(
            "Run skills/shared/scripts/checkpoint.py to verify")
        self.assertIn("skills/shared/scripts/checkpoint.py", matches)

    def test_bare_path_re_matches_sh_paths(self):
        matches = dep_graph._BARE_PATH_RE.findall("Execute scripts/run.sh for setup")
        self.assertIn("scripts/run.sh", matches)

    def test_bare_path_to_missing_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/a/SKILL.md", "skills/shared/references/nope.md")
            self.assertEqual(dep_graph.behavior_surface(root, "a"),
                             ["skills/a/SKILL.md"])

    def test_python_import_of_shared_module_is_a_dependency(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/a/SKILL.md", "skill body")
            _write(root, "skills/a/scripts/run.py", "import secret_detect\n")
            _write(root, "skills/shared/scripts/secret_detect.py", "# module")
            self.assertIn("skills/shared/scripts/secret_detect.py",
                          dep_graph.behavior_surface(root, "a"))

    def test_python_from_import_of_shared_module_is_a_dependency(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/a/SKILL.md", "skill body")
            _write(root, "skills/a/scripts/run.py",
                   "from frontmatter import parse_frontmatter_lines\n")
            _write(root, "skills/shared/scripts/frontmatter.py", "# module")
            self.assertIn("skills/shared/scripts/frontmatter.py",
                          dep_graph.behavior_surface(root, "a"))

    def test_python_import_alias_is_a_dependency(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/a/SKILL.md", "skill body")
            _write(root, "skills/a/scripts/run.py", "import secret_detect as _sd\n")
            _write(root, "skills/shared/scripts/secret_detect.py", "# module")
            self.assertIn("skills/shared/scripts/secret_detect.py",
                          dep_graph.behavior_surface(root, "a"))

    def test_python_import_of_nonexistent_shared_module_is_ignored(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/a/SKILL.md", "skill body")
            _write(root, "skills/a/scripts/run.py", "import nonexistent\n")
            _write(root, "skills/shared/scripts/secret_detect.py", "# module")
            self.assertNotIn("skills/shared/scripts/nonexistent.py",
                             dep_graph.behavior_surface(root, "a"))

    def test_python_import_does_not_traverse_shared_module_imports(self):
        """Imports between shared modules are not followed — the one-hop rule."""
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/a/SKILL.md", "skill body")
            _write(root, "skills/a/scripts/run.py", "import checkpoint\n")
            _write(root, "skills/shared/scripts/checkpoint.py",
                   "from secret_detect import mask_secrets\n")
            _write(root, "skills/shared/scripts/secret_detect.py", "# module")
            surface = dep_graph.behavior_surface(root, "a")
            self.assertIn("skills/shared/scripts/checkpoint.py", surface)
            self.assertNotIn("skills/shared/scripts/secret_detect.py", surface)

    def test_python_import_in_test_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/a/SKILL.md", "skill body")
            _write(root, "skills/a/scripts/test_run.py", "import secret_detect\n")
            _write(root, "skills/shared/scripts/secret_detect.py", "# module")
            self.assertNotIn("skills/shared/scripts/secret_detect.py",
                             dep_graph.behavior_surface(root, "a"))

    def test_shared_script_import_change_impacts_importing_skill(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "skills/a/SKILL.md", "skill body")
            _write(root, "skills/a/scripts/run.py", "import secret_detect\n")
            _write(root, "skills/shared/scripts/secret_detect.py", "# module")
            _write(root, "skills/b/SKILL.md", "no imports")
            graph = dep_graph.build_graph(root)
            skills, _ = dep_graph.impacted_skills(
                graph, ["skills/shared/scripts/secret_detect.py"], root)
            self.assertEqual(skills, ["a"])

    def test_missing_skill_returns_empty(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            self.assertEqual(dep_graph.behavior_surface(root, "nope"), [])


class TestBuildGraph(unittest.TestCase):
    def test_maps_every_skill_except_shared(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            self.assertEqual(sorted(dep_graph.build_graph(root)), ["a", "b", "c"])

    def test_shared_contract_appears_in_both_dependents(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            graph = dep_graph.build_graph(root)
            for skill in ("a", "b"):
                self.assertIn("skills/shared/references/gate.md", graph[skill])
            self.assertNotIn("skills/shared/references/gate.md", graph["c"])


class TestImpactedSkills(unittest.TestCase):
    def test_shared_contract_change_impacts_all_dependents(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            graph = dep_graph.build_graph(root)
            skills, unresolved = dep_graph.impacted_skills(
                graph, ["skills/shared/references/gate.md"], root)
            self.assertEqual(skills, ["a", "b"])
            self.assertEqual(unresolved, [])

    def test_own_file_change_impacts_only_owner(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            graph = dep_graph.build_graph(root)
            skills, unresolved = dep_graph.impacted_skills(
                graph, ["skills/a/references/unlinked.md"], root)
            self.assertEqual(skills, ["a"])
            self.assertEqual(unresolved, [])

    def test_unrelated_change_impacts_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            graph = dep_graph.build_graph(root)
            skills, unresolved = dep_graph.impacted_skills(graph, ["README.md"], root)
            self.assertEqual(skills, [])
            self.assertEqual(unresolved, [])


class TestPathNormalization(unittest.TestCase):
    """The same file written several ways must yield the same impact result."""

    def test_dot_slash_prefix(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            graph = dep_graph.build_graph(root)
            skills, unresolved = dep_graph.impacted_skills(
                graph, ["./skills/a/SKILL.md"], root)
            self.assertEqual(skills, ["a"])
            self.assertEqual(unresolved, [])

    def test_absolute_path(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            graph = dep_graph.build_graph(root)
            abs_path = os.path.join(root, "skills", "a", "SKILL.md")
            skills, unresolved = dep_graph.impacted_skills(graph, [abs_path], root)
            self.assertEqual(skills, ["a"])
            self.assertEqual(unresolved, [])

    def test_non_normalized_path(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            graph = dep_graph.build_graph(root)
            skills, unresolved = dep_graph.impacted_skills(
                graph, [f"skills/a/{PARENT}/a/SKILL.md"], root)
            self.assertEqual(skills, ["a"])
            self.assertEqual(unresolved, [])

    def test_path_outside_root_is_unresolved(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            graph = dep_graph.build_graph(root)
            skills, unresolved = dep_graph.impacted_skills(graph, [OUTSIDE], root)
            self.assertEqual(skills, [])
            self.assertEqual(unresolved, [OUTSIDE])

    def test_nonexistent_relative_path_resolves(self):
        """A relative path that does not exist is still resolvable, so it is
        simply no impact rather than an unresolved input."""
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            graph = dep_graph.build_graph(root)
            skills, unresolved = dep_graph.impacted_skills(
                graph, ["skills/nope/SKILL.md"], root)
            self.assertEqual(skills, [])
            self.assertEqual(unresolved, [])

    def test_all_variants_return_same_result(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            graph = dep_graph.build_graph(root)
            variants = [
                "skills/a/SKILL.md",
                "./skills/a/SKILL.md",
                os.path.join(root, "skills", "a", "SKILL.md"),
                f"skills/a/{PARENT}/a/SKILL.md",
            ]
            for v in variants:
                skills, _ = dep_graph.impacted_skills(graph, [v], root)
                self.assertEqual(skills, ["a"], f"failed for variant: {v}")


if __name__ == "__main__":
    unittest.main()
