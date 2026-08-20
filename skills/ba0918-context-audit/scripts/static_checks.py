#!/usr/bin/env python3
"""ba0918-context-audit: the pure-function CA-* rule engine.

Every rule is a pure function `check(targets, ctx) -> list[Finding]` listed in RULES,
and this module is the dispatcher over that list. Adding a rule is writing the
function, listing it, and adding its tests; no existing rule is touched.

A finding carries, whichever rule produced it:
  id, severity, action, where(file:line), what, why, how, fix_action({old,new,path}|None)

Every text a finding carries is passed through the credential mask before it leaves
this module, so a value detected in an instruction file never reaches the findings
that get written out. The masking happens in one place, finalize_findings.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import secret_detect  # noqa: E402

# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

CANONICAL_FINDING_FIELDS = ("id", "severity", "action", "where", "what", "why",
                            "how", "fix_action")

_MASKED_FINDING_FIELDS = ("where", "what", "why", "how")


def make_finding(rule_id, severity, action, where, what, why, how, fix_action=None):
    return {"id": rule_id, "severity": severity, "action": action, "where": where,
            "what": what, "why": why, "how": how, "fix_action": fix_action}


def validate_finding_schema(finding: dict) -> list[str]:
    """Name the required fields the finding does not carry (empty list = complete)."""
    return [key for key in CANONICAL_FINDING_FIELDS if key not in finding]


def _mask_fix_action(fix_action: dict) -> dict:
    # 'path' names the file a fix opens, and one of the credential patterns matches a
    # path under a user's home directory. Masking it would leave a fix pointing at a
    # placeholder, so only the text a fix carries is masked, never its destination.
    return {
        key: (secret_detect.mask_secrets(value)
              if key != "path" and isinstance(value, str) else value)
        for key, value in fix_action.items()
    }


def finalize_findings(findings: list[dict]) -> list[dict]:
    """Mask credentials in every text a finding carries, including its fix."""
    masked = []
    for finding in findings:
        out = dict(finding)
        for key in _MASKED_FINDING_FIELDS:
            if isinstance(out.get(key), str):
                out[key] = secret_detect.mask_secrets(out[key])
        if isinstance(out.get("fix_action"), dict):
            out["fix_action"] = _mask_fix_action(out["fix_action"])
        masked.append(out)
    return masked


# ---------------------------------------------------------------------------
# Registry (dispatch by listing, not by editing the dispatcher)
# ---------------------------------------------------------------------------

RULES: dict[str, dict[str, Any]] = {}


def run_checks(targets: list[dict], ctx: dict, rules: dict | None = None) -> list[dict]:
    """Run every listed rule in identifier order and mask what they report."""
    listed = RULES if rules is None else rules
    findings: list[dict] = []
    for rule_id in sorted(listed):
        findings.extend(listed[rule_id]["fn"](targets, ctx))
    return finalize_findings(findings)


def build_context(root: str, targets: list[dict]) -> dict:
    root = os.path.abspath(root)
    skill_names = set()
    skills_dir = os.path.join(root, "skills")
    if os.path.isdir(skills_dir):
        skill_names = {
            name for name in os.listdir(skills_dir)
            if os.path.isdir(os.path.join(skills_dir, name)) and name != "shared"
        }
    return {"root": root, "skill_names": skill_names}


def _attach_content(targets: list[dict]) -> list[dict]:
    attached = []
    for target in targets:
        content = target.get("content")
        if content is None:
            try:
                with open(target["path"], encoding="utf-8", errors="replace") as handle:
                    content = handle.read()
            except OSError:
                continue
        attached.append({**target, "content": content})
    return attached


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the context-audit static checks")
    parser.add_argument("targets_json", help="collect_targets.py output (path or '-')")
    parser.add_argument("--root", default=".", help="Project root")
    parser.add_argument("--output", default=None, help="Output file (default stdout)")
    args = parser.parse_args(argv)

    raw = sys.stdin.read() if args.targets_json == "-" \
        else Path(args.targets_json).read_text(encoding="utf-8")
    data = json.loads(raw)
    targets = _attach_content(data["targets"] if isinstance(data, dict) else data)
    ctx = build_context(args.root, targets)
    findings = run_checks(targets, ctx)

    rendered = json.dumps(
        {"finding_count": len(findings), "findings": findings},
        indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
