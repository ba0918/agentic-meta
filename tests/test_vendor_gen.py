"""Tests for vendor.py generation: digest normalization, declaration parsing,
vendor expansion, and manifest output."""

import json
from pathlib import Path

import pytest

import vendor

GOOD_TREE = "contracts-basic/good"


def tree_snapshot(root: Path) -> dict:
    """Byte content of every generated artifact in a tree."""
    files = sorted(root.rglob("references/vendor/*.md"))
    files.append(root / "vendor-manifest.json")
    return {str(f.relative_to(root)): f.read_bytes() for f in files if f.exists()}


class TestCanonicalDigest:
    def test_digest_excludes_frontmatter_and_the_blank_lines_after_it(self):
        with_frontmatter = "---\nid: x\nversion: 1.0.0\n---\n\nBody line\n"
        without_frontmatter = "Body line\n"
        assert vendor.contract_digest(with_frontmatter) == vendor.contract_digest(
            without_frontmatter
        )

    def test_digest_treats_crlf_and_lf_endings_as_the_same_content(self):
        assert vendor.contract_digest("Body line\r\nNext\r\n") == vendor.contract_digest(
            "Body line\nNext\n"
        )

    def test_digest_normalizes_trailing_newlines_to_exactly_one(self):
        assert vendor.contract_digest("Body line\n\n\n") == vendor.contract_digest(
            "Body line\n"
        )

    def test_digest_matches_the_documented_reference_value_for_the_fixture(
        self, fixtures_dir
    ):
        text = (
            fixtures_dir / "contracts-basic/good/contracts/changelog-entry.md"
        ).read_text(encoding="utf-8")
        assert (
            vendor.contract_digest(text)
            == "sha256:50c256ff60e9960bc01d4fe385bcb7c31604fbf1585394c5be22ae610f122c70"
        )

    def test_digest_preserves_inner_trailing_whitespace(self):
        # Per-line trimming is deliberately not part of the normalization;
        # only line endings and EOF are canonicalized.
        assert vendor.contract_digest("Body line  \n") != vendor.contract_digest(
            "Body line\n"
        )


class TestContractIdValidation:
    @pytest.mark.parametrize(
        "contract_id",
        ["report-format", "a", "log.v2", "x_1-y", "0start"],
    )
    def test_accepts_well_formed_ids(self, contract_id):
        assert vendor.is_valid_contract_id(contract_id)

    @pytest.mark.parametrize(
        "contract_id",
        [
            "../evil",
            "a/b",
            "a\\b",
            "/absolute",
            "Upper",
            ".hidden",
            "-dash-start",
            "a..b",
            "",
            "x" * 65,
        ],
    )
    def test_rejects_ids_that_could_escape_or_break_paths(self, contract_id):
        assert not vendor.is_valid_contract_id(contract_id)


class TestDeclarationParsing:
    def test_reads_id_and_digest_pairs_in_declaration_order(self, fixtures_dir):
        text = (
            fixtures_dir / "contracts-basic/good/skills/report-writer/SKILL.md"
        ).read_text(encoding="utf-8")
        declarations = vendor.parse_declarations(text)
        assert [d.id for d in declarations] == ["report-format", "changelog-entry"]
        assert all(d.digest.startswith("sha256:") for d in declarations)

    def test_a_skill_without_contract_metadata_declares_nothing(self, fixtures_dir):
        text = (
            fixtures_dir / "contracts-basic/good/skills/note-taker/SKILL.md"
        ).read_text(encoding="utf-8")
        assert vendor.parse_declarations(text) == []

    def test_a_declaration_entry_missing_its_digest_is_a_configuration_error(self):
        text = (
            "---\n"
            "name: broken\n"
            "metadata:\n"
            "  contracts:\n"
            "    - id: report-format\n"
            "---\n"
        )
        with pytest.raises(vendor.DeclarationError):
            vendor.parse_declarations(text)

    def test_a_malformed_digest_string_is_a_configuration_error(self):
        text = (
            "---\n"
            "name: broken\n"
            "metadata:\n"
            "  contracts:\n"
            "    - id: report-format\n"
            "      digest: not-a-digest\n"
            "---\n"
        )
        with pytest.raises(vendor.DeclarationError):
            vendor.parse_declarations(text)

    def test_declaring_the_same_contract_id_twice_is_a_configuration_error(self):
        entry = (
            "    - id: report-format\n"
            "      digest: sha256:" + "0" * 64 + "\n"
        )
        text = "---\nname: broken\nmetadata:\n  contracts:\n" + entry + entry + "---\n"
        with pytest.raises(vendor.DeclarationError):
            vendor.parse_declarations(text)

    def test_a_duplicate_key_within_one_entry_is_a_configuration_error(self):
        text = (
            "---\n"
            "name: broken\n"
            "metadata:\n"
            "  contracts:\n"
            "    - id: report-format\n"
            "      digest: sha256:" + "0" * 64 + "\n"
            "      digest: sha256:" + "1" * 64 + "\n"
            "---\n"
        )
        with pytest.raises(vendor.DeclarationError):
            vendor.parse_declarations(text)

    def test_a_flow_style_contracts_list_is_a_configuration_error(self):
        text = (
            "---\n"
            "name: broken\n"
            "metadata:\n"
            "  contracts: [{id: report-format, digest: sha256:" + "0" * 64 + "}]\n"
            "---\n"
        )
        with pytest.raises(vendor.DeclarationError):
            vendor.parse_declarations(text)

    def test_a_contracts_item_at_the_contracts_key_indent_is_a_configuration_error(
        self,
    ):
        text = (
            "---\n"
            "name: broken\n"
            "metadata:\n"
            "  contracts:\n"
            "  - id: report-format\n"
            "    digest: sha256:" + "0" * 64 + "\n"
            "---\n"
        )
        with pytest.raises(vendor.DeclarationError):
            vendor.parse_declarations(text)

    def test_metadata_children_indented_four_spaces_do_not_silently_drop_pins(self):
        text = (
            "---\n"
            "name: broken\n"
            "metadata:\n"
            "    contracts:\n"
            "        - id: report-format\n"
            "          digest: sha256:" + "0" * 64 + "\n"
            "---\n"
        )
        with pytest.raises(vendor.DeclarationError):
            vendor.parse_declarations(text)

    def test_a_trailing_comment_on_metadata_does_not_silently_drop_pins(self):
        text = (
            "---\n"
            "name: broken\n"
            "metadata: # pinned dependencies\n"
            "  contracts:\n"
            "    - id: report-format\n"
            "      digest: sha256:" + "0" * 64 + "\n"
            "---\n"
        )
        with pytest.raises(vendor.DeclarationError):
            vendor.parse_declarations(text)

    def test_an_invalid_contract_id_in_a_declaration_is_a_configuration_error(self):
        text = (
            "---\n"
            "name: broken\n"
            "metadata:\n"
            "  contracts:\n"
            "    - id: ../escape\n"
            "      digest: sha256:" + "0" * 64 + "\n"
            "---\n"
        )
        with pytest.raises(vendor.DeclarationError):
            vendor.parse_declarations(text)


class TestGen:
    def test_generating_twice_from_the_same_input_is_byte_identical(self, copy_tree):
        first = copy_tree(GOOD_TREE)
        assert vendor.main(["gen", "--root", str(first)]) == 0
        snapshot_one = tree_snapshot(first)
        assert vendor.main(["gen", "--root", str(first)]) == 0
        snapshot_two = tree_snapshot(first)
        assert snapshot_one and snapshot_one == snapshot_two

    def test_vendor_files_carry_do_not_edit_header_id_version_and_source_digest(
        self, copy_tree
    ):
        tree = copy_tree(GOOD_TREE)
        vendor.main(["gen", "--root", str(tree)])
        content = (
            tree / "skills/report-writer/references/vendor/report-format.md"
        ).read_text(encoding="utf-8")
        assert "DO NOT EDIT" in content
        assert "report-format" in content
        assert "1.2.0" in content
        assert (
            "sha256:017156e79c2eb67bef20f8615994b02a1c78ce97d4d10f6ec51ca398a0d6f111"
            in content
        )

    def test_vendor_files_contain_the_canonical_contract_body(self, copy_tree):
        tree = copy_tree(GOOD_TREE)
        vendor.main(["gen", "--root", str(tree)])
        source = (tree / "contracts/report-format.md").read_text(encoding="utf-8")
        generated = (
            tree / "skills/report-writer/references/vendor/report-format.md"
        ).read_text(encoding="utf-8")
        assert vendor.canonical_body(source) in generated

    def test_manifest_separates_lock_from_provenance(self, copy_tree):
        tree = copy_tree(GOOD_TREE)
        vendor.main(["gen", "--root", str(tree)])
        manifest = json.loads((tree / "vendor-manifest.json").read_text(encoding="utf-8"))
        assert set(manifest) == {"lock", "provenance"}
        locked = manifest["lock"]["skills"]["report-writer"]
        assert {entry["id"] for entry in locked} == {"report-format", "changelog-entry"}
        assert all(set(entry) == {"id", "version", "digest"} for entry in locked)
        provenance = manifest["provenance"]
        assert provenance["contracts"]["report-format"]["source"] == (
            "contracts/report-format.md"
        )
        assert "generator_version" in provenance

    def test_manifest_locks_a_conformance_digest_for_contracts_shipping_tests(
        self, copy_tree
    ):
        tree = copy_tree(GOOD_TREE)
        vendor.main(["gen", "--root", str(tree)])
        manifest = json.loads((tree / "vendor-manifest.json").read_text(encoding="utf-8"))
        conformance = manifest["lock"]["conformance"]
        # report-format ships conformance tests; changelog-entry does not and
        # is therefore omitted from the map.
        assert set(conformance) == {"report-format"}
        assert conformance["report-format"].startswith("sha256:")

    def test_manifest_records_no_wall_clock_timestamp(self, copy_tree):
        # Reproducibility is the property the manifest guarantees; a
        # generated_at field would make regeneration differ by run time.
        tree = copy_tree(GOOD_TREE)
        vendor.main(["gen", "--root", str(tree)])
        assert "generated_at" not in (tree / "vendor-manifest.json").read_text(
            encoding="utf-8"
        )

    def test_gen_refuses_when_a_declared_digest_does_not_match_the_canonical(
        self, copy_tree, capsys
    ):
        tree = copy_tree(GOOD_TREE)
        skill_md = tree / "skills/report-writer/SKILL.md"
        skill_md.write_text(
            skill_md.read_text(encoding="utf-8").replace(
                "sha256:017156e79c2eb67bef20f8615994b02a1c78ce97d4d10f6ec51ca398a0d6f111",
                "sha256:" + "0" * 64,
            ),
            encoding="utf-8",
        )
        assert vendor.main(["gen", "--root", str(tree)]) == 1
        assert "digest-mismatch" in capsys.readouterr().out

    def test_gen_leaves_the_tree_byte_untouched_when_it_rejects_a_digest_mismatch(
        self, copy_tree
    ):
        tree = copy_tree(GOOD_TREE)
        skill_md = tree / "skills/report-writer/SKILL.md"
        skill_md.write_text(
            skill_md.read_text(encoding="utf-8").replace(
                "sha256:017156e79c2eb67bef20f8615994b02a1c78ce97d4d10f6ec51ca398a0d6f111",
                "sha256:" + "0" * 64,
            ),
            encoding="utf-8",
        )
        before = tree_snapshot(tree)
        assert vendor.main(["gen", "--root", str(tree)]) == 1
        assert tree_snapshot(tree) == before

    def test_gen_exits_with_code_2_when_a_vendor_target_cannot_be_written(
        self, copy_tree, capsys
    ):
        # A directory sitting where a vendor copy must be written raises
        # OSError; that must surface as a loud configuration error naming the
        # path, not a crash.
        tree = copy_tree(GOOD_TREE)
        target = tree / "skills/report-writer/references/vendor/report-format.md"
        target.unlink()
        target.mkdir()
        exit_code = vendor.main(["gen", "--root", str(tree)])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert captured.err.startswith("error:")
        assert "report-format.md" in captured.err

    def test_gen_refuses_a_vendor_dir_symlinked_to_an_external_directory(
        self, copy_tree, tmp_path, capsys
    ):
        # Reproduced escape: following the symlink would delete the external
        # directory's files; gen must refuse instead and leave them intact.
        tree = copy_tree(GOOD_TREE)
        external = tmp_path / "external"
        external.mkdir()
        precious = external / "precious.md"
        precious.write_text("do not delete\n", encoding="utf-8")
        vendor_dir = tree / "skills/note-taker/references/vendor"
        vendor_dir.parent.mkdir(parents=True)
        vendor_dir.symlink_to(external, target_is_directory=True)
        exit_code = vendor.main(["gen", "--root", str(tree)])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert captured.err.startswith("error:")
        assert precious.exists()
        assert precious.read_text(encoding="utf-8") == "do not delete\n"

    def test_gen_refuses_a_vendor_dir_symlinked_to_an_empty_external_directory(
        self, copy_tree, tmp_path, capsys
    ):
        # An empty target yields no per-entry checks, so the vendor directory
        # itself must be refused, not only its entries.
        tree = copy_tree(GOOD_TREE)
        external = tmp_path / "external-empty"
        external.mkdir()
        vendor_dir = tree / "skills/note-taker/references/vendor"
        vendor_dir.parent.mkdir(parents=True)
        vendor_dir.symlink_to(external, target_is_directory=True)
        exit_code = vendor.main(["gen", "--root", str(tree)])
        assert exit_code == 2
        assert capsys.readouterr().err.startswith("error:")

    def test_gen_refuses_a_skill_directory_that_is_a_symlink(
        self, copy_tree, tmp_path, capsys
    ):
        tree = copy_tree(GOOD_TREE)
        external = tmp_path / "external-skill"
        external.mkdir()
        (external / "SKILL.md").write_text("---\nname: evil\n---\nBody\n", encoding="utf-8")
        (tree / "skills/linked").symlink_to(external, target_is_directory=True)
        exit_code = vendor.main(["gen", "--root", str(tree)])
        assert exit_code == 2
        assert capsys.readouterr().err.startswith("error:")

    def test_gen_refuses_a_stale_vendor_entry_that_is_a_symlink(
        self, copy_tree, tmp_path, capsys
    ):
        tree = copy_tree(GOOD_TREE)
        external_file = tmp_path / "external-note.md"
        external_file.write_text("external content\n", encoding="utf-8")
        link = tree / "skills/report-writer/references/vendor/stray-link.md"
        link.symlink_to(external_file)
        exit_code = vendor.main(["gen", "--root", str(tree)])
        assert exit_code == 2
        assert capsys.readouterr().err.startswith("error:")
        assert external_file.read_text(encoding="utf-8") == "external content\n"

    def test_gen_removes_vendor_files_no_declaration_accounts_for(self, copy_tree):
        tree = copy_tree(GOOD_TREE)
        stale = tree / "skills/note-taker/references/vendor/stale.md"
        stale.parent.mkdir(parents=True)
        stale.write_text("left over\n", encoding="utf-8")
        vendor.main(["gen", "--root", str(tree)])
        assert not stale.exists()

    def test_an_interrupted_gen_loses_no_pre_existing_file(
        self, copy_tree, monkeypatch, capsys
    ):
        # Deletions must come last and writes must be atomic: a failure on the
        # very first write leaves every pre-existing file in place, including
        # a stale vendor copy that a completed run would have removed.
        tree = copy_tree(GOOD_TREE)
        stale = tree / "skills/note-taker/references/vendor/stale.md"
        stale.parent.mkdir(parents=True)
        stale.write_text("left over\n", encoding="utf-8")
        before = tree_snapshot(tree)

        def failing_write(path, content):
            raise OSError(f"simulated mid-write failure at {path}")

        monkeypatch.setattr(vendor, "_write_atomic", failing_write)
        assert vendor.main(["gen", "--root", str(tree)]) == 2
        assert capsys.readouterr().err.startswith("error:")
        assert stale.read_text(encoding="utf-8") == "left over\n"
        assert tree_snapshot(tree) == before

    def test_verify_flags_the_state_left_by_a_mid_write_failure(
        self, copy_tree, monkeypatch, capsys
    ):
        # A gen interrupted between vendor writes and the manifest write must
        # leave a state verify reports, never a silently half-updated tree.
        tree = copy_tree(GOOD_TREE)
        contract = tree / "contracts/report-format.md"
        contract.write_text(
            contract.read_text(encoding="utf-8") + "\nA new requirement.\n",
            encoding="utf-8",
        )
        new_digest = vendor.contract_digest(contract.read_text(encoding="utf-8"))
        skill_md = tree / "skills/report-writer/SKILL.md"
        skill_md.write_text(
            skill_md.read_text(encoding="utf-8").replace(
                "sha256:017156e79c2eb67bef20f8615994b02a1c78ce97d4d10f6ec51ca398a0d6f111",
                new_digest,
            ),
            encoding="utf-8",
        )
        real_write = vendor._write_atomic
        calls = []

        def flaky_write(path, content):
            calls.append(path)
            if len(calls) == 2:
                raise OSError(f"simulated mid-write failure at {path}")
            real_write(path, content)

        monkeypatch.setattr(vendor, "_write_atomic", flaky_write)
        assert vendor.main(["gen", "--root", str(tree)]) == 2
        capsys.readouterr()
        assert vendor.main(["verify", "--root", str(tree)]) == 1

    def test_gen_removes_orphan_vendor_artifacts_so_verify_passes_afterwards(
        self, copy_tree
    ):
        tree = copy_tree(GOOD_TREE)
        orphan = tree / "skills/removed-skill/references/vendor/old.md"
        orphan.parent.mkdir(parents=True)
        orphan.write_text("left over after a skill removal\n", encoding="utf-8")
        stray = tree / "skills/report-writer/references/vendor/notes.txt"
        stray.write_text("stray\n", encoding="utf-8")
        subdir = tree / "skills/report-writer/references/vendor/cache"
        subdir.mkdir()
        (subdir / "cached.md").write_text("cached\n", encoding="utf-8")
        assert vendor.main(["gen", "--root", str(tree)]) == 0
        assert not orphan.exists()
        assert not stray.exists()
        assert not subdir.exists()
        assert vendor.main(["verify", "--root", str(tree)]) == 0
