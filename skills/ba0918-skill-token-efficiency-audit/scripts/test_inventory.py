import json
import os
from pathlib import Path

import pytest

from . import inventory


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_resolution_uses_first_nonempty_layer(tmp_path):
    write(tmp_path / "skills" / "chosen" / "SKILL.md", "---\nname: chosen\n---\n")
    write(tmp_path / "SKILL.md", "---\nname: root\n---\n")
    assert [item["name"] for item in inventory.resolve_skills(tmp_path)] == ["chosen"]


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


def test_inventory_recurses_once_and_reports_cycle_missing_dynamic_and_metadata(tmp_path):
    write(tmp_path / "SKILL.md", "# Main\nRead [A](references/a.md) and `${dynamic}/x.md`.\n")
    write(tmp_path / "references" / "a.md", "# A\nSee [main](../SKILL.md) and [missing](none.md).\n")
    result = inventory.inventory_skill(tmp_path)
    assert [f["path"] for f in result["files"]] == ["SKILL.md", "references/a.md"]
    assert result["files"][0]["headings"] == ["Main"]
    assert result["files"][0]["bytes"] > 0 and result["files"][0]["lines"] == 2
    assert result["cycles"]
    assert any(x["kind"] == "missing" for x in result["unresolved"])
    assert any(x["kind"] == "dynamic" for x in result["unresolved"])
    assert "content" not in json.dumps(result)


@pytest.mark.parametrize("reference", ["../outside.md", "/outside.md"])
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


def test_output_order_is_stable(tmp_path):
    write(tmp_path / "SKILL.md", "[z](z.md) [a](a.md)\n")
    write(tmp_path / "z.md", "z")
    write(tmp_path / "a.md", "a")
    assert inventory.inventory_skill(tmp_path) == inventory.inventory_skill(tmp_path)
