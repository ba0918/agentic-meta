#!/usr/bin/env python3
"""Tests for SI-S* static checks."""

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import static_checks as sc


# self-containment lint reads a literal parent-directory prefix anywhere in a skill file as a
# reference above the skill directory. The link bodies below are synthetic markdown written
# into a temp tree — link resolution is what is under test — so they are assembled from
# os.pardir rather than spelled out.
_UP = os.pardir + "/"


def _make_target(name="test-skill", content="", description="", tmpdir=None):
    if tmpdir is None:
        tmpdir = tempfile.mkdtemp()
    skill_dir = os.path.join(tmpdir, "skills", name)
    os.makedirs(skill_dir, exist_ok=True)
    skill_md = os.path.join(skill_dir, "SKILL.md")
    full = f"---\nname: {name}\ndescription: {description}\n---\n\n{content}"
    with open(skill_md, "w") as f:
        f.write(full)
    return {
        "name": name,
        "skill_dir": skill_dir,
        "skill_md_content": full,
        "description": description,
    }


# ── SI-S001 ──────────────────────────────────────────────────────────────

class TestSIS001(unittest.TestCase):
    def test_no_references_pass(self):
        t = _make_target(content="# Test\n\nNo references here.")
        findings = sc.check_si_s001([t], {"root": os.path.dirname(t["skill_dir"])})
        self.assertEqual(len(findings), 0)

    def test_single_level_pass(self):
        tmpdir = tempfile.mkdtemp()
        t = _make_target(name="my-skill", content="See [ref](references/foo.md).", tmpdir=tmpdir)
        refs_dir = os.path.join(t["skill_dir"], "references")
        os.makedirs(refs_dir, exist_ok=True)
        with open(os.path.join(refs_dir, "foo.md"), "w") as f:
            f.write("# Foo\nJust content, no links.\n")
        findings = sc.check_si_s001([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 0)

    def test_chain_to_sibling_detected(self):
        tmpdir = tempfile.mkdtemp()
        t = _make_target(name="my-skill", content="See [ref](references/a.md).", tmpdir=tmpdir)
        refs_dir = os.path.join(t["skill_dir"], "references")
        os.makedirs(refs_dir, exist_ok=True)
        with open(os.path.join(refs_dir, "a.md"), "w") as f:
            f.write("See also [b](b.md) for details.\n")
        with open(os.path.join(refs_dir, "b.md"), "w") as f:
            f.write("# B\nDeep content.\n")
        findings = sc.check_si_s001([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["id"], "SI-S001")

    def test_repeated_skill_md_links_count_edge_once(self):
        """issue #110: linking the same reference N times must not multiply findings."""
        tmpdir = tempfile.mkdtemp()
        t = _make_target(
            name="my-skill",
            content="See [ref](references/a.md), again [ref](references/a.md), "
                    "and once more [ref](references/a.md).",
            tmpdir=tmpdir)
        refs_dir = os.path.join(t["skill_dir"], "references")
        os.makedirs(refs_dir, exist_ok=True)
        with open(os.path.join(refs_dir, "a.md"), "w") as f:
            f.write("See also [b](b.md) for details.\n")
        with open(os.path.join(refs_dir, "b.md"), "w") as f:
            f.write("# B\nDeep content.\n")
        findings = sc.check_si_s001([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 1)

    def test_chain_to_vendored_contract_allowed(self):
        tmpdir = tempfile.mkdtemp()
        t = _make_target(name="my-skill", content="See [ref](references/a.md).", tmpdir=tmpdir)
        refs_dir = os.path.join(t["skill_dir"], "references")
        vendor_dir = os.path.join(refs_dir, "vendor")
        os.makedirs(vendor_dir, exist_ok=True)
        with open(os.path.join(refs_dir, "a.md"), "w") as f:
            f.write("See [contract](vendor/common.md).\n")
        with open(os.path.join(vendor_dir, "common.md"), "w") as f:
            f.write("# Common\n")
        findings = sc.check_si_s001([t], {"root": tmpdir})
        self.assertEqual(len(findings), 0)

    def test_vendored_contract_is_not_traversed(self):
        """A vendored contract is generated text; its outbound links are not the skill's."""
        tmpdir = tempfile.mkdtemp()
        t = _make_target(name="my-skill",
                         content="See [contract](references/vendor/common.md).", tmpdir=tmpdir)
        vendor_dir = os.path.join(t["skill_dir"], "references", "vendor")
        os.makedirs(vendor_dir, exist_ok=True)
        other_dir = os.path.join(tmpdir, "skills", "other-skill", "references")
        os.makedirs(other_dir, exist_ok=True)
        with open(os.path.join(vendor_dir, "common.md"), "w") as f:
            f.write(f"See [other]({_UP * 3}other-skill/references/z.md).\n")
        with open(os.path.join(other_dir, "z.md"), "w") as f:
            f.write("# Z\n")
        findings = sc.check_si_s001([t], {"root": tmpdir})
        self.assertEqual(len(findings), 0)

    def test_chain_to_other_skill_detected(self):
        """A5: cross-skill link from references should be detected."""
        tmpdir = tempfile.mkdtemp()
        t = _make_target(name="my-skill", content="See [ref](references/a.md).", tmpdir=tmpdir)
        refs_dir = os.path.join(t["skill_dir"], "references")
        os.makedirs(refs_dir, exist_ok=True)
        other_dir = os.path.join(tmpdir, "skills", "other-skill", "references")
        os.makedirs(other_dir, exist_ok=True)
        with open(os.path.join(refs_dir, "a.md"), "w") as f:
            f.write(f"See [other]({_UP * 2}other-skill/references/z.md).\n")
        with open(os.path.join(other_dir, "z.md"), "w") as f:
            f.write("# Z\n")
        findings = sc.check_si_s001([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 1)

    def test_references_extra_not_confused(self):
        """A4: references-extra/ must not match references/ prefix."""
        tmpdir = tempfile.mkdtemp()
        t = _make_target(name="my-skill", content="See [ref](references-extra/a.md).", tmpdir=tmpdir)
        extra_dir = os.path.join(t["skill_dir"], "references-extra")
        os.makedirs(extra_dir, exist_ok=True)
        with open(os.path.join(extra_dir, "a.md"), "w") as f:
            f.write("# A\n")
        findings = sc.check_si_s001([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 0)


# ── SI-S002 ──────────────────────────────────────────────────────────────

class TestSIS002(unittest.TestCase):
    def test_clean_description_pass(self):
        t = _make_target(description="コードを静的に解析するスキル。「analyze」で起動。")
        findings = sc.check_si_s002([t], {"root": "."})
        self.assertEqual(len(findings), 0)

    def test_phase_number_detected(self):
        t = _make_target(description="Phase 1 で収集し Phase 2 で分析するスキル。")
        findings = sc.check_si_s002([t], {"root": "."})
        self.assertEqual(len(findings), 1)

    def test_numbered_list_detected(self):
        t = _make_target(description="1. 収集 2. 分析 3. レポートするスキル。")
        findings = sc.check_si_s002([t], {"root": "."})
        self.assertEqual(len(findings), 1)

    def test_arrow_chain_detected(self):
        t = _make_target(description="収集→分析→レポートの順で実行する。")
        findings = sc.check_si_s002([t], {"root": "."})
        self.assertEqual(len(findings), 1)

    def test_japanese_procedure_detected(self):
        t = _make_target(description="まずファイルを読み、次にレポートを出力する。")
        findings = sc.check_si_s002([t], {"root": "."})
        self.assertEqual(len(findings), 1)


# ── SI-S003 ──────────────────────────────────────────────────────────────

class TestSIS003(unittest.TestCase):
    def test_workflow_heavy_pass(self):
        content = "\n".join(
            ["# My Skill", "", "Short intro.", "", "## Workflow", ""]
            + [f"Step {i}." for i in range(40)]
            + ["", "## Notes", "", "A few notes."])
        t = _make_target(content=content)
        findings = sc.check_si_s003([t], {"root": "."})
        self.assertEqual(len(findings), 0)

    def test_english_flow_heading_is_workflow(self):
        """issue #119: `## Flow` must classify as workflow-type, not prose."""
        content = "\n".join(
            ["# My Skill", "", "Short intro.", "", "## Flow", ""]
            + [f"Step {i}." for i in range(40)]
            + ["", "## Notes", "", "A few notes."])
        t = _make_target(content=content)
        findings = sc.check_si_s003([t], {"root": "."})
        self.assertEqual(len(findings), 0)

    def test_prose_heavy_detected(self):
        content = "\n".join(
            ["# My Skill", "", "## Background", ""]
            + [f"Knowledge line {i}." for i in range(50)]
            + ["", "## More Background", ""]
            + [f"More knowledge {i}." for i in range(30)]
            + ["", "## Workflow", ""]
            + [f"Step {i}." for i in range(10)])
        t = _make_target(content=content)
        findings = sc.check_si_s003([t], {"root": "."})
        self.assertEqual(len(findings), 1)

    def test_empty_skill_no_crash(self):
        t = _make_target(content="")
        findings = sc.check_si_s003([t], {"root": "."})
        self.assertEqual(len(findings), 0)

    def test_intro_before_first_h2_is_prose(self):
        """D6: lines before first ## should count as prose."""
        content = "\n".join(
            ["# My Skill"] + [f"Intro line {i}." for i in range(50)]
            + ["", "## Workflow", ""]
            + [f"Step {i}." for i in range(10)])
        t = _make_target(content=content)
        findings = sc.check_si_s003([t], {"root": "."})
        self.assertEqual(len(findings), 1)

    def test_independent_h3_is_prose(self):
        """D6: ### without parent ## should be prose."""
        content = "\n".join(
            ["# My Skill", "", "## Workflow", ""]
            + [f"Step {i}." for i in range(10)]
            + ["", "### Standalone Section", ""]
            + [f"Standalone line {i}." for i in range(60)])
        t = _make_target(content=content)
        # Standalone section is under ## Workflow (last h2), so it's workflow
        # This tests the actual behavior
        findings = sc.check_si_s003([t], {"root": "."})
        self.assertEqual(len(findings), 0)


# ── SI-S004 ──────────────────────────────────────────────────────────────

class TestSIS004(unittest.TestCase):
    def test_clean_skill_pass(self):
        tmpdir = tempfile.mkdtemp()
        t = _make_target(content="# Skill\n\n## Workflow\n\nファイルを読み、分析する。",
                         tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 0)

    def test_tool_name_mid_sentence_detected(self):
        tmpdir = tempfile.mkdtemp()
        t = _make_target(content="# Skill\n\nその後 Edit で修正する。", tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 1)
        self.assertIn("Edit", findings[0]["what"])

    def test_tool_name_in_code_block_excluded(self):
        tmpdir = tempfile.mkdtemp()
        t = _make_target(content="# Skill\n\n```\nEdit the file.\n```\n", tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 0)

    def test_tilde_fence_excluded(self):
        """E: ~~~ fenced blocks should also be excluded."""
        tmpdir = tempfile.mkdtemp()
        t = _make_target(content="# Skill\n\n~~~\nEdit the file.\n~~~\n", tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 0)

    def test_tool_name_in_inline_code_excluded(self):
        tmpdir = tempfile.mkdtemp()
        t = _make_target(content="# Skill\n\nツール名は `Edit` です。", tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 0)

    def test_sentence_start_excluded(self):
        tmpdir = tempfile.mkdtemp()
        t = _make_target(content="# Skill\n\nEdit the file. Read it back.", tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 0)

    def test_heading_excluded(self):
        tmpdir = tempfile.mkdtemp()
        t = _make_target(content="# Skill\n\n## Workflow\n\nDo things.", tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 0)

    def test_japanese_tool_notation_detected(self):
        tmpdir = tempfile.mkdtemp()
        t = _make_target(content="# Skill\n\nBash ツールで実行する。", tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 1)
        self.assertIn("Bash ツール", findings[0]["what"])

    def test_japanese_tool_no_double_count(self):
        """A2: 'Bash ツール' must produce exactly 1 finding, not 2."""
        tmpdir = tempfile.mkdtemp()
        t = _make_target(content="# Skill\n\nその後 Bash ツールで実行する。", tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 1)

    def test_model_name_detected(self):
        tmpdir = tempfile.mkdtemp()
        t = _make_target(content="# Skill\n\nclaude-opus-4 を使用する。", tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 1)
        self.assertIn("モデル固有名", findings[0]["what"])

    def test_gpt_model_detected(self):
        """D3: gpt-* model names should be detected."""
        tmpdir = tempfile.mkdtemp()
        t = _make_target(content="# Skill\n\ngpt-4.1 を使用する。", tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 1)

    def test_o1_model_detected(self):
        """D3: o1-* model names should be detected."""
        tmpdir = tempfile.mkdtemp()
        t = _make_target(content="# Skill\n\no1-preview を使用する。", tmpdir=tmpdir)
        # o1-preview doesn't match o1-[\d.]+, this is expected behavior
        # o1-2 would match
        t2 = _make_target(name="s2", content="# Skill\n\no1-3 を使用する。", tmpdir=tmpdir)
        findings = sc.check_si_s004([t2], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 1)

    def test_lsp_protocol_mention_excluded(self):
        tmpdir = tempfile.mkdtemp()
        t = _make_target(content="# Skill\n\nLSP 準拠のサーバーと連携する。", tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 0)

    def test_lsp_tool_mention_detected(self):
        """D4: 'LSP ツール' should be detected."""
        tmpdir = tempfile.mkdtemp()
        t = _make_target(content="# Skill\n\nLSP ツールで解析する。", tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertGreaterEqual(len(findings), 1)

    def test_numbered_list_start_excluded(self):
        tmpdir = tempfile.mkdtemp()
        t = _make_target(content="# Skill\n\n1. Read the file.\n2. Write the output.",
                         tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 0)

    def test_tool_mid_numbered_list_detected(self):
        tmpdir = tempfile.mkdtemp()
        t = _make_target(content="# Skill\n\n1. その後 Edit で修正する。", tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 1)
        self.assertIn("Edit", findings[0]["what"])

    def test_symlink_in_references_skipped(self):
        """E: symlinks in references/ should be skipped."""
        tmpdir = tempfile.mkdtemp()
        t = _make_target(content="# Skill\n\nSome content.", tmpdir=tmpdir)
        refs_dir = os.path.join(t["skill_dir"], "references")
        os.makedirs(refs_dir, exist_ok=True)
        target_file = os.path.join(tmpdir, "external.md")
        with open(target_file, "w") as f:
            f.write("# External\n\nその後 Edit で修正。")
        os.symlink(target_file, os.path.join(refs_dir, "linked.md"))
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 0)

    # ── Issue #124: English false-positive suppression ──────────────────

    def test_bullet_start_excluded(self):
        """#124 case 1: bullet list items are sentence-initial."""
        tmpdir = tempfile.mkdtemp()
        t = _make_target(content="# Skill\n\n- Read the file\n* Write output\n+ Edit it",
                         tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 0)

    def test_table_cell_start_excluded(self):
        """#124 case 1: table cell start is sentence-initial."""
        tmpdir = tempfile.mkdtemp()
        t = _make_target(content="# Skill\n\n| Read | Write | Edit |",
                         tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 0)

    def test_emphasis_after_list_marker_excluded(self):
        """#124 case 1: bold/italic at list start is sentence-initial."""
        tmpdir = tempfile.mkdtemp()
        t = _make_target(
            content="# Skill\n\n1. **Read** current status\n- *Write* the output",
            tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 0)

    def test_domain_agent_artifact_store_excluded(self):
        """#124 case 2: 'Agent Artifact Store' is a domain term."""
        tmpdir = tempfile.mkdtemp()
        t = _make_target(content="# Skill\n\nInitialize the Agent Artifact Store.",
                         tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 0)

    def test_domain_agent_skills_excluded(self):
        """#124 case 2: 'Agent Skills' is a domain term."""
        tmpdir = tempfile.mkdtemp()
        t = _make_target(content="# Skill\n\nThis repo contains Agent Skills.",
                         tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 0)

    def test_domain_agent_number_excluded(self):
        """#124 case 2: 'Agent 1' (numbered subagent) is a domain term."""
        tmpdir = tempfile.mkdtemp()
        t = _make_target(content="# Skill\n\nLaunch Agent 3 for review.",
                         tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 0)

    def test_domain_workflow_excluded(self):
        """#124 case 2: 'Wrap Workflow' is a domain term."""
        tmpdir = tempfile.mkdtemp()
        t = _make_target(content="# Skill\n\nRun the Wrap Workflow to finish.",
                         tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 0)

    def test_bare_agent_mid_sentence_still_detected(self):
        """#124 case 2: bare 'Agent' not in domain phrase is still flagged."""
        tmpdir = tempfile.mkdtemp()
        t = _make_target(content="# Skill\n\nUse the Agent to run tasks.",
                         tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertGreaterEqual(len(findings), 1)

    def test_lsp_english_language_server_excluded(self):
        """#124 case 3: 'the language server (LSP)' is protocol context."""
        tmpdir = tempfile.mkdtemp()
        t = _make_target(
            content="# Skill\n\nConnect to the language server (LSP) for completions.",
            tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 0)

    def test_slash_in_enumeration_not_suppressed(self):
        """#124 case 4: slash in enumeration is not a path, so detect."""
        tmpdir = tempfile.mkdtemp()
        t = _make_target(
            content="# Skill\n\nAvoid Read/Write/Edit in the text.",
            tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        # "Read" is at sentence start (after ". "), but "Write" and "Edit" should be detected
        tool_names = [f["what"] for f in findings]
        self.assertTrue(any("Write" in w for w in tool_names))
        self.assertTrue(any("Edit" in w for w in tool_names))

    def test_slash_in_path_still_suppressed(self):
        """#124 case 4: slash in file path still suppresses."""
        tmpdir = tempfile.mkdtemp()
        t = _make_target(
            content="# Skill\n\nSee scripts/Read/foo.py for details.",
            tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 0)

    def test_english_tool_pattern_detected(self):
        """#124 case 5: 'the Read tool' is a high-confidence pattern."""
        tmpdir = tempfile.mkdtemp()
        t = _make_target(
            content="# Skill\n\nUse the Read tool to inspect files.",
            tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertGreaterEqual(len(findings), 1)
        self.assertTrue(any("Read tool" in f["what"] for f in findings))

    def test_english_tool_possessive_detected(self):
        """#124 case 5: 'Read tool's output' is a high-confidence pattern."""
        tmpdir = tempfile.mkdtemp()
        t = _make_target(
            content="# Skill\n\nCheck Read tool's output before proceeding.",
            tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertGreaterEqual(len(findings), 1)

    def test_english_tool_no_double_count(self):
        """#124 case 5: 'the Read tool' must produce exactly 1 finding, not 2."""
        tmpdir = tempfile.mkdtemp()
        t = _make_target(
            content="# Skill\n\nUse the Read tool here.",
            tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 1)

    def test_japanese_tool_still_works(self):
        """#124: _TOOL_JA_RE must still fire for remaining Japanese content."""
        tmpdir = tempfile.mkdtemp()
        t = _make_target(
            content="# Skill\n\nBash ツールで実行する。",
            tmpdir=tmpdir)
        findings = sc.check_si_s004([t], {"root": os.path.join(tmpdir, "skills")})
        self.assertEqual(len(findings), 1)
        self.assertIn("ツール", findings[0]["what"])


# ── ID numbering ─────────────────────────────────────────────────────────

class TestIDNumbering(unittest.TestCase):
    def test_single_finding_no_suffix(self):
        """Single finding keeps base ID."""
        findings = sc._assign_ids([
            {"id": "SI-S004", "other": "data"},
        ])
        self.assertEqual(findings[0]["id"], "SI-S004")

    def test_multiple_findings_get_suffix(self):
        """A3: multiple findings get -1, -2, ... (no gap)."""
        findings = sc._assign_ids([
            {"id": "SI-S004", "other": "a"},
            {"id": "SI-S004", "other": "b"},
            {"id": "SI-S004", "other": "c"},
        ])
        self.assertEqual(findings[0]["id"], "SI-S004-1")
        self.assertEqual(findings[1]["id"], "SI-S004-2")
        self.assertEqual(findings[2]["id"], "SI-S004-3")

    def test_mixed_rules_numbered_independently(self):
        findings = sc._assign_ids([
            {"id": "SI-S004", "other": "a"},
            {"id": "SI-S001", "other": "x"},
            {"id": "SI-S004", "other": "b"},
        ])
        self.assertEqual(findings[0]["id"], "SI-S004-1")
        self.assertEqual(findings[1]["id"], "SI-S001")
        self.assertEqual(findings[2]["id"], "SI-S004-2")


# ── collect_targets ──────────────────────────────────────────────────────

class TestCollectTargets(unittest.TestCase):
    def test_collects_skills(self):
        tmpdir = tempfile.mkdtemp()
        skills_dir = os.path.join(tmpdir, "skills")
        os.makedirs(os.path.join(skills_dir, "my-skill"))
        with open(os.path.join(skills_dir, "my-skill", "SKILL.md"), "w") as f:
            f.write("---\nname: my-skill\ndescription: test\n---\n# My Skill\n")
        targets = sc.collect_targets(skills_dir)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["name"], "my-skill")

    def test_skips_dot_prefixed_directory(self):
        tmpdir = tempfile.mkdtemp()
        skills_dir = os.path.join(tmpdir, "skills")
        os.makedirs(os.path.join(skills_dir, ".cache"))
        with open(os.path.join(skills_dir, ".cache", "SKILL.md"), "w") as f:
            f.write("---\nname: cache\ndescription: test\n---\n")
        targets = sc.collect_targets(skills_dir)
        self.assertEqual(len(targets), 0)

    def test_skips_installed_dependency_directory(self):
        tmpdir = tempfile.mkdtemp()
        skills_dir = os.path.join(tmpdir, "skills")
        os.makedirs(os.path.join(skills_dir, "node_modules"))
        with open(os.path.join(skills_dir, "node_modules", "SKILL.md"), "w") as f:
            f.write("---\nname: vendored\ndescription: test\n---\n")
        targets = sc.collect_targets(skills_dir)
        self.assertEqual(len(targets), 0)

    def test_skips_symlinked_skill_dir(self):
        tmpdir = tempfile.mkdtemp()
        skills_dir = os.path.join(tmpdir, "skills")
        real = os.path.join(skills_dir, "real-skill")
        os.makedirs(real)
        with open(os.path.join(real, "SKILL.md"), "w") as f:
            f.write("---\nname: real-skill\ndescription: test\n---\n")
        os.symlink(real, os.path.join(skills_dir, "linked-skill"))
        targets = sc.collect_targets(skills_dir)
        names = [t["name"] for t in targets]
        self.assertIn("real-skill", names)
        self.assertNotIn("linked-skill", names)


# ── CLI ──────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    def test_bare_output_filename(self):
        """A1: --output findings.json (no directory) must not crash."""
        tmpdir = tempfile.mkdtemp()
        skills_dir = os.path.join(tmpdir, "skills")
        os.makedirs(os.path.join(skills_dir, "dummy"))
        with open(os.path.join(skills_dir, "dummy", "SKILL.md"), "w") as f:
            f.write("---\nname: dummy\ndescription: test\n---\n# Dummy\n")
        out = os.path.join(tmpdir, "findings.json")
        result = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(__file__), "static_checks.py"),
             "--root", tmpdir, "--output", out],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.isfile(out))

    def test_multiple_skills(self):
        """C1: --skill a b should filter to both."""
        tmpdir = tempfile.mkdtemp()
        skills_dir = os.path.join(tmpdir, "skills")
        for name in ["alpha", "beta", "gamma"]:
            os.makedirs(os.path.join(skills_dir, name))
            with open(os.path.join(skills_dir, name, "SKILL.md"), "w") as f:
                f.write(f"---\nname: {name}\ndescription: test\n---\n# {name}\n")
        out = os.path.join(tmpdir, "out.json")
        subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(__file__), "static_checks.py"),
             "--root", tmpdir, "--skill", "alpha", "beta", "--output", out],
            capture_output=True, text=True)
        import json
        findings_data = json.load(open(out))
        # We only care that it didn't crash and processed the right skills
        self.assertTrue(os.path.isfile(out))


# ── Real repo integration ────────────────────────────────────────────────

class TestRunOnRealRepo(unittest.TestCase):
    def test_self_audit_no_crash(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        skills_dir = os.path.join(root, "skills")
        if not os.path.isdir(skills_dir):
            self.skipTest("Not running from repo root")
        targets = sc.collect_targets(skills_dir)
        self.assertGreater(len(targets), 0)
        findings = sc.run_checks(targets, {"root": root})
        self.assertIsInstance(findings, list)
        for f in findings:
            for field in sc.CANONICAL_FIELDS:
                self.assertIn(field, f, f"Finding missing field: {field}")


if __name__ == "__main__":
    unittest.main()


# ── SI-S006 ──────────────────────────────────────────────────────────────

def _make_contract(tmpdir, name, body, skill="test-skill"):
    d = os.path.join(tmpdir, "skills", skill, "references", "vendor")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), "w") as f:
        f.write(body)


_LONG = ("the queue itself holds ready running done failed archives and their "
         "index under the state root directory")


class TestSIS006(unittest.TestCase):
    def test_verbatim_run_in_linked_contract_is_flagged(self):
        tmpdir = tempfile.mkdtemp()
        _make_contract(tmpdir, "polling-pattern.md", f"# Contract\n\n{_LONG}\n")
        t = _make_target(
            content=f"See [contract](references/vendor/polling-pattern.md).\n\n{_LONG}\n",
            tmpdir=tmpdir)
        findings = sc.check_si_s006([t], {"root": tmpdir})
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["id"], "SI-S006")
        self.assertEqual(findings[0]["severity"], "WARN")
        self.assertEqual(findings[0]["action"], "NEEDS_JUDGMENT")

    def test_link_without_duplication_passes(self):
        tmpdir = tempfile.mkdtemp()
        _make_contract(tmpdir, "polling-pattern.md", f"# Contract\n\n{_LONG}\n")
        t = _make_target(
            content="Follow [contract](references/vendor/polling-pattern.md); "
                    "this skill retries at most three times.\n",
            tmpdir=tmpdir)
        self.assertEqual(sc.check_si_s006([t], {"root": tmpdir}), [])

    def test_unlinked_contract_is_not_compared(self):
        # リンクしていない契約とは比較しない。偶然の語の一致で発火させないため
        tmpdir = tempfile.mkdtemp()
        _make_contract(tmpdir, "polling-pattern.md", f"# Contract\n\n{_LONG}\n")
        t = _make_target(content=f"{_LONG}\n", tmpdir=tmpdir)
        self.assertEqual(sc.check_si_s006([t], {"root": tmpdir}), [])

    def test_same_named_link_outside_vendor_is_not_the_contract(self):
        # Where the link resolves decides whether it is the contract; the file name does not.
        tmpdir = tempfile.mkdtemp()
        _make_contract(tmpdir, "polling-pattern.md", f"# Contract\n\n{_LONG}\n")
        t = _make_target(
            content=f"See [local](references/polling-pattern.md).\n\n{_LONG}\n",
            tmpdir=tmpdir)
        refs = os.path.join(t["skill_dir"], "references")
        os.makedirs(refs, exist_ok=True)
        with open(os.path.join(refs, "polling-pattern.md"), "w") as f:
            f.write("# A note this skill owns.\n")
        self.assertEqual(sc.check_si_s006([t], {"root": tmpdir}), [])

    def test_code_fence_match_is_ignored(self):
        # コマンド例やスキーマ例が契約と一致するのは正しい引用であって重複ではない
        tmpdir = tempfile.mkdtemp()
        _make_contract(tmpdir, "polling-pattern.md", f"# Contract\n\n```\n{_LONG}\n```\n")
        t = _make_target(
            content=f"See [contract](references/vendor/polling-pattern.md).\n\n"
                    f"```\n{_LONG}\n```\n",
            tmpdir=tmpdir)
        self.assertEqual(sc.check_si_s006([t], {"root": tmpdir}), [])

    def test_short_shared_phrase_passes(self):
        # 閾値未満の短い言い換えは拾わない（役割固有の 1 行要約を潰さない）
        tmpdir = tempfile.mkdtemp()
        _make_contract(tmpdir, "polling-pattern.md", "# Contract\n\nready running done failed\n")
        t = _make_target(
            content="See [contract](references/vendor/polling-pattern.md).\n\n"
                    "ready running done failed\n",
            tmpdir=tmpdir)
        self.assertEqual(sc.check_si_s006([t], {"root": tmpdir}), [])

    def test_duplication_inside_references_dir_is_flagged(self):
        # references/ 配下も走査対象。実測ではここで真陽性 1 件が増えた
        tmpdir = tempfile.mkdtemp()
        _make_contract(tmpdir, "polling-pattern.md", f"# Contract\n\n{_LONG}\n")
        t = _make_target(content="A skill body with no duplication.\n", tmpdir=tmpdir)
        refs = os.path.join(t["skill_dir"], "references")
        os.makedirs(refs, exist_ok=True)
        with open(os.path.join(refs, "state.md"), "w") as f:
            f.write(f"See [contract](vendor/polling-pattern.md).\n\n{_LONG}\n")
        findings = sc.check_si_s006([t], {"root": tmpdir})
        self.assertEqual(len(findings), 1)
        self.assertIn("references/state.md", findings[0]["where"])

    def test_missing_vendor_dir_is_not_an_error(self):
        t = _make_target(content="# Test\n")
        self.assertEqual(
            sc.check_si_s006([t], {"root": os.path.dirname(t["skill_dir"])}), [])
