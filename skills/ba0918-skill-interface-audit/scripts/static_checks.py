#!/usr/bin/env python3
"""
skill-interface-audit: pure-function SI-S* rule engine.

Each rule is `check(targets, ctx) -> list[Finding]` registered in RULES.
Adding a rule = add function + register + test (Open-Closed).

Finding schema:
  id, severity, action, where(skill:file:line), what, why, how, fix_draft
"""

import argparse
import json
import os
import re
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Finding helpers
# ---------------------------------------------------------------------------

CANONICAL_FIELDS = ("id", "severity", "action", "where", "what", "why", "how", "fix_draft")


def make_finding(rule_id, severity, action, where, what, why, how, fix_draft=None):
    return {"id": rule_id, "severity": severity, "action": action, "where": where,
            "what": what, "why": why, "how": how, "fix_draft": fix_draft}


def _assign_ids(findings: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    for f in findings:
        base = f["id"]
        counts[base] = counts.get(base, 0) + 1
    multi = {k for k, v in counts.items() if v > 1}
    counters: dict[str, int] = {}
    for f in findings:
        base = f["id"]
        if base in multi:
            counters[base] = counters.get(base, 0) + 1
            f["id"] = f"{base}-{counters[base]}"
    return findings


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

_LINK_RE = re.compile(r"\]\(([^)\s#]+\.md[^)]*)\)")
_FENCED_BLOCK = re.compile(r"^(`{3,}|~{3,})")
_INLINE_CODE = re.compile(r"`{1,2}[^`\n]+`{1,2}")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _strip_frontmatter(content: str) -> str:
    m = _FRONTMATTER_RE.match(content)
    return content[m.end():] if m else content


def _extract_frontmatter(content: str) -> str:
    m = _FRONTMATTER_RE.match(content)
    return m.group(1) if m else ""


def _extract_description(content: str) -> str:
    fm = _extract_frontmatter(content)
    for line in fm.split("\n"):
        if line.startswith("description:"):
            return line[len("description:"):].strip()
    return ""


def _lines_outside_code_blocks(content: str) -> list[tuple[int, str]]:
    lines = content.split("\n")
    result = []
    in_fence = False
    for i, line in enumerate(lines, 1):
        if _FENCED_BLOCK.match(line.strip()):
            in_fence = not in_fence
            continue
        if not in_fence:
            result.append((i, line))
    return result


def _strip_inline_code(line: str) -> str:
    return _INLINE_CODE.sub("", line)


def _is_quote_line(line: str) -> bool:
    return line.strip().startswith(">")


def _is_heading(line: str) -> bool:
    return line.strip().startswith("#")


def _startswith_dir(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + os.sep)


# ---------------------------------------------------------------------------
# SI-S001: Reference chain depth
# ---------------------------------------------------------------------------

def _extract_md_links(content: str) -> list[tuple[str, int]]:
    result = []
    for lineno, line in _lines_outside_code_blocks(content):
        for m in _LINK_RE.finditer(line):
            target = m.group(1).split("#")[0]
            if target:
                result.append((target, lineno))
    return result


def check_si_s001(targets: list[dict], ctx: dict) -> list[dict]:
    findings = []
    for t in targets:
        skill_md = t.get("skill_md_content", "")
        skill_dir = t.get("skill_dir", "")
        skill_name = t.get("name", "")
        refs_dir = os.path.normpath(os.path.join(skill_dir, "references"))
        vendor_dir = os.path.normpath(os.path.join(refs_dir, _VENDOR_DIRNAME))

        first_level_refs = []
        seen_ref_paths = set()
        for link, lineno in _extract_md_links(skill_md):
            resolved = os.path.normpath(os.path.join(skill_dir, link))
            if _startswith_dir(resolved, vendor_dir):
                continue
            if _startswith_dir(resolved, refs_dir) and resolved not in seen_ref_paths:
                seen_ref_paths.add(resolved)
                first_level_refs.append((link, lineno, resolved))

        for ref_link, ref_lineno, ref_path in first_level_refs:
            if not os.path.isfile(ref_path):
                continue
            try:
                with open(ref_path, encoding="utf-8", errors="replace") as f:
                    ref_content = f.read()
            except OSError:
                continue

            for second_link, second_lineno in _extract_md_links(ref_content):
                second_resolved = os.path.normpath(
                    os.path.join(os.path.dirname(ref_path), second_link))
                if _startswith_dir(second_resolved, vendor_dir):
                    continue
                # A5 fix: flag ANY md link out of a first-level ref, bar a vendored contract
                findings.append(make_finding(
                    rule_id="SI-S001",
                    severity="WARN",
                    action="REPORT_ONLY",
                    where=f"{skill_name}:{os.path.basename(ref_path)}:{second_lineno}",
                    what=f"参照チェーン深度超過: {os.path.basename(ref_path)} -> {second_link}",
                    why="Progressive disclosure は1階層まで (authoring-principles #4)",
                    how="二次参照を references/vendor/ の契約に寄せるか、SKILL.md から直接リンクする",
                ))
    return findings


# ---------------------------------------------------------------------------
# SI-S002: Description workflow summary leakage
# ---------------------------------------------------------------------------

_PHASE_STEP_RE = re.compile(r"Phase\s*\d|Step\s*\d", re.IGNORECASE)
_NUMBERED_LIST_RE = re.compile(r"\d+[.)]\s")
_PROCEDURE_JA_RE = re.compile(r"まず.*次に|最初に.*その後")
_ARROW_CHAIN_RE = re.compile(r"→.*→")


def check_si_s002(targets: list[dict], ctx: dict) -> list[dict]:
    findings = []
    for t in targets:
        desc = t.get("description", "")
        skill_name = t.get("name", "")
        if not desc:
            continue

        violations = []
        if _PHASE_STEP_RE.search(desc):
            violations.append("Phase/Step 番号")
        if _NUMBERED_LIST_RE.search(desc):
            violations.append("番号付きリスト")
        if _PROCEDURE_JA_RE.search(desc):
            violations.append("手順接続詞")
        if _ARROW_CHAIN_RE.search(desc):
            violations.append("→ 連鎖")

        if violations:
            findings.append(make_finding(
                rule_id="SI-S002",
                severity="WARN",
                action="REPORT_ONLY",
                where=f"{skill_name}:SKILL.md:frontmatter",
                what=f"description にワークフロー要約が混入: {', '.join(violations)}",
                why="description は「何をするか + いつ使うか」に留める (authoring-principles frontmatter)",
                how="Phase/Step 番号・手順記述を削除し、能力とトリガー語のみにする",
            ))
    return findings


# ---------------------------------------------------------------------------
# SI-S003: Prose bloat
# ---------------------------------------------------------------------------

_WORKFLOW_KEYWORDS = {"workflow", "flow", "phase", "step", "フロー", "ワークフロー"}


def _classify_heading(heading_text: str) -> str:
    lower = heading_text.lower().strip().lstrip("#").strip()
    for kw in _WORKFLOW_KEYWORDS:
        if kw in lower:
            return "workflow"
    return "prose"


def check_si_s003(targets: list[dict], ctx: dict) -> list[dict]:
    findings = []
    for t in targets:
        content = t.get("skill_md_content", "")
        skill_name = t.get("name", "")
        body = _strip_frontmatter(content)
        if not body.strip():
            continue

        lines = body.split("\n")
        total = len(lines)
        if total == 0:
            continue

        current_h2_class = "prose"
        workflow_lines = 0
        prose_lines = 0

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("## "):
                current_h2_class = _classify_heading(stripped)
            if current_h2_class == "workflow":
                workflow_lines += 1
            else:
                prose_lines += 1

        ratio = prose_lines / total if total > 0 else 0
        if ratio > 0.6:
            findings.append(make_finding(
                rule_id="SI-S003",
                severity="INFO",
                action="REPORT_ONLY",
                where=f"{skill_name}:SKILL.md",
                what=f"prose 肥大: {prose_lines}/{total} 行 ({ratio:.0%})",
                why="Process over prose (authoring-principles #1)",
                how="知識の羅列は references/ に逃がし、SKILL.md はワークフローに徹する",
            ))
    return findings


# ---------------------------------------------------------------------------
# SI-S004: Platform-specific tool vocabulary
# ---------------------------------------------------------------------------

_TOOL_NAMES_SORTED = sorted([
    "Edit", "Write", "Read", "Bash", "Agent", "Workflow",
    "WebFetch", "WebSearch", "Grep", "Glob", "LSP", "NotebookEdit",
])

_TOOL_JA_RE = re.compile(
    r"(" + "|".join(re.escape(t) for t in _TOOL_NAMES_SORTED) + r")\s*ツール"
)

# English high-confidence pattern: "the Read tool" / "Read tool's" / "Read tool"
_TOOL_EN_RE = re.compile(
    r"(?:the\s+)?(" + "|".join(re.escape(t) for t in _TOOL_NAMES_SORTED) + r")\s+tool(?:'s)?\b"
)

# Domain-word whitelist: patterns that look like tool names but are repository domain terms
_DOMAIN_WHITELIST_RE = re.compile(
    r"Agent\s+Artifact\s+Store"
    r"|Agent\s+Skills"
    r"|Agent\s+\d"
    r"|[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+Workflow"
)

_MODEL_RE = re.compile(
    r"claude-(?:opus|sonnet|haiku)-[\d.*]+|gpt-[\d.]+|o1-[\d.]+",
    re.IGNORECASE,
)


def _is_at_sentence_start(line: str, match_start: int) -> bool:
    if match_start == 0:
        return True
    before = line[:match_start].rstrip()
    if not before:
        return True
    if before[-1] in ".!?。！？:：":
        return True
    # Numbered list: "1. Read ..." / "2) Write ..."
    m = re.match(r"^\s*\d+[.)]\s", line)
    if m and match_start <= m.end():
        return True
    # Bullet list: "- Read ..." / "* Write ..." / "+ Edit ..."
    m_bullet = re.match(r"^\s*[-*+]\s", line)
    if m_bullet and match_start <= m_bullet.end():
        return True
    # Table cell start: "| Read ..."
    m_table = re.match(r"^\s*\|\s*", line)
    if m_table and match_start <= m_table.end():
        return True
    # After mid-line table separator: "... | Read ..."
    if match_start > 0 and before[-1] == "|":
        return True
    # After markdown emphasis at list/sentence start:
    # e.g. "1. **Read** ..." / "- **Edit** ..." / "| **Write** ..."
    # Strip trailing emphasis markers to check if what remains is a list marker or sentence start
    before_no_emph = before.rstrip("*_")
    if before_no_emph != before and before_no_emph:
        # There were emphasis markers; check if what's left is a list/table start
        b = before_no_emph.rstrip()
        if not b:
            return True
        if b[-1] in ".!?。！？:：|":
            return True
        m2 = re.match(r"^\s*\d+[.)]\s*$", b)
        if m2:
            return True
        m3 = re.match(r"^\s*[-*+]\s*$", b)
        if m3:
            return True
    return False


def check_si_s004(targets: list[dict], ctx: dict) -> list[dict]:
    findings = []
    for t in targets:
        skill_name = t.get("name", "")
        skill_dir = t.get("skill_dir", "")

        files_to_check = []
        skill_md_path = os.path.join(skill_dir, "SKILL.md")
        if os.path.isfile(skill_md_path):
            files_to_check.append(("SKILL.md", t.get("skill_md_content", "")))
        refs_dir = os.path.join(skill_dir, "references")
        if os.path.isdir(refs_dir):
            for fname in sorted(os.listdir(refs_dir)):
                if fname.endswith(".md"):
                    fpath = os.path.join(refs_dir, fname)
                    if os.path.islink(fpath):
                        continue
                    try:
                        with open(fpath, encoding="utf-8", errors="replace") as f:
                            files_to_check.append((f"references/{fname}", f.read()))
                    except OSError:
                        pass

        for relpath, content in files_to_check:
            for lineno, line in _lines_outside_code_blocks(content):
                if _is_quote_line(line):
                    continue
                if _is_heading(line):
                    continue

                clean = _strip_inline_code(line)

                # Track positions consumed by high-confidence patterns
                consumed: set[int] = set()

                # JA high-confidence: "Edit ツール" etc.
                for m in _TOOL_JA_RE.finditer(clean):
                    for pos in range(m.start(), m.end()):
                        consumed.add(pos)
                    findings.append(make_finding(
                        rule_id="SI-S004",
                        severity="WARN", action="NEEDS_JUDGMENT",
                        where=f"{skill_name}:{relpath}:{lineno}",
                        what=f"プラットフォーム固有ツール語彙: {m.group(0)}",
                        why="AGENTS.md: 特定プラットフォームのツール API 名を避ける",
                        how="プラットフォーム非依存の表現に置換する",
                    ))

                # EN high-confidence: "the Read tool" / "Read tool's" etc.
                for m in _TOOL_EN_RE.finditer(clean):
                    if any(pos in consumed for pos in range(m.start(), m.end())):
                        continue
                    for pos in range(m.start(), m.end()):
                        consumed.add(pos)
                    findings.append(make_finding(
                        rule_id="SI-S004",
                        severity="WARN", action="NEEDS_JUDGMENT",
                        where=f"{skill_name}:{relpath}:{lineno}",
                        what=f"プラットフォーム固有ツール語彙: {m.group(0)}",
                        why="AGENTS.md: 特定プラットフォームのツール API 名を避ける",
                        how="プラットフォーム非依存の表現に置換する",
                    ))

                for tool in _TOOL_NAMES_SORTED:
                    pattern = re.compile(r"\b" + re.escape(tool) + r"\b")
                    for tm in pattern.finditer(clean):
                        if any(pos in consumed for pos in range(tm.start(), tm.end())):
                            continue
                        # Domain whitelist: skip tool names that are part of domain terms
                        if _DOMAIN_WHITELIST_RE.search(clean) and \
                                any(dm.start() <= tm.start() < dm.end()
                                    for dm in _DOMAIN_WHITELIST_RE.finditer(clean)):
                            continue
                        if tool == "LSP":
                            context_after = clean[tm.end():tm.end() + 10].strip()
                            context_line_lower = clean.lower()
                            if any(kw in context_after for kw in
                                   ["準拠", "サポート", "対応", "プロトコル"]):
                                continue
                            # English LSP protocol context: "language server"
                            if "language server" in context_line_lower:
                                continue
                        if _is_at_sentence_start(clean, tm.start()):
                            continue
                        # Path guard: "/" suppresses only for file paths, not
                        # enumerations like "Read/Write/Edit"
                        if tm.start() > 0 and clean[tm.start() - 1] == "/":
                            # Check if the word before "/" is also a tool name
                            # (enumeration pattern like Read/Write/Edit)
                            pre_slash = clean[:tm.start() - 1]
                            pre_word_m = re.search(r"(\w+)$", pre_slash)
                            pre_word = pre_word_m.group(1) if pre_word_m else ""
                            if pre_word not in _TOOL_NAMES_SORTED:
                                # Not an enumeration; check path context
                                ch_after = clean[tm.end()] if tm.end() < len(clean) else ""
                                if ch_after == "" or re.match(r"[A-Za-z0-9._\-/]", ch_after):
                                    continue
                        if tm.start() > 0 and clean[tm.start() - 1] in "#.":
                            continue
                        findings.append(make_finding(
                            rule_id="SI-S004",
                            severity="WARN", action="NEEDS_JUDGMENT",
                            where=f"{skill_name}:{relpath}:{lineno}",
                            what=f"プラットフォーム固有ツール語彙: {tool}",
                            why="AGENTS.md: 特定プラットフォームのツール API 名を避ける",
                            how="プラットフォーム非依存の表現に置換する",
                        ))

                for mm in _MODEL_RE.finditer(clean):
                    findings.append(make_finding(
                        rule_id="SI-S004",
                        severity="WARN", action="NEEDS_JUDGMENT",
                        where=f"{skill_name}:{relpath}:{lineno}",
                        what=f"モデル固有名: {mm.group(0)}",
                        why="AGENTS.md: 特定プラットフォームのモデル名を避ける",
                        how="「高性能モデル」「軽量モデル」等の表現に置換する",
                    ))

    return findings


# ---------------------------------------------------------------------------
# RULES registry
# ---------------------------------------------------------------------------

_SI_S006_NGRAM = 12
_WORD_RE = re.compile(r"[a-z0-9]+")
_VENDOR_DIRNAME = "vendor"


def _word_stream(content: str) -> list[tuple[str, int]]:
    """(word, 1-indexed line) の列。frontmatter とコードフェンスは除く。

    フェンスを除くのは、コマンド例やスキーマ例が契約と一致するのは重複ではなく
    正しい引用だから。SI-S004 が同じ理由でコードブロックを除外しているのに揃える。
    """
    return [
        (w, lineno)
        for lineno, line in _lines_outside_code_blocks(_strip_frontmatter(content))
        for w in _WORD_RE.findall(line.lower())
    ]


def _ngrams(stream: list[tuple[str, int]], n: int) -> set[str]:
    return {" ".join(w for w, _ in stream[i:i + n]) for i in range(len(stream) - n + 1)}


def _first_contract_ngram_hit(stream, contract_grams, n):
    """最初に一致した n-gram を (行, 語列) で返す。無ければ None。"""
    for i in range(len(stream) - n + 1):
        gram = " ".join(w for w, _ in stream[i:i + n])
        if gram in contract_grams:
            return stream[i][1], gram
    return None


def _vendored_contract_grams(vendor_dir: str) -> dict[str, set[str]]:
    """{contract file name: set of n-grams}. Empty when there is no vendor directory."""
    grams: dict[str, set[str]] = {}
    if not os.path.isdir(vendor_dir):
        return grams
    for name in sorted(os.listdir(vendor_dir)):
        if not name.endswith(".md"):
            continue
        try:
            with open(os.path.join(vendor_dir, name), encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        grams[name] = _ngrams(_word_stream(text), _SI_S006_NGRAM)
    return grams


def _linked_contracts(content, containing_dir, vendor_dir, contract_grams) -> set[str]:
    """The vendored contracts this file actually links to, by file name.

    Decided on the resolved path rather than a prefix of the link text: the same contract
    is written `references/vendor/x.md` from SKILL.md and `vendor/x.md` from a file under
    references/, and a prefix match splits on that difference.
    """
    linked = set()
    for link, _ in _extract_md_links(content):
        resolved = os.path.normpath(os.path.join(containing_dir, link))
        if _startswith_dir(resolved, vendor_dir) and os.path.basename(resolved) in contract_grams:
            linked.add(os.path.basename(resolved))
    return linked


def check_si_s006(targets: list[dict], ctx: dict) -> list[dict]:
    """SI-S006: 契約のインライン重複。

    ファイルが md リンクしている vendored contract との間で、コードフェンス外の語が
    `_SI_S006_NGRAM` 語ぶん逐語一致したら finding とする。

    語彙の重なりや見出し名の一致は使わない。2026-07-27 の実測では、契約固有語彙の
    出現率は連続値で分離せず（中央値 0.117 / 最大 0.625）、上位は「その契約を実装して
    いるスキルが当然の語彙を使っている」偽陽性で埋まった。見出し名の一致も、
    `Preventing rationalization` のように推奨パターンとして共有されるだけで
    中身は別物だった。逐語一致だけが分離した（12 語で 4 件検出・4 件とも真陽性）。

    行スパンによる長さゲートは置かない。12 語連続の逐語一致それ自体が
    「コピーされた」ことの証拠で、行数ゲートを重ねると確認済みの真陽性
    （表形式の重複など、語順が行をまたぐもの）が落ちる。
    """
    findings = []
    root = ctx.get("root", ".")

    for t in targets:
        vendor_dir = os.path.normpath(
            os.path.join(t["skill_dir"], "references", _VENDOR_DIRNAME))
        contract_grams = _vendored_contract_grams(vendor_dir)
        if not contract_grams:
            continue

        files = [(os.path.join(t["skill_dir"], "SKILL.md"), t["skill_md_content"])]
        refs_dir = os.path.join(t["skill_dir"], "references")
        if os.path.isdir(refs_dir):
            for name in sorted(os.listdir(refs_dir)):
                if not name.endswith(".md"):
                    continue
                path = os.path.join(refs_dir, name)
                try:
                    with open(path, encoding="utf-8", errors="replace") as f:
                        files.append((path, f.read()))
                except OSError:
                    continue

        for path, content in files:
            linked = _linked_contracts(content, os.path.dirname(path), vendor_dir, contract_grams)
            if not linked:
                continue
            stream = _word_stream(content)
            for contract in sorted(linked):
                hit = _first_contract_ngram_hit(stream, contract_grams[contract], _SI_S006_NGRAM)
                if hit is None:
                    continue
                lineno, gram = hit
                rel = os.path.relpath(path, root)
                findings.append(make_finding(
                    "SI-S006", "WARN", "NEEDS_JUDGMENT",
                    where=f"{rel}:{lineno}",
                    what=(f"A verbatim run of {_SI_S006_NGRAM} words is shared with the linked "
                          f"contract `{contract}`: \"{gram}\""),
                    why=("authoring-principles #5 forbids reinventing a contract. Duplicated text "
                         "drifts: the two copies are edited separately and silently disagree. "
                         "Consolidating an inline duplicate into a contract reference measured "
                         "friction -37%, the largest recorded effect"),
                    how=("Decide which side is canonical. If the contract covers it, replace the "
                         "inline text with a link plus this skill's role-specific values. Keep the "
                         "inline copy only when the section is needed in every scenario of this "
                         "skill — that judgement is not mechanical, which is why this is "
                         "NEEDS_JUDGMENT rather than an automatic fix"),
                    fix_draft=None,
                ))
    return findings


RULES: dict[str, dict[str, Any]] = {
    "SI-S001": {"category": "structural", "severity": "WARN",
                "action": "REPORT_ONLY", "fn": check_si_s001},
    "SI-S002": {"category": "structural", "severity": "WARN",
                "action": "REPORT_ONLY", "fn": check_si_s002},
    "SI-S003": {"category": "structural", "severity": "INFO",
                "action": "REPORT_ONLY", "fn": check_si_s003},
    "SI-S004": {"category": "structural", "severity": "WARN",
                "action": "NEEDS_JUDGMENT", "fn": check_si_s004},
    "SI-S006": {"category": "structural", "severity": "WARN",
                "action": "NEEDS_JUDGMENT", "fn": check_si_s006},
}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def collect_targets(skills_dir: str) -> list[dict]:
    targets = []
    if not os.path.isdir(skills_dir):
        return targets
    for name in sorted(os.listdir(skills_dir)):
        if name.startswith(".") or name == "node_modules":
            continue
        skill_dir = os.path.join(skills_dir, name)
        if os.path.islink(skill_dir):
            continue
        skill_md = os.path.join(skill_dir, "SKILL.md")
        if not os.path.isfile(skill_md):
            continue
        try:
            with open(skill_md, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            continue
        targets.append({
            "name": name,
            "skill_dir": skill_dir,
            "skill_md_content": content,
            "description": _extract_description(content),
        })
    return targets


def run_checks(targets: list[dict], ctx: dict) -> list[dict]:
    findings = []
    for rid in sorted(RULES):
        fn = RULES[rid]["fn"]
        findings.extend(fn(targets, ctx))
    return _assign_ids(findings)


def main():
    parser = argparse.ArgumentParser(description="SI-S* static checks")
    parser.add_argument("--skills-dir", default="skills")
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default=None)
    parser.add_argument("--skill", nargs="*", default=None,
                        help="Audit specific skill(s)")
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    targets = collect_targets(os.path.join(root, args.skills_dir))
    if args.skill:
        skill_set = set(args.skill)
        targets = [t for t in targets if t["name"] in skill_set]

    ctx = {"root": root}
    findings = run_checks(targets, ctx)

    output = json.dumps(findings, ensure_ascii=False, indent=2)
    if args.output:
        d = os.path.dirname(args.output)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"{len(findings)} findings written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
