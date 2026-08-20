#!/usr/bin/env python3
"""
context-audit: findings plus a baseline turned into a summary-first report.

Withholds the findings a baseline records as accepted, counts what remains by severity
and by the way it may be fixed, and lays the result out with the counts ahead of the
findings. The way a finding may be fixed is carried over verbatim from static_checks.py
and never recomputed here, so there stays exactly one place that decides it.

A baseline holds nothing but opaque per-finding identifiers (a digest over the rule, the
place and the description). No detected value and no body text reaches it, which is what
makes a committed baseline safe to read.

The directory the project memory was read from travels alongside the findings rather
than inside them. It is collection provenance, not something a rule found, and a report
that named no memory location would leave the reader unable to tell what was read: the
place a finding names is redacted, and a home-relative location is one of the shapes the
redaction replaces.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ACTIONS = ("AUTO_FIX", "NEEDS_JUDGMENT", "REPORT_ONLY")
_SEVERITY_RANK = {"BLOCK": 0, "WARN": 1, "INFO": 2, "PASS": 3}


def finding_id(finding: dict) -> str:
    """An opaque, stable identifier for one finding."""
    key = f"{finding.get('id')}|{finding.get('where')}|{finding.get('what')}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def apply_suppression(findings: list[dict],
                      baseline: dict | None) -> tuple[list[dict], int]:
    """Withhold the findings the baseline records, and say how many were withheld."""
    suppressed_ids = set((baseline or {}).get("suppressions", []))
    if not suppressed_ids:
        return list(findings), 0
    kept, withheld = [], 0
    for finding in findings:
        if finding_id(finding) in suppressed_ids:
            withheld += 1
        else:
            kept.append(finding)
    return kept, withheld


def build_baseline(findings: list[dict]) -> dict:
    """A baseline over the current findings, holding opaque identifiers and nothing else."""
    return {
        "version": 1,
        "suppressions": sorted({finding_id(f) for f in findings}),
    }


def summarize(findings: list[dict]) -> dict:
    """Count the findings by the way they may be fixed and by severity."""
    by_action = {action: 0 for action in ACTIONS}
    by_severity: dict[str, int] = {}
    for finding in findings:
        action = finding.get("action")
        if action in by_action:
            by_action[action] += 1
        severity = finding.get("severity", "INFO")
        by_severity[severity] = by_severity.get(severity, 0) + 1
    return {**by_action, "total": len(findings), "by_severity": by_severity}


def _sort_key(finding: dict) -> tuple:
    return (_SEVERITY_RANK.get(finding.get("severity"), 9),
            finding.get("id", ""), finding.get("where", ""))


def build_report(findings: list[dict], baseline: dict | None,
                 memory_dir: str | None = None) -> dict:
    """Lay the findings out with the counts ahead of them."""
    kept, suppressed = apply_suppression(findings, baseline)
    ordered = sorted(kept, key=_sort_key)
    for finding in ordered:
        finding["finding_id"] = finding_id(finding)

    counts = summarize(ordered)
    groups: dict[str, list[dict]] = {}
    for finding in ordered:
        groups.setdefault(finding.get("id", "?"), []).append(finding)

    return {
        "summary": {
            "total": counts["total"],
            "AUTO_FIX": counts["AUTO_FIX"],
            "NEEDS_JUDGMENT": counts["NEEDS_JUDGMENT"],
            "REPORT_ONLY": counts["REPORT_ONLY"],
            "suppressed": suppressed,
        },
        "memory_dir": memory_dir,
        "by_severity": counts["by_severity"],
        "groups": [{"rule_id": rule_id, "count": len(group), "findings": group}
                   for rule_id, group in sorted(groups.items())],
        "findings": ordered,
    }


def render_markdown(report: dict) -> str:
    summary = report["summary"]
    memory_dir = report.get("memory_dir")
    lines = [
        "# context-audit report",
        "",
        f"{summary['total']} findings: {summary['AUTO_FIX']} AUTO_FIX / "
        f"{summary['NEEDS_JUDGMENT']} NEEDS_JUDGMENT / "
        f"{summary['REPORT_ONLY']} REPORT_ONLY; {summary['suppressed']} suppressed",
        # Phrased as what the report was told, not as what happened: a run given no
        # collected targets cannot tell "no memory was read" from "nobody said", and a
        # report that picked one would be stating something it does not know.
        f"memory read from: {memory_dir}" if memory_dir
        else "memory: no location reported",
        "",
    ]
    for finding in report["findings"]:
        lines.append(f"- [{finding['severity']}/{finding['action']}] "
                     f"{finding['id']} {finding['where']}")
        lines.append(f"  - {finding['what']}")
    return "\n".join(lines) + "\n"


def _read_json(source: str) -> dict | list:
    raw = sys.stdin.read() if source == "-" \
        else Path(source).read_text(encoding="utf-8")
    return json.loads(raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate the context-audit findings")
    parser.add_argument("findings_json", help="static_checks.py output (path or '-')")
    parser.add_argument("--targets", default=None,
                        help="collect_targets.py output, read for the memory location "
                             "the report names")
    parser.add_argument("--baseline", default=None, help="Baseline JSON path")
    parser.add_argument("--output", default=None, help="Output file (default stdout)")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--update-baseline", default=None, metavar="PATH",
                        help="Write the current findings out as the new baseline "
                             "(identifiers only) to PATH and stop")
    args = parser.parse_args(argv)

    data = _read_json(args.findings_json)
    findings = data["findings"] if isinstance(data, dict) else data

    if args.update_baseline:
        baseline_doc = build_baseline(findings)
        Path(args.update_baseline).write_text(
            json.dumps(baseline_doc, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"baseline_written": args.update_baseline,
                          "suppression_count": len(baseline_doc["suppressions"])}))
        return 0

    memory_dir = None
    if args.targets:
        collected = _read_json(args.targets)
        if isinstance(collected, dict):
            memory_dir = collected.get("memory_dir")

    baseline = None
    if args.baseline and Path(args.baseline).is_file():
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))

    report = build_report(findings, baseline, memory_dir)
    rendered = render_markdown(report) if args.markdown \
        else json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(
            rendered + ("" if rendered.endswith("\n") else "\n"), encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
