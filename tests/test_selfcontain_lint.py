"""Tests for vendor.py lint-selfcontain: every skills/<name>/ directory must be
self-contained — no path reference above the skill directory, no absolute
filesystem path."""

import vendor


def lint(tree, capsys):
    """Run lint-selfcontain and return (exit_code, list of violation lines)."""
    exit_code = vendor.main(["lint-selfcontain", "--root", str(tree)])
    lines = [line for line in capsys.readouterr().out.splitlines() if line]
    return exit_code, lines


class TestSelfContainLint:
    def test_a_clean_tree_passes_with_zero_violations(self, copy_tree, capsys):
        exit_code, lines = lint(copy_tree("contracts-basic/good"), capsys)
        assert exit_code == 0
        assert lines == []

    def test_a_parent_directory_reference_is_detected(self, copy_tree, capsys):
        tree = copy_tree("contracts-basic/good")
        offender = tree / "skills/note-taker/notes.md"
        offender.write_text(
            "See [the shared rules](../shared/rules.md) for details.\n",
            encoding="utf-8",
        )
        exit_code, lines = lint(tree, capsys)
        assert exit_code == 1
        assert any(
            line.startswith("parent-escape:") and "notes.md" in line for line in lines
        )

    def test_an_absolute_path_reference_is_detected(self, copy_tree, capsys):
        tree = copy_tree("contracts-basic/good")
        offender = tree / "skills/note-taker/notes.md"
        offender.write_text(
            "Credentials live in /etc/app/config.yaml on the host.\n",
            encoding="utf-8",
        )
        exit_code, lines = lint(tree, capsys)
        assert exit_code == 1
        assert any(
            line.startswith("absolute-path:") and "notes.md" in line for line in lines
        )

    def test_a_home_directory_reference_is_detected(self, copy_tree, capsys):
        tree = copy_tree("contracts-basic/good")
        offender = tree / "skills/note-taker/notes.md"
        offender.write_text("Load [config](~/app/config.md) first.\n", encoding="utf-8")
        exit_code, lines = lint(tree, capsys)
        assert exit_code == 1
        assert any(line.startswith("absolute-path:") for line in lines)

    def test_a_windows_drive_reference_is_detected(self, copy_tree, capsys):
        tree = copy_tree("contracts-basic/good")
        offender = tree / "skills/note-taker/notes.md"
        offender.write_text("Logs are under C:\\app\\logs\\run.txt today.\n", encoding="utf-8")
        exit_code, lines = lint(tree, capsys)
        assert exit_code == 1
        assert any(line.startswith("absolute-path:") for line in lines)

    def test_a_shebang_line_is_not_treated_as_a_path_reference(self, copy_tree, capsys):
        tree = copy_tree("contracts-basic/good")
        script = tree / "skills/note-taker/scripts/run.py"
        script.parent.mkdir(parents=True)
        script.write_text(
            '#!/usr/bin/env python3\nprint("self-contained")\n', encoding="utf-8"
        )
        exit_code, lines = lint(tree, capsys)
        assert exit_code == 0
        assert lines == []

    def test_a_url_is_not_treated_as_a_path_reference(self, copy_tree, capsys):
        tree = copy_tree("contracts-basic/good")
        offender = tree / "skills/note-taker/notes.md"
        offender.write_text(
            "See [the docs](https://example.com/guide/setup) for setup.\n",
            encoding="utf-8",
        )
        exit_code, lines = lint(tree, capsys)
        assert exit_code == 0
        assert lines == []

    def test_a_symlink_resolving_outside_the_skill_directory_is_detected(
        self, copy_tree, capsys
    ):
        tree = copy_tree("contracts-basic/good")
        outside = tree / "shared-notes.md"
        outside.write_text("central notes\n", encoding="utf-8")
        (tree / "skills/note-taker/notes.md").symlink_to(outside)
        exit_code, lines = lint(tree, capsys)
        assert exit_code == 1
        assert any(
            line.startswith("symlink-escape:") and "notes.md" in line for line in lines
        )

    def test_a_symlink_resolving_inside_the_same_skill_directory_passes(
        self, copy_tree, capsys
    ):
        tree = copy_tree("contracts-basic/good")
        real = tree / "skills/note-taker/notes.md"
        real.write_text("notes\n", encoding="utf-8")
        (tree / "skills/note-taker/alias.md").symlink_to(real)
        exit_code, lines = lint(tree, capsys)
        assert exit_code == 0
        assert lines == []

    def test_files_outside_skill_directories_are_not_linted(self, copy_tree, capsys):
        tree = copy_tree("contracts-basic/good")
        outside = tree / "notes-outside-skills.md"
        outside.write_text("Central docs may reference ../anything.\n", encoding="utf-8")
        exit_code, lines = lint(tree, capsys)
        assert exit_code == 0
        assert lines == []


class TestSkillsetFixturesAreSelfContained:
    def test_the_standard_layout_skillset_passes_with_zero_violations(
        self, copy_tree, capsys
    ):
        exit_code, lines = lint(copy_tree("skillset-alpha"), capsys)
        assert exit_code == 0
        assert lines == []

    def test_the_heterogeneous_skillset_with_a_bundled_script_passes_too(
        self, copy_tree, capsys
    ):
        exit_code, lines = lint(copy_tree("skillset-beta"), capsys)
        assert exit_code == 0
        assert lines == []
