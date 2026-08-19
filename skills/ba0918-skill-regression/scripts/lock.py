#!/usr/bin/env python3
"""The verification lock: what it records, and how a tree is judged against it.

`regression-lock.json` at the repository root records a verification event — that
while a skill's behaviour surface held this exact content, every one of its
scenarios passed, or was explicitly judged not to need rerunning. When the
surface moves and the lock stays behind, the skill is reported stale, which is
how a shared contract edit stops silently changing the behaviour of every skill
citing it.

It is a lock in the ordinary sense, and it sits where a lock sits: at the root of
the repository it describes, committed alongside it. Inside the instrument's own
directory it would be replaced by every update that reinstalls the skill.

**What it does not record.** Nothing about the route a run took, the model that
ran it, or what it cost. Those are facts about one environment, and the lock
travels to every environment that clones the repository. Cost history and judge
calibration live with the environment that produced them.

**Being stale asks for a recorded judgment, not a rerun.** Rerunning is expensive
and whoever demands it does not pay for it. What the lock refuses is leaving the
drift unaddressed: it must be resolved by a rerun or by an acceptance that says,
on the record, why one was not needed.

Only skills that have scenarios are tracked, so coverage is opt-in and a skill
with none is outside the check rather than silently passing it.
"""
import datetime
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dep_graph  # noqa: E402
import fixture_setup  # noqa: E402
import md_structure  # noqa: E402

LOCK_REL = "regression-lock.json"
CASES_DIR = "evals/cases"
MISSING = "MISSING"

SEVERITY_CHANGE = "contract-change"
SEVERITY_ADDITION = "contract-addition"
SEVERITY_PROSE = "prose-change"

RESULT_PASS = "pass"
RESULT_ACCEPTED_ADDITION = "accepted-addition"
RESULT_ACCEPTED_PROSE = "accepted-prose"
RESULT_ACCEPTED_SEMANTIC = "accepted-semantic"
RESULT_ACCEPTED_WITHOUT_RUN = "accepted-without-run"

# The three answers a semantic judge may give about a diff. `unclear` is not a
# failure of the judge — it is the answer that sends the question to a human.
VERDICT_UNAFFECTED = "unaffected"
VERDICT_UNCLEAR = "unclear"
VERDICT_AFFECTED = "affected"
VERDICTS = (VERDICT_UNAFFECTED, VERDICT_UNCLEAR, VERDICT_AFFECTED)

# Both sides of the calibration corpus need enough cases that a clean score means
# something. Twenty is the floor the corpus was built to clear.
MIN_CALIBRATION_CASES = 20

# The scenario content hash is defined once, next to the declaration it hashes.
# A second implementation here would let the rerun guard and the carry-over rule
# disagree about whether a declaration-only edit needs a run.
scenario_sha256 = fixture_setup.scenario_sha256


class LockError(Exception):
    """The tree could not be read well enough to judge it."""


def _file_sha256(root, rel):
    path = os.path.join(root, rel)
    if not os.path.isfile(path):
        return MISSING
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def file_hashes(root, files):
    """{repository-relative path: sha256}, with MISSING standing for absent."""
    return {rel: _file_sha256(root, rel) for rel in files}


def fingerprint(root, files):
    """One content fingerprint over a file set. Order-independent and deterministic."""
    hashes = file_hashes(root, files)
    digest = hashlib.sha256()
    for rel in sorted(hashes):
        digest.update(f"{rel}\n{hashes[rel]}\n".encode("utf-8"))
    return digest.hexdigest()


def structural_hashes(root, files):
    """Structural fingerprints of the markdown files, for the prose-only judgment.

    Files that are not markdown have no notion of prose, and a file that cannot
    be read has nothing to compare; both are simply absent here, which the
    severity rule reads as "no material" and answers on the heavy side.
    """
    out = {}
    for rel in files:
        if not rel.endswith(".md"):
            continue
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        except UnicodeDecodeError:
            continue
        out[rel] = md_structure.structural_fingerprint(text)
    return out


def skill_surface(root, skill):
    """The behaviour surface of one skill."""
    return dep_graph.behavior_surface(root, skill)


def stale_severity(recorded, current, recorded_struct=None, current_struct=None,
                   own_prefix=None):
    """How heavy the drift is, as (severity, changed files). (None, []) when equal.

    `recorded` and `current` map repository-relative paths to hashes, MISSING for
    absent. The structural maps and `own_prefix` (a skill's own path prefix) are
    optional, and leaving one out means that material is unavailable — which
    always answers on the heavy side.

    Three answers. Files only added to the surface is `contract-addition`; every
    modification to an existing markdown file being prose alone, proven by equal
    structural fingerprints, is `prose-change`; anything else is
    `contract-change`. Every uncertain path lands on the heavy one: an added file
    that is not actually there (a broken reference), an entry with no recorded
    hashes to compare against, an addition from outside the skill's own directory
    (unverified content arriving through a bare-path reference), and a
    modification to a file with no structural record.

    The material is confined to hash differences on purpose. Judging against git
    history would make the answer depend on which commits are in view; comparing
    against the content the lock recorded makes it depend only on the tree.
    """
    added = sorted(set(current) - set(recorded))
    removed = sorted(set(recorded) - set(current))
    modified = sorted(rel for rel in set(recorded) & set(current)
                      if recorded[rel] != current[rel])
    changed = sorted(added + removed + modified)
    if not changed:
        return None, []
    dangling = [rel for rel in added if current[rel] == MISSING]
    foreign = [] if own_prefix is None else [
        rel for rel in added if not rel.startswith(own_prefix)]
    if not recorded or removed or dangling or foreign:
        return SEVERITY_CHANGE, changed
    if modified:
        recorded_struct = recorded_struct or {}
        current_struct = current_struct or {}
        prose_only = all(
            rel in recorded_struct and rel in current_struct
            and recorded_struct[rel] == current_struct[rel]
            for rel in modified)
        return (SEVERITY_PROSE if prose_only else SEVERITY_CHANGE), changed
    return SEVERITY_ADDITION, changed


def accept_result(recorded, current, prev_result, recorded_struct=None,
                  current_struct=None, own_prefix=None):
    """Which acceptance value to record, from the severity and the previous result.

    Only an acceptance that is mechanically confirmed as addition-only or
    prose-only **and stands on a previous real run** earns the lighter names. Were
    a light acceptance allowed on top of an earlier acceptance, a lock could take
    them forever without a single run and never be counted as such. Both lighter
    names mean "a safe difference from content a run confirmed", which is not
    something an acceptance can be the ground for.

    A difference of zero also lands here rather than on a light name: an
    acceptance that added nothing has nothing to be light about.
    """
    severity, _ = stale_severity(recorded, current, recorded_struct,
                                 current_struct, own_prefix)
    if prev_result == RESULT_PASS:
        if severity == SEVERITY_ADDITION:
            return RESULT_ACCEPTED_ADDITION
        if severity == SEVERITY_PROSE:
            return RESULT_ACCEPTED_PROSE
    return RESULT_ACCEPTED_WITHOUT_RUN


def scenario_dir(root, skill):
    return os.path.join(root, CASES_DIR.replace("/", os.sep), skill)


def load_scenarios(root, skill):
    """Every scenario declared for a skill, ordered by file name.

    A file that cannot be read stops the read instead of being skipped: passing
    over it would drop a scenario from the run while the report still counted the
    skill as covered.
    """
    directory = scenario_dir(root, skill)
    if not os.path.isdir(directory):
        return []
    scenarios = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith((".yaml", ".yml")):
            continue
        path = os.path.join(directory, name)
        try:
            scenario = fixture_setup.load_scenario(path)
        except fixture_setup.MaterializeError as exc:
            raise LockError(str(exc)) from exc
        if not isinstance(scenario, dict) or not scenario.get("id"):
            raise LockError(f"{path}: declares no id")
        scenarios.append(scenario)
    return scenarios


def _skills_with_scenarios(root):
    base = os.path.join(root, CASES_DIR.replace("/", os.sep))
    if not os.path.isdir(base):
        return set()
    return {name for name in os.listdir(base)
            if os.path.isdir(os.path.join(base, name)) and load_scenarios(root, name)}


def _all_skills(root):
    base = os.path.join(root, "skills")
    if not os.path.isdir(base):
        return set()
    return {name for name in os.listdir(base)
            if name != "shared"
            and os.path.isfile(os.path.join(base, name, "SKILL.md"))}


def declared_dependencies(scenario, surface):
    """What a scenario claims it touches, or None when it makes no usable claim.

    None means "no claim, so any change could reach it". The claim is complete —
    nothing outside it and the skill's own body is touched — so one path that is
    not on the surface discredits the whole claim: a typo or a moved reference
    would otherwise buy a carry-over the scenario has not earned.
    """
    declared = scenario.get("exercises")
    if not isinstance(declared, list):
        return None
    if any(path not in surface for path in declared):
        return None
    return set(declared)


def changed_scenarios(scenarios, recorded_scenarios):
    """Scenario ids whose declaration content moved, or that are new."""
    if not recorded_scenarios:
        # Nothing to compare against, and no ground for calling them unchanged.
        return {s["id"] for s in scenarios}
    return {s["id"] for s in scenarios
            if recorded_scenarios.get(s["id"], {}).get("scenario_sha256")
            != scenario_sha256(s)}


def impacted_scenarios(skill, surface, scenarios, changed, recorded_scenarios=None):
    """Which scenario ids a set of changed files reaches, sorted.

    Every rule prefers the safe answer, falling back to every scenario whenever
    the material runs out:

    - the skill's own body is an implicit dependency of every scenario
    - a changed path that is neither on the surface nor a scenario file cannot be
      reconciled with any declaration
    - a changed scenario file reaches the scenario it declares, when its content
      actually moved
    - any other surface file reaches the scenarios declaring it, plus every
      scenario that makes no usable claim
    """
    surface = set(surface)
    changed = set(changed)
    ids = sorted(s["id"] for s in scenarios)
    if not changed:
        return []
    skill_md = f"skills/{skill}/SKILL.md"
    case_prefix = f"{CASES_DIR}/{skill}/"
    case_changes = {p for p in changed if p.startswith(case_prefix)}
    others = changed - case_changes - {skill_md}
    if skill_md in changed or (others - surface):
        return ids
    impacted = set()
    if others:
        for scenario in scenarios:
            deps = declared_dependencies(scenario, surface)
            if deps is None or (others & deps):
                impacted.add(scenario["id"])
    if case_changes:
        impacted |= changed_scenarios(scenarios, recorded_scenarios)
    return sorted(impacted)


def carryover_dependencies(skill, scenario, surface):
    """The files whose hashes must be unmoved for a previous pass to carry over."""
    deps = declared_dependencies(scenario, set(surface))
    if deps is None:
        return set(surface)
    return deps | {f"skills/{skill}/SKILL.md"}


def carryover_reason(skill, scenario, surface, recorded_hashes, current_hashes,
                     recorded_scenarios):
    """Why a previous pass cannot be carried over, or None when it can.

    Validity is established by induction on the previous entry: that entry held
    this scenario as valid, so if the scenario's own definition has not moved and
    not one byte of what it depends on has moved, the pass still holds. That is
    what lets the lock carry scenarios forward without storing per-scenario file
    hashes.

    Every case where the material is missing refuses the carry-over: no record in
    the previous entry, a dependency that was absent when it was recorded (a
    broken reference), or one that was not on the previous surface at all.
    """
    recorded = (recorded_scenarios or {}).get(scenario["id"])
    if not recorded:
        return "the previous entry holds no record for this scenario"
    if recorded.get("scenario_sha256") != scenario_sha256(scenario):
        return "the scenario declaration changed since it was verified"
    unbacked, drifted = [], []
    for rel in sorted(carryover_dependencies(skill, scenario, surface)):
        previous = recorded_hashes.get(rel)
        if previous is None or previous == MISSING:
            unbacked.append(rel)
        elif previous != current_hashes.get(rel):
            drifted.append(rel)
    if unbacked:
        return "a dependency had no content when it was verified: " + ", ".join(unbacked)
    if drifted:
        return "a dependency changed: " + ", ".join(drifted)
    return None


def skill_result(scenario_records):
    """The skill-level result implied by its per-scenario records.

    One scenario that was not actually run keeps the skill from claiming a pass.
    Runs mixed only with judged scenarios read as judged: a calibrated judge's
    confidence is a different kind of ground from a mechanical proof, so it gets
    its own step rather than being folded in with the rest.
    """
    results = {record.get("result") for record in scenario_records.values()}
    if results == {RESULT_PASS}:
        return RESULT_PASS
    if results and results <= {RESULT_PASS, RESULT_ACCEPTED_SEMANTIC}:
        return RESULT_ACCEPTED_SEMANTIC
    return RESULT_ACCEPTED_WITHOUT_RUN


def make_entry(root, surface, result, verified_date, note=None, scenarios=None,
               carried_note=None):
    """Build a lock entry.

    `structural_sha256` is what the next prose-only judgment compares against;
    an entry without it can only ever answer `contract-change`.

    `scenarios` holds the per-scenario {scenario_sha256, result, verified} the
    carry-over rule inducts from. `note` carries what a bare pass cannot tell the
    next reader — which route the run took, what it worked around — and never
    affects the verdict. `carried_note` keeps the previous entry's note for one
    generation so rebuilding an entry does not silently drop the provenance of
    the evidence.
    """
    entry = {
        "surface": surface,
        "file_sha256": file_hashes(root, surface),
        "structural_sha256": structural_hashes(root, surface),
        "surface_sha256": fingerprint(root, surface),
        "result": result,
        "verified": verified_date,
    }
    if scenarios:
        entry["scenarios"] = scenarios
    if note:
        entry["note"] = note
    if carried_note:
        entry["carried_note"] = carried_note
    return entry


def load(root):
    """Read the lock, or an empty one when the repository has none yet."""
    path = os.path.join(root, LOCK_REL)
    if not os.path.isfile(path):
        return {"version": 1, "skills": {}, "coverage_exempt": {}}
    try:
        with open(path, encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise LockError(f"{LOCK_REL}: cannot be read ({exc})") from exc
    state.setdefault("version", 1)
    state.setdefault("skills", {})
    state.setdefault("coverage_exempt", {})
    return state


def save(root, state):
    """Write the lock at the repository root."""
    path = os.path.join(root, LOCK_REL)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def check(root, state):
    """Judge the tree against the lock, as a list of (kind, skill, detail)."""
    issues = []
    entries = state.get("skills") or {}
    tracked = _skills_with_scenarios(root)
    for skill in sorted(tracked - set(entries)):
        issues.append(("unverified", skill, "has scenarios but no verification record"))
    for skill in sorted(set(entries) - tracked):
        issues.append(("orphan", skill, "recorded but declares no scenarios any more"))
    for skill in sorted(set(entries) & tracked):
        entry = entries[skill]
        surface = skill_surface(root, skill)
        severity, changed = stale_severity(
            entry.get("file_sha256") or {}, file_hashes(root, surface),
            entry.get("structural_sha256") or {}, structural_hashes(root, surface),
            own_prefix=f"skills/{skill}/")
        if severity is not None:
            issues.append(("stale", skill, f"[{severity}] " + ", ".join(changed)))
    return issues


def coverage(root, state):
    """How much is verified at all, as covered / exempt / uncovered.

    The check is opt-in and looks only at skills holding scenarios, so it cannot
    say how much is unverified. This can. Exemptions are declared in the lock
    with a reason rather than on the skill side, so that touching a skill
    directory cannot make it disappear from the count. "Not written yet" is not
    an exemption; that is uncovered.
    """
    exempt = state.get("coverage_exempt") or {}
    skills = _all_skills(root)
    covered = skills & _skills_with_scenarios(root)
    exempted = {name: exempt[name] for name in sorted(skills & set(exempt))
                if name not in covered}
    return {
        "covered": sorted(covered),
        "exempt": exempted,
        "uncovered": sorted(skills - covered - set(exempted)),
        "total": len(skills),
    }


def carried_note(prev_entry, note):
    """The note a rebuilt entry inherits. There is one slot, holding one generation.

    Every update that rebuilds an entry goes through this. If only some of them
    kept the note, a single routine acceptance would erase where the run evidence
    came from while the carried records stayed behind with no provenance.
    """
    prev_entry = prev_entry or {}
    carried = prev_entry.get("note") or prev_entry.get("carried_note")
    return None if carried == note else carried


def full_scenarios_record(root, skill, result, verified_date):
    """Record every current scenario with the same result and verification date."""
    return {
        scenario["id"]: {
            "scenario_sha256": scenario_sha256(scenario),
            "result": result,
            "verified": verified_date,
        }
        for scenario in load_scenarios(root, skill)
    }


def accepted_scenarios_record(root, skill, result, prev_entry, today):
    """Per-scenario records for an acceptance: the value changes, the dates do not.

    A per-scenario date says when that scenario was last confirmed by running it,
    which is how the freshness of a run is read. An acceptance that ran nothing
    stamping today would make an acceptance and a run indistinguishable from the
    record. A scenario with no previous record falls back to the entry's own date,
    and then to today, rather than inventing an older one.
    """
    previous = (prev_entry or {}).get("scenarios") or {}
    fallback = (prev_entry or {}).get("verified") or today
    return {
        scenario["id"]: {
            "scenario_sha256": scenario_sha256(scenario),
            "result": result,
            "verified": previous.get(scenario["id"], {}).get("verified") or fallback,
        }
        for scenario in load_scenarios(root, skill)
    }


def update(root, state, skill, today, note=None):
    """Record that every scenario of the skill was run and passed."""
    prev_entry = (state.get("skills") or {}).get(skill)
    surface = skill_surface(root, skill)
    records = full_scenarios_record(root, skill, RESULT_PASS, today)
    state.setdefault("skills", {})[skill] = make_entry(
        root, surface, RESULT_PASS, today, note=note, scenarios=records,
        carried_note=carried_note(prev_entry, note))
    return state["skills"][skill]


def update_accept(root, state, skill, today, note=None):
    """Record that the drift was judged not to need a run, and on what ground."""
    prev_entry = (state.get("skills") or {}).get(skill) or {}
    surface = skill_surface(root, skill)
    result = accept_result(
        prev_entry.get("file_sha256") or {}, file_hashes(root, surface),
        prev_entry.get("result"), prev_entry.get("structural_sha256") or {},
        structural_hashes(root, surface), own_prefix=f"skills/{skill}/")
    records = accepted_scenarios_record(root, skill, result, prev_entry, today)
    state.setdefault("skills", {})[skill] = make_entry(
        root, surface, result, today, note=note, scenarios=records,
        carried_note=carried_note(prev_entry, note))
    return state["skills"][skill]


def partial_update(root, state, skill, ran_ids, today, note=None):
    """Record the scenarios that ran and carry the rest, or refuse and change nothing.

    Returns the (scenario id, reason) pairs that could not be carried. A
    non-empty list means the lock was left untouched: recording the rest anyway
    would leave it claiming verification for a scenario whose dependency moved
    underneath it. Running nothing is legitimate — an edit that reaches no
    scenario advances the lock with no run at all.
    """
    prev_entry = (state.get("skills") or {}).get(skill) or {}
    scenarios = load_scenarios(root, skill)
    known = {s["id"] for s in scenarios}
    unknown = sorted(set(ran_ids) - known)
    if unknown:
        raise LockError(f"{skill}: no such scenario: {', '.join(unknown)}")

    surface = skill_surface(root, skill)
    recorded_hashes = prev_entry.get("file_sha256") or {}
    current_hashes = file_hashes(root, surface)
    recorded_scenarios = prev_entry.get("scenarios") or {}

    records = {}
    refused = []
    for scenario in scenarios:
        if scenario["id"] in set(ran_ids):
            records[scenario["id"]] = {
                "scenario_sha256": scenario_sha256(scenario),
                "result": RESULT_PASS,
                "verified": today,
            }
            continue
        reason = carryover_reason(skill, scenario, surface, recorded_hashes,
                                  current_hashes, recorded_scenarios)
        if reason is not None:
            refused.append((scenario["id"], reason))
            continue
        previous = recorded_scenarios[scenario["id"]]
        records[scenario["id"]] = {
            "scenario_sha256": scenario_sha256(scenario),
            "result": previous.get("result", RESULT_PASS),
            "verified": previous.get("verified", today),
        }
    if refused:
        return refused

    state.setdefault("skills", {})[skill] = make_entry(
        root, surface, skill_result(records), today, note=note, scenarios=records,
        carried_note=carried_note(prev_entry, note))
    return []


def _report_check(root, state, out):
    issues = check(root, state)
    for kind, skill, detail in issues:
        out(f"[{kind}] {skill}: {detail}")
    return issues


def _impact_scenarios(root, state, changed_paths, out):
    graph = dep_graph.build_graph(root)
    skills, unresolved = dep_graph.impacted_skills(graph, changed_paths, root)
    case_owners = {name for name in _skills_with_scenarios(root)
                   if any(p.startswith(f"{CASES_DIR}/{name}/") for p in changed_paths)}
    entries = state.get("skills") or {}
    for skill in sorted(set(skills) | case_owners):
        scenarios = load_scenarios(root, skill)
        if not scenarios:
            continue
        recorded = (entries.get(skill) or {}).get("scenarios")
        for scenario_id in impacted_scenarios(
                skill, skill_surface(root, skill), scenarios,
                [p for p in changed_paths], recorded):
            out(f"{skill}\t{scenario_id}")
    return unresolved


def main(argv):
    args = list(argv)

    def take(flag):
        if flag in args:
            args.remove(flag)
            return True
        return False

    def take_value(flag):
        if flag in args:
            index = args.index(flag)
            value = args[index + 1] if index + 1 < len(args) else None
            del args[index:index + 2]
            return value
        return None

    def take_all(flag):
        values = []
        while flag in args:
            value = take_value(flag)
            if value is not None:
                values.append(value)
        return values

    strict = take("--strict")
    accept = take("--accept")
    partial = take("--partial")
    note = take_value("--note")
    scenario_ids = take_all("--scenario")
    today = take_value("--today") or datetime.date.today().isoformat()

    mode = None
    for candidate in ("--check", "--coverage", "--update", "--impact-scenarios"):
        if candidate in args:
            mode = candidate
            args.remove(candidate)
            break
    if mode is None:
        print(__doc__, file=sys.stderr)
        return 2

    if mode == "--update":
        skill = args.pop(0) if args else None
        if skill is None:
            print("--update needs a skill name", file=sys.stderr)
            return 2
    changed = []
    if mode == "--impact-scenarios":
        # A trailing existing directory is the root; the rest are changed files.
        while len(args) > 1 or (args and not os.path.isdir(args[-1])):
            changed.append(args.pop(0))
    root = args[0] if args else os.getcwd()
    state = load(root)

    if mode == "--check":
        return 1 if _report_check(root, state, lambda line: print(line)) else 0
    if mode == "--coverage":
        report = coverage(root, state)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if strict and report["uncovered"] else 0
    if mode == "--impact-scenarios":
        unresolved = _impact_scenarios(root, state, changed, lambda line: print(line))
        for path in unresolved:
            print(f"warning: unresolvable path: {path}", file=sys.stderr)
        return 2 if unresolved else 0

    if accept:
        entry = update_accept(root, state, skill, today, note=note)
    elif partial:
        refused = partial_update(root, state, skill, scenario_ids, today, note=note)
        if refused:
            for scenario_id, reason in refused:
                print(f"cannot carry {scenario_id}: {reason}", file=sys.stderr)
            return 1
        entry = state["skills"][skill]
    else:
        entry = update(root, state, skill, today, note=note)
    save(root, state)
    print(f"{skill}: {entry['result']} ({entry['verified']})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except LockError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
