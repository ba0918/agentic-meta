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

    def test_gen_removes_vendor_files_no_declaration_accounts_for(self, copy_tree):
        tree = copy_tree(GOOD_TREE)
        stale = tree / "skills/note-taker/references/vendor/stale.md"
        stale.parent.mkdir(parents=True)
        stale.write_text("left over\n", encoding="utf-8")
        vendor.main(["gen", "--root", str(tree)])
        assert not stale.exists()
