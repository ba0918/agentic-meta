#!/usr/bin/env python3
"""
trigger-eval: Metrics aggregation (pure functions).

Implements the formulas in references/metrics-spec.md over a list of
pre-fixed cases with recorded judgments. The judge is non-deterministic,
but aggregation over the judgment JSON is fully deterministic, so unit
tests use hand-written judgment fixtures.

Case schema: {case_id, gold, judgments: [j1, j2?]}
  - Metrics (TP/FN/FP / confusion / specificity / invalid_rate) use j1 only.
  - The (j1, j2) pair feeds stability only.

Label space: normalized bare skill names + "none" + "INVALID" bucket.
"""

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path
from typing import Any

INVALID = "INVALID"
NONE = "none"


def normalize_judgment(j: Any, valid_labels: set[str]) -> str:
    """Normalize a raw judgment to a label in the label space.

    valid_labels must include the skill names and "none". Anything else
    -- unparseable, a name outside the list, or multiple skills -- becomes
    INVALID. (Generation of INVALID at judge time is judge-protocol.md's
    job; this function only enforces the counting-side invariant.)
    """
    if isinstance(j, str):
        if j == INVALID:
            return INVALID
        if j in valid_labels:
            return j
        return INVALID
    # list (multiple skills), None, or any other type
    return INVALID


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def aggregate(
    cases: list[dict[str, Any]],
    valid_skills: list[str],
    stability_sample_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Aggregate metrics from cases per metrics-spec.md."""
    valid_labels = set(valid_skills) | {NONE}

    # Precompute j1 (and j2) normalized labels per case.
    rows = []
    for c in cases:
        judgments = c.get("judgments", [])
        j1 = normalize_judgment(judgments[0], valid_labels) if judgments else INVALID
        j2 = (
            normalize_judgment(judgments[1], valid_labels)
            if len(judgments) > 1
            else None
        )
        rows.append({"case_id": c.get("case_id"), "gold": c.get("gold"), "j1": j1, "j2": j2})

    # --- Confusion counts: confusion[gold][j1] ---
    confusion: dict[str, dict[str, int]] = {}
    for r in rows:
        confusion.setdefault(r["gold"], {})
        confusion[r["gold"]][r["j1"]] = confusion[r["gold"]].get(r["j1"], 0) + 1

    # --- per-skill TP / FN / FP ---
    per_skill: dict[str, dict[str, Any]] = {}
    for s in valid_skills:
        tp = sum(1 for r in rows if r["gold"] == s and r["j1"] == s)
        fn = sum(1 for r in rows if r["gold"] == s and r["j1"] != s)
        fp = sum(1 for r in rows if r["gold"] != s and r["j1"] == s)
        recall = tp / (tp + fn) if (tp + fn) > 0 else None
        precision = tp / (tp + fp) if (tp + fp) > 0 else None
        per_skill[s] = {
            "tp": tp,
            "fn": fn,
            "fp": fp,
            "recall": recall,
            "precision": precision,
        }

    # --- macro / micro ---
    macro_recall = _mean([p["recall"] for p in per_skill.values() if p["recall"] is not None])
    macro_precision = _mean(
        [p["precision"] for p in per_skill.values() if p["precision"] is not None]
    )
    tp_sum = sum(p["tp"] for p in per_skill.values())
    fn_sum = sum(p["fn"] for p in per_skill.values())
    fp_sum = sum(p["fp"] for p in per_skill.values())
    micro_recall = tp_sum / (tp_sum + fn_sum) if (tp_sum + fn_sum) > 0 else None
    micro_precision = tp_sum / (tp_sum + fp_sum) if (tp_sum + fp_sum) > 0 else None

    # --- specificity (gold none) ---
    none_denom = sum(1 for r in rows if r["gold"] == NONE)
    none_num = sum(1 for r in rows if r["gold"] == NONE and r["j1"] == NONE)
    specificity_value = none_num / none_denom if none_denom > 0 else None

    # --- invalid rate (j1) ---
    invalid_count = sum(1 for r in rows if r["j1"] == INVALID)
    invalid_rate = invalid_count / len(rows) if rows else 0.0

    # --- stability (j1, j2 exact match on the paired sample) ---
    paired = [r for r in rows if r["j2"] is not None]
    if stability_sample_ids is not None:
        sample_set = set(stability_sample_ids)
        paired = [r for r in paired if r["case_id"] in sample_set]
    matches = sum(1 for r in paired if r["j1"] == r["j2"])
    stability_value = matches / len(paired) if paired else None

    # --- confusion cells (non-zero only) + pair ranking ---
    cells = []
    for gold in sorted(confusion):
        for pred in sorted(confusion[gold]):
            cells.append({"gold": gold, "pred": pred, "count": confusion[gold][pred]})

    gold_counts: dict[str, int] = {}
    for r in rows:
        gold_counts[r["gold"]] = gold_counts.get(r["gold"], 0) + 1

    pair_labels = sorted(set(valid_skills) | {NONE})
    pairs = []
    for a, b in combinations(pair_labels, 2):
        raw = confusion.get(a, {}).get(b, 0) + confusion.get(b, {}).get(a, 0)
        if raw == 0:
            continue
        related = gold_counts.get(a, 0) + gold_counts.get(b, 0)
        normalized = raw / related if related > 0 else 0.0
        pairs.append({"a": a, "b": b, "raw": raw, "related": related, "normalized": normalized})
    pairs.sort(key=lambda p: (-p["raw"], -p["normalized"], p["a"], p["b"]))

    return {
        "case_count": len(rows),
        "macro": {"recall": macro_recall, "precision": macro_precision},
        "micro": {"recall": micro_recall, "precision": micro_precision},
        "per_skill": per_skill,
        "specificity": {"value": specificity_value, "num": none_num, "denom": none_denom},
        "invalid_count": invalid_count,
        "invalid_rate": invalid_rate,
        "stability": {
            "value": stability_value,
            "matches": matches,
            "sample_size": len(paired),
        },
        "confusion": {"cells": cells, "pairs": pairs},
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate trigger-eval judgment JSON into metrics"
    )
    parser.add_argument(
        "input", type=str, help="Cases JSON: {cases:[...], valid_skills:[...]} (or '-')"
    )
    parser.add_argument("--output", type=str, default=None, help="Output file (default stdout)")
    args = parser.parse_args()

    if args.input == "-":
        data = json.load(sys.stdin)
    else:
        data = json.loads(Path(args.input).read_text(encoding="utf-8"))

    cases = data["cases"]
    valid_skills = data["valid_skills"]
    sample_ids = data.get("stability_sample_ids")
    result = aggregate(cases, valid_skills, stability_sample_ids=sample_ids)

    json_str = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(json_str + "\n", encoding="utf-8")
    else:
        print(json_str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
