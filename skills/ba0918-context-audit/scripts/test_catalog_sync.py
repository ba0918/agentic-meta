#!/usr/bin/env python3
"""Guard against the rule catalog and the rule registry drifting apart.

references/rule-catalog.md and the RULES registry of static_checks.py both state what
each CA-* rule is, so either can be edited without the other. This test parses the
catalog table and holds the identifier, category, severity and fix action of every rule
against the registry, so the two cannot diverge unnoticed.
"""

import importlib.util
import os
import re
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


sc = _load("ba0918_context_audit_static_checks_for_catalog", "static_checks.py")

CATALOG = Path(__file__).resolve().parent.parent / "references" / "rule-catalog.md"

_ROW = re.compile(r"^\|\s*(CA-[A-Z0-9]+)\s*\|(.+)\|\s*$")


def parse_catalog(path):
    """Read the rule rows of the catalog table as identifier to stated fields."""
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _ROW.match(line)
        if not match:
            continue
        cells = [cell.strip() for cell in match.group(2).split("|")]
        rows[match.group(1)] = {
            "category": cells[0], "severity": cells[1], "action": cells[2],
        }
    return rows


class TestCatalogSync(unittest.TestCase):
    def test_the_catalog_the_registry_is_held_against_is_present(self):
        self.assertTrue(CATALOG.is_file())

    def test_the_catalog_lists_exactly_the_rules_the_registry_carries(self):
        self.assertEqual(set(parse_catalog(CATALOG)), set(sc.RULES))

    def test_each_rule_is_given_the_same_category_severity_and_fix_in_both(self):
        catalog = parse_catalog(CATALOG)
        for rule_id, registered in sc.RULES.items():
            self.assertIn(rule_id, catalog)
            for field in ("category", "severity", "action"):
                self.assertEqual(catalog[rule_id][field], registered[field],
                                 f"{rule_id} {field}")


if __name__ == "__main__":
    unittest.main()
