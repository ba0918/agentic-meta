"""Tests for vendor.py generation: digest normalization, declaration parsing,
vendor expansion, and manifest output."""

import pytest

import vendor


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
