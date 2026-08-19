# Requirement reachability — the verification procedure before locking

**Before** hash-locking the requirement checklist, verify that each requirement is reachable in that scenario.
When an unreachable requirement slips in, **an executor that behaved exactly as instructed loses points**.
What you are measuring then is not the quality of the instruction but a defect in the scenario design.

Skipping this verification led to **stepping into the same trap 4 times**: dw-001 (doc-write) → dj-003 (decision-journal)
→ gi-003 / gi-004 (github-issue) → pi-001-003 (plan-implement). In gi-004 the verdict fell to HOLD, and a whole batch was
discarded and re-run.

## The 3 axes

A requirement is reachable when it satisfies **all** three of the following.

| Axis | The question | What happens if you drop it |
|---|---|---|
| **Process reachability** | Is the step where the requirement can be observed before the scenario's stopping point? | You grade steps after a stop for confirmation, and every run fails |
| **Environment reachability** | Does that step get reached **in this environment**? Is there a condition that stops it earlier? | An environmental factor stops it first, and the requirement is demoted to a future-tense note |
| **Contract consistency** | Does the behavior satisfying the requirement contradict another clause of the instruction? | The requirement becomes one that correct behavior always violates, and the deviant arm scores higher |

Looking only at process reachability is **nothing more than matching against the procedure table**. The procedure table
answers only "what can be observed at step N", never "is step N reached in this environment". **The missing second axis is the cause of the 4 recurrences.**

## Procedure: enumerate the "stopping conditions" before the requirement table

Before writing the requirement table, lay out every condition that could halt the workflow in this environment.
A requirement's reachability is determined by where it falls relative to that list of stopping points.

| # | Stopping condition | Does it hold in this environment | Steps affected |
|---|---|---|---|
| S1 | A required tool is missing | | |
| S2 | Authentication or credentials are missing | | |
| S3 | The target file or repository does not exist | | |
| S4 | An external API or rate limit cannot be reached | | |
| S5 | It stops waiting for user confirmation | | |

A typical case (measured): gi-003 tried to measure the issue-number validation of Cycle Pre-check 3, but
**S2 (gh unauthenticated) stopped it earlier at Common Pre-checks 2**. The executor stopped correctly in both the Japanese
and English arms, and 007's rejection became the future-tense note "even after authenticating, cycle cannot start as is",
identical in sentence form in both arms and therefore partial.

**How to release it**: put an environment exception clause on the prompt side.
"In this environment <the dependency> is unavailable, but <the judgment you want to measure> should not depend on it —
record the failure and still return that judgment". gi-001 had this clause and did reach the step in the same environment.

### Crush a stopping condition all the way down to "what is being asked for"

"Waiting on a user answer can be avoided by giving the answer in the prompt up front" **does not always hold**.
The outcome depends on whether what that step asks for is "a declaration of direction" or **"a choice among generated candidates"**.

Measured (dg-002 / design-guide): trying to measure Phase 6 (artifact generation) of the interactive discovery, the prompt
gave the visual mood direction (cool, muted, blue-green) up front.
But what Phase 3 asks for is **a choice among 3 palette candidates generated on the spot**, and a choice among candidates
that do not exist yet cannot be pre-empted by a declaration. The executor stopped correctly at Phase 3 in both arms and
never reached Phase 6. **All 5 requirements were wiped out.**

To claim a stopping condition has been crushed, confirm this much:

```
What does that step ask of the user?
  "declaring a fact or a policy"      → it can be crushed by giving it in the prompt up front
  "choosing among presented candidates" → it cannot. The candidates are generated at runtime and cannot be pre-empted
  "approving a produced artifact"      → it cannot
```

When a step of the latter two kinds lies before the stopping point, **everything past it cannot be measured in a single turn**.
The body of most interactive skills (present candidates → choose → generate) falls into this category.

### A permitted path is not the path that gets chosen

Never treat the fact that the instruction **permits** "in this situation you may substitute this way" as grounds for reaching
that step. A permission only widens the options; it does not guarantee that the executor picks that option.

Measured (pi-001-003 / plan-implement): the top of the body had an explicit clause allowing inline execution when
"subagents cannot be launched / another skill cannot point at the target project correctly", and the isolated area fell under
the latter. The verification table cited that clause to say "this does not count as a nested-delegation stall", but
**2 of 3 chose delegation**, the child's completion notification never reached the parent, and it stalled short of the
following step. The remaining 1 chose inline not because of the clause but because of a separate constraint on the platform side.

When an environment exception clause was put into the prompt **instructing** "do not delegate; substitute inline",
2 of 2 ran to completion under the same setup. The difference is not whether the body permits it, but whether it was instructed.

**How to write the verification**: "the body permits it, so it is reached" is not grounds.
Write it down to "which path is certain to be chosen in this environment". If no path is guaranteed, specify the path on the
prompt side. When you do, separately confirm that the specified path is within what the body permits, and that it does not
pre-empt the judgment you want to measure.

## How to look at contract consistency

Confirm that the behavior satisfying the requirement does not violate another clause of the instruction.

A measured example: gi-004's requirement "has not **executed the gh command**" contradicted the Common Pre-checks, which
mandate running `gh --version` / `gh auth status` / `gh repo view` at the top of every workflow.
An executor that ran the pre-checks got partial; one that did not got pass.
What was being measured was not the language difference but the accident of "whether the pre-checks were run".

**How to write it**: a requirement measuring zero side effects must **enumerate write operations only**.
Not "has not executed gh" but "has not executed issue edit / adding or removing a label / pr create / pr merge / issue close".
Reads and status checks may be mandated by the instruction itself.

## What to do when you find a defect

**Do not loosen the requirement. Reset the baseline, re-lock, and re-run both arms.**
The hash lock exists precisely for this (SKILL.md, "Hash-locking the checklist").

Never confuse "loosening" with "making it measurable".

| | Content | Allowed |
|---|---|---|
| Loosening | Looking at the results and lowering the strength of a failed requirement | **Forbidden** |
| Making it measurable | Removing only the claim that is impossible to observe in principle in this environment, keeping the substance | Allowed (treated as a reset) |

When you choose to make it measurable, always satisfy the following:

- Keep the substance (what must be decidable for it to count as correct). In gi-003 only the process-order claim "fails and
  exits immediately" was removed, while the substance of the rejection, the error term, and the ban on reinterpretation were kept
- State the old lock's `checklist_sha256` in `supersedes`
- **Re-run both arms from the start.** Carry over not a single score from the old run
- Leave in the verification table why it was unobservable. There is nowhere else to record what keeps the next person out of the same trap

**Excluding a scenario after the fact is selection bias**, so never drop an inconvenient scenario before judging.

### An error in the verdict rule is not "loosening"

Sometimes it is not the requirement but **the verdict rule that is broken**. Fixing that does not count as loosening.
The criterion is **whether the grounds for the fix are independent of the candidate**.

Measured (dg-001 / design-guide): the non-degradation A/B gate was written as the **absolute predicate**
"the critical requirement passes in the candidate arm".
But the baseline itself was dropping that critical, so the gate could not hold whatever the candidate was —
it had become **a device returning constant false**. That discriminates nothing between candidates.

The grounds for the fix, "the baseline drops the critical", is **a fact visible from the baseline arm alone** and can be
derived without referring to the candidate arm's results. It therefore introduces no bias into the candidate comparison.
Conversely, a fix that can only be justified after looking at the candidate's score is loosening, even when it is a change to the verdict rule.

Write the non-degradation A/B gate in **differential form** from the start:

```
NG: the critical requirement passes in the candidate arm
OK: the candidate does not drop a critical that the baseline was passing
```

## Axes unsuited to being gate conditions

**Compliance with a request-based constraint** must never be used as a gate condition.

When the constraint is a request rather than "a mechanical gate that neither configuration nor instruction can remove",
whether it is upheld depends on the executor's characteristics and wobbles run to run. This is **language-invariant**, and
letting it decide whether to adopt a rephrasing, translation, or compression of the body means judging on a property you are not measuring.

Measured (dg-001): the constraint "no file creation during Phases 1-5" came off under the user's
"skip the questions and just write it". And it came off **in exactly the same shape in both arms**, with both dropping the
same 3 criticals. It has nothing to do with translation quality.

Split the handling by purpose:

| Purpose | Handling |
|---|---|
| Finding defects in the instruction | **Valid.** Highly valuable as a detector of rationalization hooks |
| Deciding whether to adopt a body revision | **Not allowed.** Put it on a differential-form gate, and never make the candidate responsible for what the baseline drops |
| A regression asset (fixture) | Valid. But if it is RED now, that makes it "something to fix", not a reason to delete the fixture |

## The gate

Right before locking, for each requirement:

```
1. Where is the step at which this requirement can be observed → is it before the stopping point?
2. In this environment, is there a condition that stops before that step → check S1-S5 one by one
3. Does the behavior satisfying this requirement violate another clause of the instruction?

Any of 1-3 is No → do not lock. Fix the scenario or the prompt
If you fixed the prompt, include that prompt in the hash target as well
```

Hashing only `requirements` means the fingerprint does not move even when the prompt is silently rewritten.
If the design releases reachability on the prompt side, **include both the prompt and the requirements in the lock.**
