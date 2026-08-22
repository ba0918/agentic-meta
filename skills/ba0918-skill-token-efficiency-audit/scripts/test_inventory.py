import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


INVENTORY_PATH = Path(__file__).with_name("inventory.py")
SPEC = importlib.util.spec_from_file_location(
    "ba0918_skill_token_efficiency_inventory", INVENTORY_PATH
)
assert SPEC is not None and SPEC.loader is not None
inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_resolution_uses_first_nonempty_layer(tmp_path):
    write(tmp_path / "skills" / "chosen" / "SKILL.md", "---\nname: chosen\n---\n")
    write(tmp_path / "SKILL.md", "---\nname: root\n---\n")
    assert [item["name"] for item in inventory.resolve_skills(tmp_path)] == ["chosen"]


def test_resolution_falls_through_a_hidden_only_conventional_layer(tmp_path):
    write(tmp_path / "skills" / ".hidden" / "SKILL.md", "---\nname: hidden\n---\n")
    write(tmp_path / "SKILL.md", "---\nname: root\n---\n")

    assert [item["name"] for item in inventory.resolve_skills(tmp_path)] == ["root"]


def test_resolution_falls_through_an_escaping_only_conventional_layer(tmp_path):
    outside = tmp_path.parent / "outside-skill.md"
    write(outside, "---\nname: outside\n---\n")
    (tmp_path / "skills" / "linked").mkdir(parents=True)
    (tmp_path / "skills" / "linked" / "SKILL.md").symlink_to(outside)
    write(tmp_path / "SKILL.md", "---\nname: root\n---\n")

    assert [item["name"] for item in inventory.resolve_skills(tmp_path)] == ["root"]


def test_resolution_falls_through_a_conventional_candidate_that_becomes_a_symlink_loop(
    tmp_path, monkeypatch
):
    linked_skill = tmp_path / "skills" / "linked" / "SKILL.md"
    write(linked_skill, "must not be read\n")
    root_skill = tmp_path / "SKILL.md"
    write(root_skill, "---\nname: root\n---\n")
    reads = []
    original_read = Path.read_text
    original_glob = Path.glob

    def record_read(path, *args, **kwargs):
        reads.append(path)
        return original_read(path, *args, **kwargs)

    def introduce_loop_after_discovery(path, pattern):
        candidates = list(original_glob(path, pattern))
        if path == tmp_path / "skills" and pattern == "*/SKILL.md":
            linked_skill.unlink()
            linked_skill.symlink_to("SKILL.md")
        return iter(candidates)

    monkeypatch.setattr(Path, "read_text", record_read)
    monkeypatch.setattr(Path, "glob", introduce_loop_after_discovery)

    assert [item["name"] for item in inventory.resolve_skills(tmp_path)] == ["root"]
    assert reads == [root_skill]


def test_resolution_falls_through_a_candidate_with_a_file_status_error(
    tmp_path, monkeypatch
):
    linked_skill = tmp_path / "skills" / "linked" / "SKILL.md"
    write(linked_skill, "must not be read\n")
    root_skill = tmp_path / "SKILL.md"
    write(root_skill, "---\nname: root\n---\n")
    reads = []
    original_read = Path.read_text
    original_resolve = Path.resolve

    def record_read(path, *args, **kwargs):
        reads.append(path)
        return original_read(path, *args, **kwargs)

    def fail_link_resolution(path, *args, **kwargs):
        if path == linked_skill:
            raise OSError("bad link")
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", record_read)
    monkeypatch.setattr(Path, "resolve", fail_link_resolution)

    assert [item["name"] for item in inventory.resolve_skills(tmp_path)] == ["root"]
    assert reads == [root_skill]


def test_resolution_supports_root_sibling_recursive_and_colliding_names(tmp_path):
    write(tmp_path / "SKILL.md", "---\nname: root\n---\n")
    assert inventory.resolve_skills(tmp_path)[0]["name"] == "root"
    os.unlink(tmp_path / "SKILL.md")
    write(tmp_path / "a" / "SKILL.md", "---\nname: same\n---\n")
    write(tmp_path / "b" / "SKILL.md", "---\nname: same\n---\n")
    resolved = inventory.resolve_skills(tmp_path)
    assert len(resolved) == 2 and len({x["path"] for x in resolved}) == 2
    for directory in (tmp_path / "a", tmp_path / "b"):
        os.unlink(directory / "SKILL.md")
    write(tmp_path / "deep" / "nested" / "SKILL.md", "body")
    assert inventory.resolve_skills(tmp_path)[0]["name"] == "nested"
    assert inventory.resolve_skills(tmp_path)[0]["frontmatter"] == "absent"


def test_resolution_reports_invalid_frontmatter_and_uses_directory_name(tmp_path):
    write(tmp_path / "broken" / "SKILL.md", "---\nnot a mapping\n---\n")
    resolved = inventory.resolve_skills(tmp_path)
    assert [(item["name"], item["frontmatter"]) for item in resolved] == [("broken", "invalid")]


def test_frontmatter_reads_plain_comments_and_quoted_scalar_characters(tmp_path):
    write(
        tmp_path / "plain" / "SKILL.md",
        "---\n# metadata comment\nname: actual # display comment\ndescription: plain value # comment\n---\n",
    )
    resolved = inventory.resolve_skills(tmp_path)
    assert resolved[0]["name"] == "actual"
    assert resolved[0]["description"] == "plain value"

    os.unlink(tmp_path / "plain" / "SKILL.md")
    write(
        tmp_path / "quoted" / "SKILL.md",
        "---\nname: 'quoted: # name'\ndescription: \"literal: # description\"\n---\n",
    )
    resolved = inventory.resolve_skills(tmp_path)
    assert resolved[0]["name"] == "quoted: # name"
    assert resolved[0]["description"] == "literal: # description"


def test_frontmatter_reads_folded_and_literal_block_scalars(tmp_path):
    write(
        tmp_path / "folded" / "SKILL.md",
        "---\nname: folded\ndescription: > # prose\n  first line\n  second line\n\n  third line\n---\n",
    )
    resolved = inventory.resolve_skills(tmp_path)
    assert resolved[0]["description"] == "first line second line\nthird line\n"

    os.unlink(tmp_path / "folded" / "SKILL.md")
    write(
        tmp_path / "literal" / "SKILL.md",
        "---\nname: literal\ndescription: |\n  first line\n  second line\n---\n",
    )
    resolved = inventory.resolve_skills(tmp_path)
    assert resolved[0]["description"] == "first line\nsecond line\n"


def test_frontmatter_ignores_unrelated_nested_metadata(tmp_path):
    write(
        tmp_path / "nested" / "SKILL.md",
        "---\nname: top-level\nmetadata:\n  name: nested\n  tags: [one, two]\ndescription: usable\n---\n",
    )

    resolved = inventory.resolve_skills(tmp_path)
    assert (resolved[0]["name"], resolved[0]["description"], resolved[0]["frontmatter"]) == (
        "top-level",
        "usable",
        "parsed",
    )


@pytest.mark.parametrize(
    ("frontmatter", "observation"),
    [
        ('name: "unterminated', "invalid"),
        ("name: |\nnot-indented", "invalid"),
        ("name: [oops", "invalid"),
        ("name: [oops]]", "invalid"),
        ("name: actual: invalid", "invalid"),
        ("name: |0", "invalid"),
        ("name: > foo", "invalid"),
        ("name: ,reserved", "invalid"),
        ("name: ]reserved", "invalid"),
        ("name: %reserved", "invalid"),
        ("name: [one, two]", "unsupported"),
        ("name: |2\n  value", "unsupported"),
        ("name: null", "unsupported"),
        ("name: true", "unsupported"),
        ("name: 123", "unsupported"),
        ("name: 1.25", "unsupported"),
        ("name: 2026-08-23", "unsupported"),
    ],
)
def test_frontmatter_does_not_report_malformed_or_unsupported_values_as_parsed(
    tmp_path, frontmatter, observation
):
    write(tmp_path / "fallback" / "SKILL.md", f"---\n{frontmatter}\n---\n")

    resolved = inventory.resolve_skills(tmp_path)
    assert (resolved[0]["name"], resolved[0]["frontmatter"]) == ("fallback", observation)


@pytest.mark.parametrize(
    "frontmatter",
    [
        "name: first\n  second",
        "name:\n  nested: value",
        "name:\n  - value",
        'name: "first\n  second"',
    ],
)
def test_frontmatter_reports_target_field_continuations_as_unsupported(
    tmp_path, frontmatter
):
    write(tmp_path / "fallback" / "SKILL.md", f"---\n{frontmatter}\n---\n")

    resolved = inventory.resolve_skills(tmp_path)
    assert (resolved[0]["name"], resolved[0]["frontmatter"]) == (
        "fallback",
        "unsupported",
    )


@pytest.mark.parametrize(
    "value",
    [
        "0123",
        "00",
        "1.",
        "1:20.5",
        "2001-12-15 2:59:43.1",
        "+12",
        "-0.5",
        ".5",
        "+.5",
        "-.inf",
    ],
)
def test_frontmatter_does_not_parse_unquoted_numeric_or_datetime_shapes_as_names(
    tmp_path, value
):
    write(tmp_path / "fallback" / "SKILL.md", f"---\nname: {value}\n---\n")

    resolved = inventory.resolve_skills(tmp_path)
    assert (resolved[0]["name"], resolved[0]["frontmatter"]) == (
        "fallback",
        "unsupported",
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("normal-skill", "normal-skill"),
        ("skill_123", "skill_123"),
        ("-normal", "-normal"),
        ("'0123'", "0123"),
        ('"2001-12-15 2:59:43.1"', "2001-12-15 2:59:43.1"),
    ],
)
def test_frontmatter_parses_proven_plain_strings_and_quoted_numeric_looking_names(
    tmp_path, source, expected
):
    write(tmp_path / "candidate" / "SKILL.md", f"---\nname: {source}\n---\n")

    resolved = inventory.resolve_skills(tmp_path)
    assert (resolved[0]["name"], resolved[0]["frontmatter"]) == (expected, "parsed")


def test_resolution_excludes_discovery_symlinks_that_escape_the_target(tmp_path):
    outside = tmp_path.parent / "outside-skill.md"
    write(outside, "---\nname: outside\n---\n")
    (tmp_path / "linked").mkdir()
    (tmp_path / "linked" / "SKILL.md").symlink_to(outside)
    assert inventory.resolve_skills(tmp_path) == []


def test_inventory_recurses_once_and_reports_cycle_missing_dynamic_and_metadata(tmp_path):
    write(tmp_path / "SKILL.md", "# Main\nRead [A](references/a.md) and `${dynamic}/x.md`.\n")
    parent_reference = ".." + "/SKILL.md"
    write(
        tmp_path / "references" / "a.md",
        f"# A\nSee [main]({parent_reference}) and [missing](none.md).\n",
    )
    result = inventory.inventory_skill(tmp_path)
    assert [f["path"] for f in result["files"]] == ["SKILL.md", "references/a.md"]
    assert result["files"][0]["headings"] == ["Main"]
    assert result["files"][0]["bytes"] > 0 and result["files"][0]["lines"] == 2
    assert result["cycles"]
    assert any(x["kind"] == "missing" for x in result["unresolved"])
    assert any(x["kind"] == "dynamic" for x in result["unresolved"])
    assert "content" not in json.dumps(result)


def test_inventory_resolves_nested_bare_paths_from_the_skill_root(tmp_path):
    write(tmp_path / "SKILL.md", "Read [details](references/details.md).\n")
    write(tmp_path / "references" / "details.md", "Run `scripts/tool.py`.\n")
    write(tmp_path / "scripts" / "tool.py", "print('safe')\n")

    result = inventory.inventory_skill(tmp_path)
    assert {item["path"] for item in result["files"]} == {
        "SKILL.md",
        "references/details.md",
        "scripts/tool.py",
    }
    assert not result["unresolved"]


def test_inventory_resolves_nested_bare_paths_from_the_source_directory(tmp_path):
    write(tmp_path / "SKILL.md", "Read [details](references/details.md).\n")
    write(tmp_path / "references" / "details.md", "Run `scripts/local.py`.\n")
    write(tmp_path / "references" / "scripts" / "local.py", "print('safe')\n")

    result = inventory.inventory_skill(tmp_path)
    assert any(
        edge == {"from": "references/details.md", "to": "references/scripts/local.py"}
        for edge in result["edges"]
    )


def test_inventory_reports_distinct_existing_bare_path_candidates_as_ambiguous(tmp_path):
    write(tmp_path / "SKILL.md", "Read [details](references/details.md).\n")
    write(tmp_path / "references" / "details.md", "Run `scripts/tool.py`.\n")
    write(tmp_path / "scripts" / "tool.py", "root\n")
    write(tmp_path / "references" / "scripts" / "tool.py", "local\n")

    result = inventory.inventory_skill(tmp_path)
    assert result["unresolved"] == [{
        "from": "references/details.md",
        "reference": "scripts/tool.py",
        "kind": "ambiguous",
        "candidates": ["references/scripts/tool.py", "scripts/tool.py"],
    }]
    assert {item["path"] for item in result["files"]} == {"SKILL.md", "references/details.md"}


def test_inventory_reports_mixed_missing_and_outside_bare_candidates_as_missing(tmp_path):
    outside = tmp_path.parent / "outside-tool.py"
    write(outside, "outside body must not be read\n")
    write(tmp_path / "SKILL.md", "Read [details](references/details.md).\n")
    write(tmp_path / "references" / "details.md", "Run `scripts/tool.py`.\n")
    (tmp_path / "references" / "scripts").mkdir()
    (tmp_path / "references" / "scripts" / "tool.py").symlink_to(outside)

    result = inventory.inventory_skill(tmp_path)
    assert result["unresolved"] == [{
        "from": "references/details.md",
        "reference": "scripts/tool.py",
        "kind": "missing",
    }]
    assert "outside body" not in json.dumps(result)


def test_inventory_does_not_report_a_diamond_dependency_as_a_cycle(tmp_path):
    write(tmp_path / "SKILL.md", "[a](a.md) [b](b.md)\n")
    write(tmp_path / "a.md", "[shared](shared.md)\n")
    write(tmp_path / "b.md", "[shared](shared.md)\n")
    write(tmp_path / "shared.md", "shared\n")
    assert inventory.inventory_skill(tmp_path)["cycles"] == []


def test_inventory_reports_a_real_cycle_without_recursing_forever(tmp_path):
    write(tmp_path / "SKILL.md", "[a](a.md)\n")
    write(tmp_path / "a.md", "[b](b.md)\n")
    write(tmp_path / "b.md", "[a](a.md)\n")
    result = inventory.inventory_skill(tmp_path)
    assert result["cycles"] == [{"from": "b.md", "to": "a.md"}]
    assert [item["path"] for item in result["files"]] == ["SKILL.md", "a.md", "b.md"]


def test_cycle_detection_handles_graphs_deeper_than_python_recursion_limit(tmp_path):
    node_count = 1_200
    write(tmp_path / "SKILL.md", "[next](node-0000.md)\n")
    for index in range(node_count):
        next_link = f"[next](node-{index + 1:04d}.md)\n" if index + 1 < node_count else "end\n"
        write(tmp_path / f"node-{index:04d}.md", next_link)
    result = inventory.inventory_skill(tmp_path)
    assert len(result["files"]) == node_count + 1
    assert result["cycles"] == []


@pytest.mark.parametrize("reference", [".." + "/outside.md", "/outside.md"])
def test_inventory_rejects_paths_outside_target(tmp_path, reference):
    write(tmp_path / "SKILL.md", f"[outside]({reference})\n")
    assert inventory.inventory_skill(tmp_path)["unresolved"][0]["kind"] == "containment"


def test_inventory_rejects_symlink_escape_and_never_writes(tmp_path):
    target = tmp_path / "target"
    outside = tmp_path / "outside.md"
    write(outside, "secret")
    write(target / "SKILL.md", "[outside](escape.md)\n")
    (target / "escape.md").symlink_to(outside)
    before = sorted((p.relative_to(target).as_posix(), p.lstat().st_mode, p.stat().st_size) for p in target.rglob("*"))
    result = inventory.inventory_skill(target)
    after = sorted((p.relative_to(target).as_posix(), p.lstat().st_mode, p.stat().st_size) for p in target.rglob("*"))
    assert result["unresolved"][0]["kind"] == "containment"
    assert before == after


def test_inventory_rejects_an_entry_symlink_that_escapes_the_target(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    outside = tmp_path / "outside.md"
    write(outside, "outside")
    (target / "SKILL.md").symlink_to(outside)
    with pytest.raises(ValueError, match="required target escapes granted directory"):
        inventory.inventory_skill(target)


@pytest.mark.parametrize("reference", ["https://example.invalid/a", "mailto:nobody@example.invalid"])
def test_inventory_reports_unsupported_external_targets_without_reading_them(tmp_path, reference):
    write(tmp_path / "SKILL.md", f"[external]({reference})\n")
    result = inventory.inventory_skill(tmp_path)
    assert result["files"] == [{
        "path": "SKILL.md",
        "bytes": len(f"[external]({reference})\n".encode()),
        "text": True,
        "lines": 1,
        "headings": [],
        "readable": True,
    }]
    assert result["unresolved"] == [{
        "from": "SKILL.md",
        "reference": reference,
        "kind": "unsupported",
    }]


def test_discovery_ignores_hidden_and_dependencies(tmp_path):
    write(tmp_path / ".hidden" / "SKILL.md", "hidden")
    write(tmp_path / "node_modules" / "dep" / "SKILL.md", "dep")
    write(tmp_path / "visible" / "deep" / "SKILL.md", "---\nname: visible\n---\n")
    assert [x["name"] for x in inventory.resolve_skills(tmp_path)] == ["visible"]


def test_binary_reference_is_reported_without_contents(tmp_path):
    write(tmp_path / "SKILL.md", "[blob](blob.bin)\n")
    (tmp_path / "blob.bin").write_bytes(b"\x00\xff")
    result = inventory.inventory_skill(tmp_path)
    blob = next(f for f in result["files"] if f["path"] == "blob.bin")
    assert blob["text"] is False and blob["lines"] is None


def test_unreadable_reference_is_reported_without_aborting(tmp_path, monkeypatch):
    write(tmp_path / "SKILL.md", "[private](private.md)\n")
    write(tmp_path / "private.md", "private")
    original = Path.read_bytes

    def fail_private(path):
        if path.name == "private.md":
            raise PermissionError("not granted")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", fail_private)
    result = inventory.inventory_skill(tmp_path)
    private = next(f for f in result["files"] if f["path"] == "private.md")
    assert private["readable"] is False and private["bytes"] is None
    assert private["reason"] == "permission-denied"
    assert "not granted" not in json.dumps(private)


@pytest.mark.parametrize(
    ("error", "reason"),
    [(FileNotFoundError("gone"), "not-found"), (OSError("device details"), "io-error")],
)
def test_unreadable_reference_reports_a_safe_stable_reason(tmp_path, monkeypatch, error, reason):
    write(tmp_path / "SKILL.md", "[unstable](unstable.md)\n")
    write(tmp_path / "unstable.md", "unstable")
    original = Path.read_bytes

    def fail_unstable(path):
        if path.name == "unstable.md":
            raise error
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", fail_unstable)
    record = next(
        item for item in inventory.inventory_skill(tmp_path)["files"]
        if item["path"] == "unstable.md"
    )
    assert record["reason"] == reason
    assert str(error) not in json.dumps(record)


def test_failure_paths_leave_the_target_unchanged(tmp_path):
    target = tmp_path / "target"
    write(target / "keep.md", "keep")
    before = [(path.relative_to(target).as_posix(), path.read_bytes()) for path in target.rglob("*")]
    with pytest.raises(ValueError, match="required target is missing"):
        inventory.inventory_skill(target)
    after = [(path.relative_to(target).as_posix(), path.read_bytes()) for path in target.rglob("*")]
    assert after == before


def test_output_order_is_stable_across_equivalent_trees_created_in_different_orders(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    for root, order in ((first, ("z.md", "a.md")), (second, ("a.md", "z.md"))):
        for name in order:
            write(root / name, name)
        write(root / "SKILL.md", "[z](z.md) [a](a.md)\n")
    assert inventory.inventory_skill(first) == inventory.inventory_skill(second)


def test_cli_ambiguity_lists_every_matching_name_and_root_relative_path(tmp_path):
    write(tmp_path / "a" / "SKILL.md", "---\nname: same\n---\n")
    write(tmp_path / "b" / "SKILL.md", "---\nname: same\n---\n")

    completed = subprocess.run(
        [sys.executable, str(INVENTORY_PATH), str(tmp_path), "--name", "same"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    error = json.loads(completed.stderr)
    assert error == {
        "error": "ambiguous-target",
        "candidates": [{"name": "same", "path": "a"}, {"name": "same", "path": "b"}],
    }
    assert str(tmp_path) not in completed.stderr
