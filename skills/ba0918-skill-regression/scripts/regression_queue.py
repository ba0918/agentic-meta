#!/usr/bin/env python3
"""Build a process-delegation work queue from fixtures, and grade what comes back.

This is the producer side that `references/process-queue.md` §11
deliberately leaves out of the runner beside it: turning scenario files into prompt files
plus a `work.jsonl`, then reducing the returned artifacts to a mechanical tally.

It exists so a regression batch can run without spending subagent launches. The dispatch
contract is otherwise the one in `references/executor-contract.md`, with two adaptations
that the process path forces and one that it removes:

- The executor writes its report as **JSON to a declared path**, because the artifact is
  what the runner grades. Prose bullets are not machine-checkable.
- The prompt still withholds the `critical` flags; they live only in the batch manifest,
  so grading stays on the caller's side of the fence.
- The "report channel" problem disappears. A subagent's completion message may never be
  delivered; a file either exists or does not.

`grade` never returns a bare pass. It collapses the mechanical part of the judgement and
names what still needs adjudication, because executor-contract requires the caller to
re-judge any self-report the artifacts do not corroborate.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fixture_setup  # noqa: E402
import process_runner  # noqa: E402

VERDICTS = ("yes", "no", "partial")

# Each unit owns one directory, laid out so a backend that sandboxes writes to the
# process working directory can still deliver its report:
#
#   work/<unit>/          <- the unit's cwd, and the narrowest sandbox that works
#     repo/               <- the staged scenario; what the executor is told to work in
#     report.json         <- the artifact
#
# Measured: an agent CLI confined to its cwd could not write a report placed in a
# sibling results/ directory, burned a full run, and exited 0 with nothing to show.
# Keeping the artifact under the unit's cwd removes that failure mode, and keeps the
# report out of the staged tree so it cannot pollute a "clean working tree" expectation.
STAGED_SUBDIR = "repo"
REPORT_NAME = "report.json"
# A scenario is only ever `fail` or `unadjudicated_pass` here. `pass` is a word this
# script is not entitled to say (see module docstring).
SCENARIO_VERDICTS = ("fail", "unadjudicated_pass", "needs_rerun")

REPORT_SCHEMA = """{
  "artifact": "<one-paragraph summary of what you produced>",
  "execution_path": "<one line: which phases you delegated vs. did inline; \\"n/a\\" if single-step>",
  "expectations": [
    {"index": 1, "verdict": "yes|no|partial", "evidence": "<one line>"}
  ],
  "unclear": ["<points in the skill you had to interpret>"],
  "discretion": ["<choices the instructions did not determine>"]
}"""

# Delimiters for an inlined SKILL.md. Not a fenced code block: skill bodies contain
# fences of their own, and a fence would close on the first one.
SKILL_MD_OPEN = "<skill_md>"
SKILL_MD_CLOSE = "</skill_md>"


class QueueError(Exception):
    """Malformed fixture, batch, or returned report."""


# ==========================================================================
# Prompt rendering (pure)
# ==========================================================================
def render_prompt(skill, scenario, *, skill_md, work_dir, output_file, env=None,
                  skill_md_text=None, empty_work_dir=False):
    """Render one executor prompt.

    Requirements are numbered and stripped of their `critical` flags: an executor that
    knows which items decide the verdict optimises for those items instead of following
    the skill, and the measurement stops being about the skill.

    `skill_md_text` inlines the skill body instead of leaving only its path. A backend
    with no file access cannot follow the path at all, so the path-only prompt hands a
    tool-using backend knowledge the other one cannot reach; measured, that asymmetry
    alone decided an expectation in a parallel run. When the body is inlined the path is
    left out entirely, because an executor that sees one follows it. References are
    deliberately not inlined — one level, and any extension has to be argued from a
    measurement.

    `empty_work_dir` says the scenario staged nothing on disk. Such a fixture carries its
    evidence in the Situation text by design, but only a backend that can list the
    directory can discover the described files are not there; measured, executors split
    on that observation, some declaring the situation unjudgeable while others simply
    read the description. Naming the emptiness removes the split without touching the
    fixture.
    """
    lines = [
        f"You are an executor reading the `{skill}` skill's SKILL.md for the first time.",
        "",
        "## Target skill",
        "",
    ]
    if skill_md_text is None:
        lines += [f"{skill_md}", "", "Read it, and follow any references it points to.", ""]
    else:
        # No path here. Inlining is for a backend that cannot read the file, and
        # printing the location invites it to try: measured, an executor followed
        # the path, had the read refused by its sandbox, and stopped without
        # producing anything — with the body already in front of it.
        lines += [
            f"`{skill}`. Its full text is inlined below and is everything you get: "
            "the files it references are not inlined, and nothing outside the working "
            "directory is available to you. Work from what is here.",
            "",
            SKILL_MD_OPEN,
            skill_md_text.rstrip("\n"),
            SKILL_MD_CLOSE,
            "",
        ]
    lines += [
        "## Working directory",
        "",
        f"{work_dir}",
        "",
        "Work only inside that directory. The one exception is the report file named "
        "in the Task section below; apart from that file, create and edit nothing "
        "outside it.",
        "",
    ]
    if empty_work_dir:
        lines += [
            "No files have been materialised there: the directory is empty. Any file, "
            "diff, or command output the Situation section describes is given to you as "
            "text — treat that text as the primary evidence. Its absence from disk is a "
            "property of this exercise, not a finding about the situation, and not a "
            "reason to withhold a judgement the description supports.",
            "",
        ]
    if env:
        lines += [
            "## Environment setup",
            "",
            "Treat the following as already true of your environment. This section is "
            "context, not a hint about how to solve the situation below.",
            "",
        ]
        lines += [f"- `{name}` = `{value}`" for name, value in sorted(env.items())]
        lines.append("")
    lines += [
        "## Situation",
        "",
        scenario["prompt"],
        "",
        "## Task",
        "",
        "1. Follow the target skill's instructions to handle the situation and produce "
        "whatever it calls for.",
        "2. Then write your report as a JSON file to exactly this path:",
        "",
        f"   {output_file}",
        "",
        "   That file is the only channel that reaches the caller. Anything you print is "
        "discarded, and a run that produces no file counts as a failure however well it "
        "went.",
        "",
        "## Report schema",
        "",
        "```json",
        REPORT_SCHEMA,
        "```",
        "",
        "Emit one `expectations` entry per numbered item below, using the same index. "
        "Assess honestly: `no` and `partial` are useful answers, and a report that "
        "disagrees with your own artifacts is worse than a low score.",
        "",
        "### Items to self-assess",
        "",
    ]
    lines += [
        f"{index}. {expectation['text']}"
        for index, expectation in enumerate(scenario["expectations"], start=1)
    ]
    lines.append("")
    return "\n".join(lines)


def unit_id(skill, scenario_id):
    """Batch-unique unit id. Must satisfy the work-queue id grammar."""
    candidate = f"{skill}-{scenario_id}"
    if not process_runner.ID_RE.fullmatch(candidate):
        raise QueueError(
            f"unit id {candidate!r} is not usable in a work queue "
            f"(allowed: [A-Za-z0-9._-]+)")
    return candidate


# ==========================================================================
# Assert predicates
# ==========================================================================
# The evaluators live here as fixed code and the fixture only declares typed
# predicate objects (#241 ruling c): a fixture that could carry code would hand
# its author arbitrary execution, and a DSL would add a parser surface that a
# handful of predicate types does not justify. Adding a type is a code change,
# so it passes review like any other guarantee.
PREDICATE_KEYS = {
    "file_exists": {"path"},
    "file_regex": {"path", "pattern"},
    "report_regex": {"pattern"},
    "git_clean": set(),
    "git_commit_count": set(),
    "git_head_equals_baseline": set(),
    "git_subject_regex": {"rev", "pattern"},
    "git_subjects_regex": {"pattern"},
    "git_path_committed": {"path"},
    "git_no_commit_touches_both": {"path_a", "path_b"},
}


class _PredicateFailure(Exception):
    """A predicate could not be evaluated (broken git state etc.).

    Reads as a failed expectation, never as a harness error: an executor that
    destroyed the staged state failed whatever was asserted about it.
    """


def _validate_pred(pred, where):
    if not isinstance(pred, dict):
        raise QueueError(f"{where}: assert entry is not an object")
    kind = pred.get("type")
    if kind not in PREDICATE_KEYS:
        raise QueueError(
            f"{where}: unknown predicate type {kind!r} "
            f"(allowed: {', '.join(sorted(PREDICATE_KEYS))})")
    missing = PREDICATE_KEYS[kind] - set(pred)
    if missing:
        raise QueueError(
            f"{where}: predicate {kind} missing {', '.join(sorted(missing))}")
    if kind == "git_commit_count" and not {"equals", "min", "max"} & set(pred):
        raise QueueError(
            f"{where}: git_commit_count needs one of equals/min/max")


def validate_asserts(expectations):
    """Producer-side validation: a batch the grader would reject fails here,
    while it is still cheap to fix (same obligation as the queue dogfooding)."""
    for index, expectation in enumerate(expectations, start=1):
        for pred in expectation.get("assert") or ():
            _validate_pred(pred, where=f"expectation {index}")


def _git_lines(work_dir, args):
    result = fixture_setup._run_git(args, work_dir)
    if result.returncode != 0:
        raise _PredicateFailure((result.stderr or "git failed").strip()[:200])
    return result.stdout.splitlines()


def _eval_one(pred, work_dir, *, baseline_head=None):
    kind = pred["type"]
    expect = pred.get("expect", True)
    if kind == "file_exists":
        actual = os.path.isfile(os.path.join(work_dir, pred["path"]))
        return actual == expect, f"file_exists({pred['path']})={actual}"
    if kind == "file_regex":
        full = os.path.join(work_dir, pred["path"])
        if not os.path.isfile(full):
            return False, f"file_regex({pred['path']}): file missing"
        try:
            content = _read(full)
        except (OSError, UnicodeDecodeError) as exc:
            # An unreadable or binary file is a failed predicate, not a harness
            # crash: what the executor left there is the thing under judgement.
            return False, f"file_regex({pred['path']}): unreadable ({exc})"
        matched = re.search(pred["pattern"], content) is not None
        return (matched == expect,
                f"file_regex({pred['path']}, {pred['pattern']!r})={matched}")
    if kind == "report_regex":
        report_path = os.path.join(work_dir, "..", REPORT_NAME)
        try:
            report = json.loads(_read(report_path))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return False, f"report_regex: the report cannot be read ({exc})"
        artifact = report.get("artifact") if isinstance(report, dict) else None
        if not isinstance(artifact, str):
            return False, "report_regex: report.artifact is not a string"
        matched = re.search(pred["pattern"], artifact) is not None
        return (matched == expect,
                f"report_regex(artifact, {pred['pattern']!r})={matched}")
    if kind == "git_clean":
        actual = not _git_lines(work_dir, ["status", "--porcelain"])
        return actual == expect, f"git_clean={actual}"
    if kind == "git_commit_count":
        count = int(_git_lines(work_dir, ["rev-list", "HEAD", "--count"])[0])
        ok = (count == pred["equals"] if "equals" in pred else True) \
            and (count >= pred["min"] if "min" in pred else True) \
            and (count <= pred["max"] if "max" in pred else True)
        return ok, f"git_commit_count={count}"
    if kind == "git_head_equals_baseline":
        if not baseline_head:
            return False, "git_head_equals_baseline: baseline is missing"
        head = _git_lines(work_dir, ["rev-parse", "HEAD"])[0]
        actual = head == baseline_head
        return actual == expect, f"git_head_equals_baseline={actual}"
    if kind == "git_subject_regex":
        subject = "\n".join(
            _git_lines(work_dir, ["log", "-1", "--format=%s", pred["rev"]]))
        matched = re.search(pred["pattern"], subject) is not None
        return (matched == expect,
                f"git_subject_regex({pred['rev']})={subject!r}")
    if kind == "git_subjects_regex":
        subjects = _git_lines(work_dir, ["log", "--format=%s"])
        skip = pred.get("skip_oldest", 0)
        checked = subjects[:len(subjects) - skip] if skip else subjects
        bad = [s for s in checked if re.search(pred["pattern"], s) is None]
        return ((not bad) == expect,
                f"git_subjects_regex: {len(checked)} checked, bad={bad!r}")
    if kind == "git_path_committed":
        paths = set(_git_lines(work_dir, ["log", "--name-only", "--format="]))
        actual = pred["path"] in paths
        return actual == expect, f"git_path_committed({pred['path']})={actual}"
    if kind == "git_no_commit_touches_both":
        commit_paths = []
        for line in _git_lines(work_dir, ["log", "--name-only", "--format=%H"]):
            if re.fullmatch(r"[0-9a-f]{40}", line):
                commit_paths.append(set())
            elif line and commit_paths:
                commit_paths[-1].add(line)
        mixed = any(pred["path_a"] in paths and pred["path_b"] in paths
                    for paths in commit_paths)
        return ((not mixed) == expect,
                f"git_no_commit_touches_both({pred['path_a']}, "
                f"{pred['path_b']})={not mixed}")
    raise QueueError(f"unhandled predicate type {kind!r}")


def evaluate_assert(preds, work_dir, *, baseline_head=None):
    """Evaluate one expectation's declared predicates against a unit's tree.

    Returns (ok, evidence). All predicates must hold. The machine verdict
    replaces the executor's self-report for the asserted expectation — in both
    directions, because the expectation is defined by post-state, not by what
    the executor believes about it.
    """
    ok_all, evidences = True, []
    for pred in preds:
        _validate_pred(pred, where="assert")
        try:
            ok, evidence = _eval_one(
                pred, work_dir, baseline_head=baseline_head)
        except _PredicateFailure as exc:
            ok, evidence = False, f"{pred['type']}: {exc}"
        ok_all = ok_all and ok
        evidences.append(("PASS " if ok else "FAIL ") + evidence)
    return ok_all, "; ".join(evidences)


# ==========================================================================
# Grading (pure)
# ==========================================================================
def parse_report(text, expected_count):
    """Validate an executor report. Raises QueueError on any protocol violation.

    A malformed report is a *harness* failure, not evidence that the skill regressed —
    the same split empirical-prompt-tuning draws between protocol failure and candidate
    failure. Conflating them makes a broken batch look like a broken skill.
    """
    try:
        report = json.loads(text)
    except json.JSONDecodeError as exc:
        raise QueueError(f"report is not valid JSON: {exc}")
    if not isinstance(report, dict):
        raise QueueError("report is not a JSON object")
    entries = report.get("expectations")
    if not isinstance(entries, list):
        raise QueueError("report has no 'expectations' list")
    if len(entries) != expected_count:
        raise QueueError(
            f"report covers {len(entries)} expectation(s), expected {expected_count}")
    by_index = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise QueueError("a expectations entry is not an object")
        index = entry.get("index")
        if not isinstance(index, int) or not 1 <= index <= expected_count:
            raise QueueError(f"expectation index out of range: {index!r}")
        if index in by_index:
            raise QueueError(f"expectation index {index} appears twice")
        verdict = entry.get("verdict")
        if verdict not in VERDICTS:
            raise QueueError(
                f"expectation {index} has unknown verdict {verdict!r} "
                f"(allowed: {', '.join(VERDICTS)})")
        by_index[index] = entry
    return report, by_index


def grade_scenario(expectations, by_index, *, drifted=(), machine=None):
    """Mechanical part of the scenario judgement.

    `partial` counts as a miss: executor-contract fails safe, because a lenient tally
    empties the ledger of meaning.

    `machine` carries the assert verdicts ({index: {ok, evidence}}) and is
    authoritative for those indexes — the self-report is not consulted, in either
    direction, because an asserted expectation is defined by post-state.

    `baseline_drift` is evidence, never a verdict. Whether an edit to a staged file is a
    violation depends on the expectation, not on the scenario's isolation mode — a
    worktree scenario may legitimately rewrite everything, and a read-only expectation
    inside one is contradicted by a single byte. The script surfaces the drift so the
    caller can hold a self-reported "yes" against it, per executor-contract's rule that
    read-only judgements rest on hash comparison rather than self-report.
    """
    machine = machine or {}
    critical_missed, other_missed = [], []
    for index, expectation in enumerate(expectations, start=1):
        if index in machine:
            verdict = "yes" if machine[index]["ok"] else "no"
            evidence = machine[index]["evidence"]
        else:
            verdict = by_index[index]["verdict"]
            evidence = by_index[index].get("evidence", "")
        if verdict == "yes":
            continue
        target = critical_missed if expectation.get("critical") else other_missed
        target.append({"index": index, "text": expectation["text"],
                       "verdict": verdict, "evidence": evidence})
    return {
        "verdict": "fail" if critical_missed else "unadjudicated_pass",
        "critical_missed": critical_missed,
        "other_missed": other_missed,
        "baseline_drift": sorted(drifted),
        "machine_checked": sorted(machine),
    }


def roll_up(scenarios):
    """Skill-level roll-up. Any non-pass scenario blocks the ledger."""
    verdicts = [s["verdict"] for s in scenarios]
    if not verdicts:
        return "needs_rerun"
    if "needs_rerun" in verdicts:
        return "needs_rerun"
    if "fail" in verdicts:
        return "fail"
    return "unadjudicated_pass"


# ==========================================================================
# Filesystem layer
# ==========================================================================
def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _sha256_file(path):
    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return None


def build(scenario_paths, batch_dir, repo_root, inputs_root, *, scenario_ids=None,
          inline_skill=False):
    """Materialise every scenario and emit prompts, a work queue, and a manifest.

    `inline_skill` embeds each target SKILL.md in the prompt. The same prompt is then
    usable by a backend with file access and by one without, which is the point: the
    comparison is only about the backend once both read the same words. A batch built
    this way carries different scaffolding from one built without it, so the two are not
    comparable evidence (§ Comparability) — the flag is recorded in the manifest so the
    ledger note can say which was used.
    """
    batch_dir = os.path.abspath(batch_dir)
    repo_root = os.path.abspath(repo_root)
    inputs_root = os.path.abspath(inputs_root)
    for sub in ("prompts", "work"):
        os.makedirs(os.path.join(batch_dir, sub), exist_ok=True)

    units, manifest = [], {}
    for scenario_path in scenario_paths:
        scenario = fixture_setup.load_scenario(scenario_path)
        errors = fixture_setup.validate(scenario, source=scenario_path)
        if errors:
            raise QueueError("; ".join(errors))
        skill = scenario["skill"]
        skill_md = os.path.join(repo_root, "skills", skill, "SKILL.md")
        if not os.path.isfile(skill_md):
            raise QueueError(f"target skill has no SKILL.md: {skill_md}")

        if scenario_ids and scenario["id"] not in scenario_ids:
            continue
        validate_asserts(scenario["expectations"])
        uid = unit_id(skill, scenario["id"])
        unit_dir = os.path.join(batch_dir, "work", uid)
        staged = fixture_setup.materialize(
            scenario, os.path.join(unit_dir, STAGED_SUBDIR), inputs_root)
        output_file = os.path.join(unit_dir, REPORT_NAME)
        prompt = render_prompt(
            skill, scenario,
            skill_md=skill_md,
            work_dir=staged["dir"],
            output_file=output_file,
            env=staged["env"],
            skill_md_text=_read(skill_md) if inline_skill else None,
            # Empty only when nothing at all was staged. The baseline map alone
            # cannot decide this: a git-only setup (init + --allow-empty commit,
            # no files) stages a .git the executor can observe, and calling that
            # directory empty would contradict what a tool-using backend sees.
            empty_work_dir=not staged["baseline"] and not staged["git"],
        )
        prompt_rel = os.path.join("prompts", f"{uid}.md")
        with open(os.path.join(batch_dir, prompt_rel), "w",
                  encoding="utf-8") as handle:
            handle.write(prompt)

        units.append({
            "id": uid,
            "prompt_file": prompt_rel,
            "output_file": os.path.join("work", uid, REPORT_NAME),
            "output_format": "json",
            "cwd": os.path.join("work", uid),
        })
        manifest[uid] = {
            "skill": skill,
            "scenario_id": scenario["id"],
            "title": scenario.get("title", scenario["id"]),
            "isolation": scenario.get("isolation", "worktree"),
            "executor_tier": scenario.get("executor_tier", "standard"),
            "expectations": scenario["expectations"],
            "work_dir": staged["dir"],
            "baseline": staged["baseline"],
            "baseline_head": staged["git"].get("baseline"),
            "unmaterialized": staged["unmaterialized"],
            "scenario_path": os.path.abspath(scenario_path),
            "inputs_root": inputs_root,
            "scenario_sha256": fixture_setup.scenario_sha256(scenario),
            # Scaffolding, not fixture: recorded per unit so a later reader can tell
            # which prompt shape produced the report without diffing the prompts.
            "inline_skill": bool(inline_skill),
        }

    if not units:
        raise QueueError("no scenarios selected")

    work_text = "".join(json.dumps(u, sort_keys=True) + "\n" for u in units)
    work_path = os.path.join(batch_dir, "work.jsonl")
    with open(work_path, "w", encoding="utf-8") as handle:
        handle.write(work_text)
    manifest_path = os.path.join(batch_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)

    # Dogfood the producer obligation in process-delegation.md §11: a batch that the
    # runner would reject must fail here, while it is still cheap to fix.
    process_runner.resolve_paths(process_runner.parse_work(work_text), batch_dir)

    unmaterialized = {
        uid: entry["unmaterialized"]
        for uid, entry in manifest.items() if entry["unmaterialized"]
    }
    return {
        "batch": batch_dir,
        "work": work_path,
        "manifest": manifest_path,
        "units": len(units),
        "unmaterialized": unmaterialized,
        "inline_skill": bool(inline_skill),
    }


def rerun(batch_dir, *, units=None):
    """Restore unfinished (or named) units to their fixture baseline for a re-run.

    Deleting a unit's `report.json` alone re-runs the scenario on top of whatever the
    first run's executor left in `work/<unit>/` — measured in batch
    prompt-audit-regression-20260804-r2, a rerun executor found the previous run's
    implementation already sitting in the seed tree, so the scenario's premise (a true
    RED in the seed) no longer held. The runner cannot own this guard: it is fixture
    knowledge, and the runner is deliberately fixture-blind (process-delegation.md §11).

    Refuses when the fixture's scenario no longer matches what `build` staged: grading
    a new scenario with the old manifest key is a rebuild, not a rerun.
    """
    batch_dir = os.path.abspath(batch_dir)
    manifest = json.loads(_read(os.path.join(batch_dir, "manifest.json")))

    unfinished = [
        uid for uid in sorted(manifest)
        if not os.path.isfile(os.path.join(batch_dir, "work", uid, REPORT_NAME))
    ]
    if units:
        unknown = sorted(set(units) - set(manifest))
        if unknown:
            raise QueueError(f"unknown unit(s): {', '.join(unknown)}")
        # Named units ADD to the unfinished set, never replace it: a rerun that
        # skipped the unfinished units would re-run them on contaminated trees —
        # the exact failure this guard exists to stop.
        targets = sorted(set(units) | set(unfinished))
    else:
        targets = unfinished

    for uid in targets:
        entry = manifest[uid]
        if "scenario_path" not in entry or "scenario_sha256" not in entry:
            raise QueueError(
                f"manifest entry {uid} predates rerun support — rebuild the batch")
        # Manifest keys are validated at build time, but the manifest is a plain file;
        # re-check before rmtree so a hand-edited id cannot escape the batch root.
        if not process_runner.ID_RE.fullmatch(uid):
            raise QueueError(f"unit id {uid!r} is not a valid unit id")

        scenario = fixture_setup.load_scenario(entry["scenario_path"])
        if (scenario.get("id") != entry["scenario_id"]
                or fixture_setup.scenario_sha256(scenario)
                != entry["scenario_sha256"]):
            raise QueueError(
                f"scenario {entry['scenario_id']} changed since build (or was "
                f"removed); the manifest grading key no longer matches — rebuild "
                f"the batch")

        unit_dir = os.path.join(batch_dir, "work", uid)
        shutil.rmtree(unit_dir, ignore_errors=True)
        staged = fixture_setup.materialize(
            scenario, os.path.join(unit_dir, STAGED_SUBDIR), entry["inputs_root"])
        if staged["baseline"] != entry["baseline"]:
            raise QueueError(
                f"re-materialised baseline for {uid} does not match the manifest; "
                f"the environment stages this scenario differently now — rebuild "
                f"the batch")

    return {
        "batch": batch_dir,
        "rematerialized": targets,
        "untouched": [uid for uid in sorted(manifest) if uid not in set(targets)],
    }


def grade(batch_dir):
    """Reduce the returned artifacts to a per-skill mechanical tally."""
    batch_dir = os.path.abspath(batch_dir)
    manifest = json.loads(_read(os.path.join(batch_dir, "manifest.json")))

    by_skill = {}
    for uid in sorted(manifest):
        entry = manifest[uid]
        expectations = entry["expectations"]
        result = {"unit": uid, "scenario_id": entry["scenario_id"],
                  "title": entry["title"]}

        artifact = os.path.join(batch_dir, "work", uid, REPORT_NAME)
        state = process_runner.artifact_state(
            process_runner.read_text(artifact), "json")
        if state != "ok":
            result.update({"verdict": "needs_rerun",
                           "harness_error": f"{state}_artifact"})
        else:
            try:
                report, by_index = parse_report(_read(artifact), len(expectations))
            except QueueError as exc:
                result.update({"verdict": "needs_rerun",
                               "harness_error": "malformed_report",
                               "detail": str(exc)})
            else:
                drifted = [
                    path for path, digest in entry["baseline"].items()
                    if _sha256_file(os.path.join(entry["work_dir"], path)) != digest
                ]
                machine = {}
                for index, expectation in enumerate(expectations, start=1):
                    preds = expectation.get("assert")
                    if preds:
                        ok, evidence = evaluate_assert(
                            preds, entry["work_dir"],
                            baseline_head=entry.get("baseline_head"))
                        machine[index] = {"ok": ok, "evidence": evidence}
                result.update(grade_scenario(
                    expectations, by_index, drifted=drifted, machine=machine))
                result["execution_path"] = report.get("execution_path", "")
                result["unclear"] = report.get("unclear", [])
        by_skill.setdefault(entry["skill"], []).append(result)

    return {
        "batch": batch_dir,
        "skills": {
            skill: {"verdict": roll_up(results), "scenarios": results}
            for skill, results in sorted(by_skill.items())
        },
    }


# ==========================================================================
# CLI
# ==========================================================================
def _cli_build(args):
    summary = build(args.case, args.batch, args.repo_root, args.inputs,
                    scenario_ids=set(args.scenario) if args.scenario else None,
                    inline_skill=args.inline_skill)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cli_grade(args):
    print(json.dumps(grade(args.batch), ensure_ascii=False, indent=2,
                     sort_keys=True))
    return 0


def _cli_rerun(args):
    print(json.dumps(rerun(args.batch, units=args.unit), ensure_ascii=False,
                     indent=2, sort_keys=True))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Scenarios -> process-delegation work queue -> mechanical tally.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    build_parser = sub.add_parser("build", help="materialise scenarios into a batch")
    build_parser.add_argument("--case", action="append", required=True,
                              help="path to one scenario file (repeatable)")
    build_parser.add_argument("--inputs", required=True,
                              help="directory holding the scenarios' input files")
    build_parser.add_argument("--batch", required=True, help="batch directory to create")
    build_parser.add_argument("--repo-root", default=".")
    build_parser.add_argument("--scenario", action="append",
                              help="restrict to these scenario ids (repeatable)")
    build_parser.add_argument(
        "--inline-skill", action="store_true",
        help="inline the target SKILL.md body into each prompt, so a backend without "
             "file access reads the same words as one with it")
    build_parser.set_defaults(func=_cli_build)

    grade_parser = sub.add_parser("grade", help="tally the returned reports")
    grade_parser.add_argument("--batch", required=True)
    grade_parser.set_defaults(func=_cli_grade)

    rerun_parser = sub.add_parser(
        "rerun", help="restore unfinished units to their declared baseline")
    rerun_parser.add_argument("--batch", required=True)
    rerun_parser.add_argument("--unit", action="append",
                              help="also reset these finished unit ids (repeatable)")
    rerun_parser.set_defaults(func=_cli_rerun)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (QueueError, fixture_setup.MaterializeError, process_runner.ParseError,
            process_runner.ContainmentError, OSError) as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)},
                         ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
