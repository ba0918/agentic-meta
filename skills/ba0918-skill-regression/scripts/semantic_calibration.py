#!/usr/bin/env python3
"""Measuring how far a semantic judge can be trusted, before it is trusted.

Deciding that a diff "does not affect behaviour" is the judgment this instrument
otherwise says a machine cannot make. Handing it to a model is defensible only if
the model's own unreliability is measured first, and the direction that matters is
the false negative: called unaffected while it was not. A false positive merely
costs a rerun.

The corpus has two sides:

  calibration/must_flag/*.json  edits that indisputably change behaviour
  calibration/must_pass/*.json  edits that indisputably do not

Case shape: {id, expected, before, after, requirements[], mutation?, label?, notes?}

**The score is not kept.** A calibration record names a model and a date, and the
same name can be serving something else tomorrow, with nothing in the record to
show it went stale. The corpus is small, so a run that wants to use semantic
triage measures the judge as part of that run and carries the result in its own
evidence.

**This module cannot start anything.** The judge never launches work in any
direction, and that boundary is held by the absence of the dependency rather than
by a promise in prose — a test walks this source to keep it that way.

CLI:
  python3 semantic_calibration.py --validate [--min-cases N] [root]
      check the corpus schema and its size
  python3 semantic_calibration.py --score RESULTS.json [--min-cases N] [root]
      score a set of verdicts and report whether the gate opens.
      RESULTS.json is {"model": "<judge identifier>", "results": {case_id: verdict}}
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lock  # noqa: E402

MIN_CASES = lock.MIN_CALIBRATION_CASES
CORPUS_DIR = "calibration"
SIDES = ("must_flag", "must_pass")
CASE_FIELDS = ("id", "expected", "before", "after", "requirements")
EXPECTED_BY_SIDE = {"must_flag": "must-flag", "must_pass": "must-pass"}


def _case_errors(case, side):
    """Everything wrong with one case, or an empty list."""
    if not isinstance(case, dict):
        return ["the case is not a JSON object"]
    missing = [f"a required field is missing: {field}"
               for field in CASE_FIELDS if field not in case]
    if missing:
        return missing
    if case["expected"] not in EXPECTED_BY_SIDE.values():
        return [f"expected is neither must-flag nor must-pass: {case['expected']!r}"]
    if case["expected"] != EXPECTED_BY_SIDE[side]:
        # Letting this through would quietly reverse the direction of the scoring.
        return [f"expected contradicts the directory: {case['expected']} "
                f"under {side}/"]
    problems = []
    for field in ("id", "before", "after"):
        if not isinstance(case[field], str) or not case[field].strip():
            problems.append(f"{field} is empty")
    if case["before"] == case["after"]:
        problems.append("before and after are identical, so nothing was edited")
    requirements = case["requirements"]
    if (not isinstance(requirements, list) or not requirements
            or not all(isinstance(r, str) and r.strip() for r in requirements)):
        problems.append("requirements is not a non-empty list of strings")
    return problems


def _corpus_root(root):
    return os.path.join(root, CORPUS_DIR)


def load_corpus(root):
    """The corpus as ({id: case}, errors). A case with problems is dropped."""
    cases, errors, seen = {}, [], {}
    for side in SIDES:
        directory = os.path.join(_corpus_root(root), side)
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(directory, name), encoding="utf-8") as handle:
                    case = json.load(handle)
            except (json.JSONDecodeError, OSError) as exc:
                errors.append(f"{side}/{name}: cannot be read as JSON ({exc})")
                continue
            problems = _case_errors(case, side)
            if problems:
                errors += [f"{side}/{name}: {problem}" for problem in problems]
                continue
            if case["id"] in seen:
                # Ids are what scoring joins on; a duplicate drops one verdict.
                errors.append(f"{side}/{name}: duplicate id {case['id']} "
                              f"(already at {seen[case['id']]})")
                continue
            seen[case["id"]] = f"{side}/{name}"
            cases[case["id"]] = case
    return cases, errors


def validate_corpus(root, min_cases=MIN_CASES):
    """Schema problems and size shortfalls together. Empty means the corpus is sound."""
    cases, errors = load_corpus(root)
    for side, expected in EXPECTED_BY_SIDE.items():
        count = sum(1 for case in cases.values() if case["expected"] == expected)
        if count < min_cases:
            errors.append(f"{side}: only {count} cases, {min_cases} are needed")
    return errors


def corpus_sha256(root):
    """A fingerprint of the corpus, so a score can be tied to what it scored."""
    cases, _ = load_corpus(root)
    digest = hashlib.sha256()
    for case_id in sorted(cases):
        digest.update(json.dumps(cases[case_id], ensure_ascii=False,
                                 sort_keys=True).encode("utf-8"))
        digest.update(b"\x1e")
    return digest.hexdigest()


def score(cases, results):
    """Score a set of verdicts, as (tally, errors).

    Only `unaffected` on a must-flag case counts as a false negative: `unclear`
    means the judge did not commit, so the question reaches a human and nothing
    unsafe is recorded. On the must-pass side anything other than `unaffected`
    is a false positive — affected and unclear both fail to save the rerun.

    A missing verdict is an error rather than a quiet exclusion; otherwise a
    perfect calibration could be assembled from a single judged case.
    """
    errors = []
    unknown = sorted(set(results) - set(cases))
    if unknown:
        errors.append("verdicts for cases not in the corpus: " + ", ".join(unknown))
    absent = sorted(set(cases) - set(results))
    if absent:
        errors.append("cases with no verdict: " + ", ".join(absent))
    false_negatives, false_positives = [], []
    for case_id in sorted(cases):
        verdict = results.get(case_id)
        if verdict is None:
            continue
        if verdict not in lock.VERDICTS:
            errors.append(f"{case_id}: not one of the three verdicts: {verdict!r}")
            continue
        if cases[case_id]["expected"] == "must-flag":
            if verdict == lock.VERDICT_UNAFFECTED:
                false_negatives.append(case_id)
        elif verdict != lock.VERDICT_UNAFFECTED:
            false_positives.append(case_id)
    scored = {
        "must_flag_fn": len(false_negatives),
        "must_pass_fp": len(false_positives),
        "false_negatives": false_negatives,
        "false_positives": false_positives,
        "cases": len(cases),
    }
    for side, expected in EXPECTED_BY_SIDE.items():
        scored[f"{side}_cases"] = sum(
            1 for case in cases.values() if case["expected"] == expected)
    return scored, errors


def gate_reason(scored, errors, min_cases=MIN_CASES):
    """Why this judge may not have its `unaffected` verdicts recorded, or None.

    One false negative is enough to close it: the whole point of the measurement
    is that direction. False positives do not close it — they only cost reruns,
    which is the safe way to be wrong.
    """
    if errors:
        return "the calibration did not score cleanly: " + "; ".join(errors)
    if scored.get("must_flag_fn", 1) != 0:
        return (f"{scored['must_flag_fn']} behaviour-changing case(s) were called "
                f"unaffected")
    for side in SIDES:
        count = scored.get(f"{side}_cases", 0)
        if count < min_cases:
            return f"{side} has only {count} cases, {min_cases} are needed"
    return None


def main(argv):
    args = list(argv)
    min_cases = MIN_CASES
    if "--min-cases" in args:
        index = args.index("--min-cases")
        min_cases = int(args[index + 1])
        del args[index:index + 2]
    results_path = None
    if "--score" in args:
        index = args.index("--score")
        results_path = args[index + 1]
        del args[index:index + 2]
    validate_only = "--validate" in args
    if validate_only:
        args.remove("--validate")
    root = args[0] if args else os.getcwd()

    if validate_only or results_path is None:
        problems = validate_corpus(root, min_cases)
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1 if problems else 0

    with open(results_path, encoding="utf-8") as handle:
        payload = json.load(handle)
    cases, corpus_errors = load_corpus(root)
    scored, errors = score(cases, payload.get("results") or {})
    reason = gate_reason(scored, corpus_errors + errors, min_cases)
    report = {
        "model": payload.get("model"),
        "corpus_sha256": corpus_sha256(root),
        "scored": scored,
        "gate": "open" if reason is None else "closed",
        "reason": reason,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if reason is None else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
