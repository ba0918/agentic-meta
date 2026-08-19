# Launching a blank-slate executor, and the verdict rules

The contract for the agent that runs one scenario. Everything the evaluation is worth
rests on that agent being a blank slate: it must meet the skill for the first time,
exactly as a real user's agent would.

## Principles

- **Dispatch fresh every time.** Reusing an agent means it has already learned the
  previous context. Reading the SKILL.md yourself and concluding "this looks fine" is
  refused for the same reason — it measures the reader, not the skill.
- **Run scenarios concurrently** by listing several launches in one message.
- **State the tier.** A scenario's `executor_tier` defaults to `standard`. Raise it to
  `high` only for a judgment-heavy skill where accuracy fell short, and record why in
  `notes`. `economy` is for a scenario whose critical expectations are all machine-judged,
  where a cheaper executor cannot degrade the verdict. Never name a concrete model in a
  scenario: the tier is the platform-independent expression of the same thing.
- **Isolate.** For `isolation: worktree`, materialise into a disposable git worktree and
  discard it afterwards. Inside that area the executor may edit and commit freely — that
  is what makes a scenario for a committing skill possible at all. What is forbidden is
  editing the repository proper. Where git worktrees are unavailable, a disposable
  directory substitutes; the declaration stays as written.
- **Corroborate zero edits** from the `baseline` hashes `--materialize` reports, not from
  what the executor says about itself.
- **Withhold the critical flags.** An executor that knows which expectations are critical
  optimises for them and papers over the rest. The same goes for machine-judged
  predicates. The executor reports on every expectation; the caller decides the verdict.
- **Do not route around a refused cleanup.** When discarding the isolated area is refused
  by a permission or a mount, record it in the report as inert debris and offer the
  human a command. Reaching for another tool to force it is out of bounds.

## The shape of the prompt

```
You are an executor reading the SKILL.md of the <skill> skill for the first time.

## Target skill
<absolute path to the SKILL.md; references may be followed from there>

## Working directory
<absolute path of the isolated area; the executor works only inside it>

## Situation
<the scenario's prompt, verbatim>

## Task
1. Follow the target skill's instructions to handle the situation and produce the artifact.
2. On completion, reply with nothing but the report structure below.

## Report structure
- Artifact: <what was produced, or the result>
- Execution path: <one line on which phases were delegated and which ran inline; "n/a" if single-step>
- Expectation table: yes / no / partial for each numbered item, with a one-line reason
  <the expectations, numbered. Never show the critical flags>
- Ambiguities: places in the skill where the reading was unclear ("none" if there are none)
- Discretionary fills: choices the instructions did not determine ("none" if there are none)
```

The execution path is reported because, on the same scenario with the same premises, the
path forks with how the executor perceives its environment, and only one branch finishes
without outside help. A bare pass in the lock hides that from whoever runs it next.

Workarounds for environment constraints may be injected as an "environment setup"
section, and that text must carry **no hint about how to solve the scenario** — say so
inside the injected text.

## Environment constraints worth building around

None of these are defects of a scenario or a skill; they are properties of an execution
platform, and a run made without knowing them reads as "the skill failed".

- **A background executor's ordinary output may never reach the caller.** State the
  concrete reporting path in the task section. The process-queue route removes this
  problem entirely: a file either exists or does not.
- **An executor usually cannot delegate further and get the completion back.** For a
  multi-stage skill this stalls at every phase boundary. The caller acts as the upper
  watchdog: inspect the artifacts directly, and send a status query carrying **facts
  only** — that the delegate has finished and no notification will arrive, never "read
  the result file". Recovering from a stall is part of what is being measured. Record
  how many queries it took, with `--note`.
- **Platform files leak into the isolated area** and dirty `git status`. For a scenario
  whose expectation is a clean tree, create the initial commit inside the isolated area
  during the run so the reference state is fixed.

## Verdicts

- A scenario passes when every `critical: true` expectation is **yes**. Partial counts
  as no.
- A skill passes when every scenario does. The lock advances only then.
- A no on a non-critical expectation does not change the verdict but always appears in
  the report — it is the early signal.
- **When the self-report and the artifact disagree, the artifact wins.** The caller
  re-judges. Only when the artifact genuinely cannot settle it does a dedicated judging
  agent get launched, handed the artifact and the expectations and nothing about how the
  run went.
- **When in doubt, no.** Lenient passes empty the lock of meaning.

## Report shape

```
## regression run — <skill>

| Scenario | Result | critical | non-critical | Failed |
|---|---|---|---|---|
| ac-001 <title> | pass | 3/3 | 1/1 | - |
| ac-002 <title> | fail | 2/3 | 1/1 | E2: <expectation> — <what showed it failed> |

- What the executor had to interpret for itself: <only what is new since the last run>
- Cost: <what the batch actually spent, against what the dry-run estimated>
- Lock: <advanced / not advanced, and why>
- Affected skills with no scenarios: <names, as capture candidates>
```

On a failure, attach the separation of "a regression in the skill" from "a scenario that
has gone obsolete", with the grounds — which edit caused it.
