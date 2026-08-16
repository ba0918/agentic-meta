"""Tests for vendor.py verify: the five checks that keep vendored copies,
declarations, canonical contracts, and the manifest mutually consistent —
plus the discovery of contract conformance tests."""

import subprocess
import sys

import vendor


def verify_kinds(tree, capsys):
    """Run verify and return (exit_code, set of violation kinds reported)."""
    exit_code = vendor.main(["verify", "--root", str(tree)])
    lines = [line for line in capsys.readouterr().out.splitlines() if line]
    return exit_code, {line.split(":", 1)[0] for line in lines}


class TestVerify:
    def test_a_freshly_generated_tree_verifies_clean(self, copy_tree, capsys):
        exit_code, kinds = verify_kinds(copy_tree("contracts-basic/good"), capsys)
        assert exit_code == 0
        assert kinds == set()

    def test_a_hand_edited_vendor_copy_is_reported_as_drift(self, copy_tree, capsys):
        exit_code, kinds = verify_kinds(copy_tree("contracts-basic/bad-drift"), capsys)
        assert exit_code == 1
        assert kinds == {"drift"}

    def test_a_vendor_file_no_declaration_accounts_for_is_reported_as_extra(
        self, copy_tree, capsys
    ):
        exit_code, kinds = verify_kinds(copy_tree("contracts-basic/bad-extra"), capsys)
        assert exit_code == 1
        assert kinds == {"extra"}

    def test_an_orphan_vendor_copy_under_a_skill_without_skill_md_is_extra(
        self, copy_tree, capsys
    ):
        tree = copy_tree("contracts-basic/good")
        orphan = tree / "skills/removed-skill/references/vendor/report-format.md"
        orphan.parent.mkdir(parents=True)
        orphan.write_text("left over after a skill removal\n", encoding="utf-8")
        exit_code, kinds = verify_kinds(tree, capsys)
        assert exit_code == 1
        assert kinds == {"extra"}

    def test_a_non_markdown_file_inside_the_vendor_directory_is_extra(
        self, copy_tree, capsys
    ):
        tree = copy_tree("contracts-basic/good")
        stray = tree / "skills/report-writer/references/vendor/notes.txt"
        stray.write_text("stray\n", encoding="utf-8")
        exit_code, kinds = verify_kinds(tree, capsys)
        assert exit_code == 1
        assert kinds == {"extra"}

    def test_a_subdirectory_inside_the_vendor_directory_is_extra(
        self, copy_tree, capsys
    ):
        tree = copy_tree("contracts-basic/good")
        (tree / "skills/report-writer/references/vendor/cache").mkdir()
        exit_code, kinds = verify_kinds(tree, capsys)
        assert exit_code == 1
        assert kinds == {"extra"}

    def test_a_declared_contract_without_a_canonical_file_is_a_closure_error(
        self, copy_tree, capsys
    ):
        exit_code, kinds = verify_kinds(
            copy_tree("contracts-basic/bad-missing-contract"), capsys
        )
        assert exit_code == 1
        assert "closure" in kinds

    def test_a_declared_digest_that_differs_from_the_canonical_is_reported(
        self, copy_tree, capsys
    ):
        exit_code, kinds = verify_kinds(copy_tree("contracts-basic/bad-digest"), capsys)
        assert exit_code == 1
        assert kinds == {"digest-mismatch"}

    def test_a_hand_edited_manifest_is_reported_as_a_manifest_mismatch(
        self, copy_tree, capsys
    ):
        exit_code, kinds = verify_kinds(
            copy_tree("contracts-basic/bad-manifest"), capsys
        )
        assert exit_code == 1
        assert kinds == {"manifest"}

    def test_a_missing_manifest_is_reported_as_a_manifest_mismatch(
        self, copy_tree, capsys
    ):
        tree = copy_tree("contracts-basic/good")
        (tree / "vendor-manifest.json").unlink()
        exit_code, kinds = verify_kinds(tree, capsys)
        assert exit_code == 1
        assert kinds == {"manifest"}

    def test_a_missing_vendor_copy_is_reported_as_drift(self, copy_tree, capsys):
        tree = copy_tree("contracts-basic/good")
        (tree / "skills/report-writer/references/vendor/report-format.md").unlink()
        exit_code, kinds = verify_kinds(tree, capsys)
        assert exit_code == 1
        assert kinds == {"drift"}


class TestConformanceDiscovery:
    def test_contract_conformance_tests_are_discovered_and_run_by_pytest(
        self, fixtures_dir
    ):
        conformance_dir = (
            fixtures_dir / "contracts-basic/good/contracts/report-format/conformance"
        )
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", str(conformance_dir), "-q"],
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0
        assert "3 passed" in completed.stdout


class TestSkillsetFixturesVerifyClean:
    def test_the_standard_layout_skillset_verifies_clean(self, copy_tree, capsys):
        exit_code, kinds = verify_kinds(copy_tree("skillset-alpha"), capsys)
        assert exit_code == 0
        assert kinds == set()

    def test_the_heterogeneous_skillset_verifies_clean(self, copy_tree, capsys):
        exit_code, kinds = verify_kinds(copy_tree("skillset-beta"), capsys)
        assert exit_code == 0
        assert kinds == set()
