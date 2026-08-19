#!/usr/bin/env python3
"""Target-resolution tests for collect_descriptions.py against the repository's
heterogeneous fixture skill trees.

The synthetic trees under `.fixtures/` differ from one another on purpose --
directory vocabulary, naming style and frontmatter shape -- so collecting from
both is what shows the collector reads an unfamiliar tree rather than one
lucky layout. `expected-skills.json` at each fixture root is the
evaluation-side ground truth the fixture contract defines.
"""

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import collect_descriptions as cd

# scripts -> ba0918-trigger-eval -> skills -> repository root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_FIXTURES = _REPO_ROOT / ".fixtures"


# These cases verify the collector against this repository's own fixture trees, so
# they need the repository around them. A standalone copy of the skill has no
# `.fixtures/`; there the cases skip with that reason rather than failing, which is
# the same degrade-and-say-so the skill itself applies to a missing dependency.
_needs_repository_fixtures = unittest.skipUnless(
    _FIXTURES.is_dir(),
    "repository fixtures absent - these cases verify the collector against this "
    "repository's own trees",
)


def _skill_dir(fixture: str) -> Path:
    d = _FIXTURES / fixture / "skills"
    if not d.is_dir():
        raise AssertionError(f"fixture skill directory missing: {d}")
    return d


def _declared_names(fixture: str) -> list[str]:
    declaration = _FIXTURES / fixture / "expected-skills.json"
    if not declaration.is_file():
        raise AssertionError(f"fixture declaration missing: {declaration}")
    return json.loads(declaration.read_text(encoding="utf-8"))["skills"]


@_needs_repository_fixtures
class TestStandardLayoutFixture(unittest.TestCase):
    def test_reads_every_skill_with_its_description(self):
        skills = cd.collect_from_dir(_skill_dir("skillset-alpha"))
        self.assertEqual(
            {s["name"]: s["description"] for s in skills},
            {
                "acme-notes": (
                    "Synthetic fixture skill for taking notes; declares no contracts."
                ),
                "acme-review": (
                    "Synthetic fixture skill that reviews work and writes handoff notes."
                ),
            },
        )


@_needs_repository_fixtures
class TestHeterogeneousLayoutFixture(unittest.TestCase):
    def setUp(self):
        self.skills = cd.collect_from_dir(_skill_dir("skillset-beta"))
        self.by_name = {s["name"]: s["description"] for s in self.skills}

    def test_reads_a_dotted_skill_name_unchanged(self):
        self.assertIn("obscure.oracle", self.by_name)

    def test_prefers_the_frontmatter_name_over_the_directory_basename(self):
        self.assertIn("pipeline.runner", self.by_name)
        self.assertNotIn("pipeline_runner", self.by_name)

    def test_reads_a_description_declared_before_the_name(self):
        self.assertEqual(
            self.by_name["obscure.oracle"],
            "A contract-free heterogeneous fixture skill with a dotted name.",
        )

    def test_reads_a_description_surrounded_by_unrelated_frontmatter_keys(self):
        self.assertEqual(
            self.by_name["pipeline.runner"],
            "Heterogeneous fixture skill bundling a script and a sample log.",
        )

    def test_ignores_markdown_siblings_of_skill_md(self):
        self.assertNotIn("HOWTO", self.by_name)
        self.assertEqual(len(self.skills), 2)


@_needs_repository_fixtures
class TestAgreementWithFixtureDeclaration(unittest.TestCase):
    """The fixture contract judges a run complete when the skills reported match
    the declaration exactly, counted with multiplicity."""

    def test_standard_layout_matches_its_declaration(self):
        skills = cd.collect_from_dir(_skill_dir("skillset-alpha"))
        self.assertEqual(
            sorted(s["name"] for s in skills),
            sorted(_declared_names("skillset-alpha")),
        )

    def test_heterogeneous_layout_matches_its_declaration(self):
        skills = cd.collect_from_dir(_skill_dir("skillset-beta"))
        self.assertEqual(
            sorted(s["name"] for s in skills),
            sorted(_declared_names("skillset-beta")),
        )


if __name__ == "__main__":
    unittest.main()
