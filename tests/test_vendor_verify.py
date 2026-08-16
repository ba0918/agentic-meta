"""Tests for vendor.py verify: the six checks that keep vendored copies,
declarations, canonical contracts, conformance tests, and the manifest
mutually consistent — plus the discovery of contract conformance tests."""

import shutil
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


class TestConformanceLock:
    """Conformance tests are pinned by the manifest lock: any divergence
    between the locked digest and the current conformance content is its own
    violation kind, distinct from a hand-edited manifest."""

    def test_editing_a_conformance_test_is_reported_as_conformance_mismatch(
        self, copy_tree, capsys
    ):
        tree = copy_tree("contracts-basic/good")
        test_file = (
            tree
            / "contracts/report-format/conformance/test_report_format_conformance.py"
        )
        test_file.write_text(
            test_file.read_text(encoding="utf-8") + "\n# weakened\n",
            encoding="utf-8",
        )
        exit_code, kinds = verify_kinds(tree, capsys)
        assert exit_code == 1
        assert kinds == {"conformance-mismatch"}

    def test_adding_a_conformance_test_file_is_reported_as_conformance_mismatch(
        self, copy_tree, capsys
    ):
        tree = copy_tree("contracts-basic/good")
        added = tree / "contracts/report-format/conformance/test_added.py"
        added.write_text("def test_added():\n    assert True\n", encoding="utf-8")
        exit_code, kinds = verify_kinds(tree, capsys)
        assert exit_code == 1
        assert kinds == {"conformance-mismatch"}

    def test_deleting_a_conformance_test_file_is_reported_as_conformance_mismatch(
        self, copy_tree, capsys
    ):
        tree = copy_tree("contracts-basic/good")
        (
            tree
            / "contracts/report-format/conformance/test_report_format_conformance.py"
        ).unlink()
        exit_code, kinds = verify_kinds(tree, capsys)
        assert exit_code == 1
        assert kinds == {"conformance-mismatch"}

    def test_removing_the_whole_conformance_directory_is_reported(
        self, copy_tree, capsys
    ):
        tree = copy_tree("contracts-basic/good")
        shutil.rmtree(tree / "contracts/report-format/conformance")
        exit_code, kinds = verify_kinds(tree, capsys)
        assert exit_code == 1
        assert kinds == {"conformance-mismatch"}

    def test_a_contract_gaining_unlocked_conformance_tests_is_reported(
        self, copy_tree, capsys
    ):
        tree = copy_tree("contracts-basic/good")
        conformance_dir = tree / "contracts/changelog-entry/conformance"
        conformance_dir.mkdir(parents=True)
        (conformance_dir / "test_new.py").write_text(
            "def test_new():\n    assert True\n", encoding="utf-8"
        )
        exit_code, kinds = verify_kinds(tree, capsys)
        assert exit_code == 1
        assert kinds == {"conformance-mismatch"}

    def test_bytecode_caches_do_not_affect_conformance_verification(
        self, copy_tree, capsys
    ):
        # Running the conformance tests drops __pycache__ next to them; that
        # byproduct must not count as a conformance change.
        tree = copy_tree("contracts-basic/good")
        cache = tree / "contracts/report-format/conformance/__pycache__"
        cache.mkdir(exist_ok=True)
        (cache / "test_report_format_conformance.cpython-312.pyc").write_bytes(
            b"\x00fake bytecode"
        )
        exit_code, kinds = verify_kinds(tree, capsys)
        assert exit_code == 0
        assert kinds == set()


class TestConfigurationErrors:
    def test_a_malformed_declaration_makes_the_cli_exit_with_code_2(
        self, copy_tree, capsys
    ):
        tree = copy_tree("contracts-basic/good")
        skill_md = tree / "skills/report-writer/SKILL.md"
        skill_md.write_text(
            skill_md.read_text(encoding="utf-8").replace("digest:", "checksum:"),
            encoding="utf-8",
        )
        exit_code = vendor.main(["verify", "--root", str(tree)])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert captured.err.startswith("error:")
        assert captured.out == ""

    def test_an_unreadable_contract_file_makes_the_cli_exit_with_code_2(
        self, copy_tree, capsys
    ):
        # A directory where a contract file is expected raises OSError on
        # read; that must surface as a loud configuration error, not a crash.
        tree = copy_tree("contracts-basic/good")
        (tree / "contracts/weird.md").mkdir()
        exit_code = vendor.main(["verify", "--root", str(tree)])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert captured.err.startswith("error:")
        assert "weird.md" in captured.err


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
