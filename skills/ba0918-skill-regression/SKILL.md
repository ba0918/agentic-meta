---
name: ba0918-skill-regression
description: A regression harness for skills. It turns the pass criteria a skill was tuned against into scenario files kept beside the repository, and when a SKILL.md or a shared contract changes it re-runs only the scenarios that change actually reaches. A lock records what was verified against which content, so editing one shared contract can no longer silently change the behaviour of every skill citing it. Every run is sized before it starts and stops after the first scenario it has no measurement for. Use when the user says "skill-regression", "regression evaluation", "turn this into a scenario", "check what this contract change affects", "which skills went stale", or asks whether a skill still behaves as it did. Sister skill of `ba0918-trigger-eval`, which measures whether a skill fires at all; this one measures whether it executes correctly once it has.
license: MIT
metadata:
  contracts:
    - fixture-contract
---

# ba0918-skill-regression

A skill is a program written in prose, so every edit to a SKILL.md, a reference, or a
shared contract is a change of behaviour. The acceptance criteria a skill was tuned
against normally vanish with the session that produced them, and when the next edit
breaks the tuned behaviour nobody notices. This harness keeps those criteria as
scenario files, re-runs only the scenarios a change reaches, and records the result in
a lock.

- What `ba0918-trigger-eval` protects is whether a skill fires. What this protects is
  whether it executes correctly once it has.
- Where a scenario came from does not matter — a measurement from empirical tuning, the
  acceptance criteria of a plan, or one written by hand are all the same here. This is
  the consuming side and depends on no particular producer.

## Terminology

| Term | Meaning |
|---|---|
| behaviour surface | The files that can affect a skill's run-time behaviour: everything under `skills/<name>/` plus what its own markdown reaches in one hop, shared contracts included. Computed by `dep_graph.py`, which also states why the hop is not followed further |
| scenario | One file under `evals/cases/<skill>/`: a situation to hand the skill, plus the expectations its result must satisfy. Schema: [references/fixture-schema.md](references/fixture-schema.md) |
| expectation | One checkable statement about the result. An expectation marked `critical: true` is one whose failure collapses the skill's reason to exist |
| lock | `regression-lock.json` at the repository root: what was verified, against which content. It is committed |

## Layout

Nothing is written inside the skill under test. The three kinds of asset have three
homes, and the placement is what keeps a measurement from polluting its own target:

```
evals/cases/<skill>/<scenario>.yaml   scenarios — committed, not distributed
evals/inputs/<skill>/                 the files a scenario stages — committed
regression-lock.json                  the verification record — committed, at the root
<the executing environment's own area>  cost history, judge calibration — never committed
```

## Execution contract

- Call the scripts by absolute path: `python3 {skill_dir}/scripts/<name>.py`, where
  `{skill_dir}` is the directory holding this SKILL.md.
- Only skills that have scenarios are tracked, so coverage is opt-in and a skill with
  none is outside the check rather than silently passing it.
- **Being stale asks for a recorded judgment, not a rerun.** Rerunning is expensive and
  whoever demands it does not pay for it. What the lock refuses is leaving drift
  unaddressed; resolving it by an acceptance that says why no run was needed is a
  first-class answer, not an evasion.
- Advance the lock only on evidence that the scenarios passed. Never on "it should have
  passed".
- Which acceptance value gets recorded is decided by the machine, not by the operator:
  the lighter names are reachable only on top of a real run whose difference could be
  mechanically confirmed as addition-only or prose-only.

## Choosing a workflow

| Input | Workflow |
|---|---|
| "turn this into a scenario" / "make this an asset" | capture |
| "run the regression evaluation" / "what does this change affect" | run |
| "show me the status" / "which ones went stale" / "what is the coverage" | status |

## capture — turning acceptance criteria into assets

1. **Find the material.** In order of preference: the converged output of an empirical
   tuning session, the acceptance criteria of the corresponding plan, or — failing both
   — criteria designed from scratch following the guidelines in
   [references/fixture-schema.md](references/fixture-schema.md).
2. **Write the scenarios.** Two or three per skill: one at the median of real usage plus
   one or two edges. Three to seven expectations each, at least one of them critical.
   Files the scenario stages go under `evals/inputs/<skill>/` as real files.
3. **Check them.** `python3 {skill_dir}/scripts/fixture_setup.py --validate evals/cases/<skill>/*.yaml`
4. **Run them once.** Steps 2 to 4 of the run workflow below. A scenario that fails is
   not turned into an asset: every later evaluation would be red and the lock would
   stop meaning anything.
5. **Record.** `python3 {skill_dir}/scripts/lock.py --update <skill> .`

## run — regression evaluation

1. **Choose what to run.**
   - Given a skill name, take its scenarios. Otherwise work back from the changed
     files: `python3 {skill_dir}/scripts/lock.py --impact-scenarios <changed>... .`
     prints `skill<TAB>scenario` for the scenarios a change actually reaches, using the
     `exercises` declarations. A scenario without one always stays on the list.
     Rules and fallbacks: [references/partial-rerun.md](references/partial-rerun.md)
   - Affected skills that have no scenarios are out of scope; list them in the report.
   - **Run or accept.** A change confined to prose — punctuation, phrasing, nothing that
     any machine reads — is acceptance territory. A change that touches a parsed token, a
     command, or a frontmatter key is a run. Neither answer needs anyone's permission,
     and the cost of a run falls on whoever runs it.
   - A `contract-change` may go through semantic triage first, which reads the diff
     against each scenario's expectations and answers unaffected / unclear / affected.
     Only `unaffected` reaches the record, and only from a judge that has passed
     calibration in this run: [references/semantic-triage.md](references/semantic-triage.md)
2. **Size it, then execute.** Before running anything:
   `python3 {skill_dir}/scripts/cost.py dry-run --skill <skill> --route <route> --inputs evals/inputs/<skill>`
   reports the selected scenarios, an approximation from their input size, and the
   measured cost of any that have run before. A batch holding a scenario with no
   measurement runs one and reports what it cost before going on.
   [references/cost-model.md](references/cost-model.md)
   - Materialise each scenario from its declaration, never by hand:
     `python3 {skill_dir}/scripts/fixture_setup.py --materialize <scenario> <inputs> <dest>`.
     Premises like file times and git state would otherwise be filled in differently on
     every run.
   - Launch a blank-slate executor per scenario under
     [references/executor-contract.md](references/executor-contract.md), using the
     `baseline` hashes to corroborate that nothing was edited and passing `env` through.
   - When launch quota is short, the batch is large, or the run should be unattended,
     delegate to separate processes instead:
     [references/process-queue.md](references/process-queue.md)
3. **Judge** each scenario by the rules in the executor contract. A skill passes when
   every critical expectation holds in every scenario.
4. **Report** per scenario: pass or fail, which critical items failed, and what the
   executor said it had to interpret for itself.
5. **Record.** For a skill that passed everything, `--update <skill>`. After a
   scenario-granular run use `--update <skill> --partial --scenario <id>...`, which
   records what ran and carries the rest, refusing the whole update — and naming them —
   if any cannot be carried. Running nothing is legitimate. Add `--note "<one line>"`
   for what a bare pass cannot tell the next reader: which route the run took, what it
   worked around. For a failure, do not advance the lock; separate a regression in the
   skill from a scenario that has gone obsolete, and say which. Fixing a scenario in the
   direction of making it easier is forbidden — that hides the regression instead.

## status — taking stock

- `python3 {skill_dir}/scripts/lock.py --check .` reports unverified, stale and orphan
  entries and exits non-zero if there are any. Each stale line carries a severity:
  `contract-addition` when the machine could confirm the surface only gained files from
  inside the skill's own directory, `prose-change` when every modification to an
  existing markdown file was prose alone, and `contract-change` otherwise. Read it as
  triage, not as permission — the lighter two still have to be resolved, only with an
  acceptance as a defensible answer.
- `python3 {skill_dir}/scripts/lock.py --coverage .` answers the other question: not
  whether the verified assets went stale, but how much is verified at all. Exemptions
  are declared in the lock with a reason, never on the skill side, so that touching a
  skill directory cannot make it disappear from the count. "Not written yet" is not an
  exemption; that is uncovered.

## Wiring it into CI

`lock.py --check` is what a gate would run: when the behaviour surface of a skill
holding scenarios has moved since it was verified, it fails and asks for either a
re-evaluation or a recorded acceptance. Whether to wire it in at all is the operator's
choice — this skill provides the mechanism and takes no position on enforcing it. The
point of such a gate is never to stop drift, only to make ignoring it impossible.

## Red flags

- Every entry in the lock is `accepted-without-run`, and stays that way. Runs have
  become a formality.
- The same skill's scenarios are rewritten repeatedly as "obsolete" in a short span.
- A run report does not say which critical items failed.
- A batch is started without a dry-run, or a scenario with no measurement is run inside
  a batch rather than alone.

## Scope

Computing a behaviour surface and reproducing a scenario cover what lies under
`skills/`, and only scenarios reproducible in the current execution environment.
Reproducing behaviour on another runtime is a deliberate non-goal: an executor launched
here cannot be called a reproduction of behaviour there, and calling it one would forge
the verification. Should it become necessary, design a runtime variant of the executor
contract first, and widen the surface computation only after — the means of execution
before the range of detection, never the reverse.

## Related

- [references/fixture-schema.md](references/fixture-schema.md) — the scenario schema and how to design one
- [references/executor-contract.md](references/executor-contract.md) — launching a blank-slate executor, and the verdict rules
- [references/cost-model.md](references/cost-model.md) — sizing a batch, the first-scenario stop, and the ceiling
- [references/partial-rerun.md](references/partial-rerun.md) — `exercises`, scenario-granular impact, and carry-over
- [references/semantic-triage.md](references/semantic-triage.md) — judging a diff's impact, calibrating the judge, and its permission boundary
- [references/process-queue.md](references/process-queue.md) — running a batch through separate processes
