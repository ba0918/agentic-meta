# Checker Subagent Protocol

The launch contract for requirement grading by an independent checker subagent.
The heart of the 3-role separation (tuner / executor / checker).

## Why separate them

When the executor grades itself, the vaguer the instruction, the more leniently it interprets it and marks ○.
This structurally removes the self-contradiction of the very thing being measured (ambiguity) becoming the grader's source of bias.

## What is handed to the checker

1. **The executor's artifact** (code / output / the text of what was produced)
2. **The requirement checklist** (with the `[critical]` tags)
3. **The fixture's input range declaration** (for an integration fixture, the set of artifacts handed over as the artifact)

## What is not handed to the checker

- **The target prompt body** — prevents "charitable interpretation" of the prompt
- **The executor's friction report** — prevents the executor's excuses from seeping into the grading
- **The previous iteration's results** — guarantees an independent judgment
- **The repository proper / the whole source tree** — reading the implementation instead of the artifact inverts what is being graded (`isolation_violation`)

## The input range declaration of an integration fixture

In an "integration fixture" spanning a handoff between skills or several artifacts, the fixture itself must state
"the set of artifacts without which the checker cannot evaluate".
A fixture that does not state it breaks reproducibility even when it happens to work (the failure mode of the original issue #4).

Include the following fields in every integration fixture:

```json
{
  "fixture_kind": "integration",
  "input_range": {
    "consumer": "<the consumer artifact path or embedded content>",
    "reference": "<the reference artifact path or embedded content>"
  },
  "input_range_required": ["consumer", "reference"]
}
```

- **Every** key listed in `input_range_required` must be included in the input to the checker
- Evaluating with only some of them handed over must be a harness error of `input_range_violation`
  (never confuse it with a candidate failure)
- For a fixture evaluable from a single artifact, use `fixture_kind: "unit"` and
  `input_range_required` may be omitted

### Implementation guide

- The harness calls `validate_input_range()` immediately before dispatching the checker.
  If `ok` is false, abort the dispatch, put the returned failure type into `harness_error.type`,
  and record that iteration.
  Obtain the missing keys for `detail` with `sorted(set(input_range_required) - set(dispatch_keys))`
  (stringifying the set directly makes the order vary per run and breaks the record's reproducibility)
- Passing extra keys is not a violation (only omissions break reproducibility).
  A unit fixture whose `input_range_required` is empty or undeclared always passes
- Validate the checker's reply with `validate_checker_output(raw, checklist, fixture_kind=fixture["fixture_kind"])`.
  Only when `fixture_kind="integration"` is `isolation_note` mandatory
- State in the checker-side template: "base your judgment **only** on the artifacts below. Never open a source that is not here" (the isolation declaration)

```python
ok, failure = validate_input_range(set(artifacts), fixture.get("input_range_required"))
if not ok:
    record_harness_error(failure, detail=str(set(fixture["input_range_required"]) - set(artifacts)))
else:
    raw = dispatch_checker(artifacts, checklist)
    ok, failure = validate_checker_output(raw, checklist, fixture_kind=fixture["fixture_kind"])
```

## Separating protocol failure from candidate failure

The checker's reply must always distinguish "a failure of the candidate prompt" from "a deviation on the checker/harness side".
Confusing them lets a checker bug lower the candidate's precision and contaminates the iteration's
learning signal (the main cause of the original issue #4).

| Channel | Meaning | Where it is recorded |
|---------|------|-----------------|
| candidate failure | a requirement was not satisfied (`result: fail`) | `scenarios[].checker_grades` |
| protocol failure | a deviation on the checker/harness side (see the table below) | `scenarios[].harness_error` |

### Protocol failure classification (`PROTOCOL_FAILURE_TYPES`)

| type | Trigger |
|------|---------|
| `malformed_output` | the checker output cannot be parsed as JSON / does not match the expected schema |
| `missing_grade` | not every requirement in the checklist was graded |
| `extra_grade` | a grade is present for a requirement index that does not exist |
| `duplicate_grade` | the same requirement index was graded more than once |
| `invalid_result_value` | `result` is something other than `pass` / `fail` / `partial` |
| `empty_checklist` | the caller handed over an empty checklist (an indicator of a bad fixture load) |
| `missing_evidence` | a grade has no non-empty `evidence` (the grading is not tied to any grounds) |
| `missing_isolation_note` | it is an integration fixture, yet the output has no `isolation_note` key |
| `isolation_violation` | `isolation_note` holds a non-empty string, self-reporting that a source outside the artifact was read |
| `input_range_violation` | dispatched with inputs missing against an integration fixture's `input_range_required` |

All 10 classifications are emitted by the pure functions in `scripts/convergence.py`. There is no need to
write your own detection in the harness.

| When it is detected | Function | Return value |
|---------------|------|-------|
| just before dispatch | `validate_input_range(dispatch_keys, input_range_required)` | `(ok, failure_type)` |
| after the checker replies | `validate_checker_output(raw, checklist, fixture_kind=...)` | `(ok, failure_type)` |
| after recording the iteration | `has_protocol_failure(iteration_record)` | `bool` |

The inspection order of `validate_checker_output()` is "structure → integration isolation → grade shape →
coverage → evidence". Output with broken structure returns the structural failure type rather than the evidence
symptom, steering the implementer to the place that should be fixed first.

### Safe-stop (halting safely when evaluation is impossible)

`resolve_exit_verdict()` returns `halt` when the latest iteration has a protocol failure.
`resolve_halt_reason()` returns `checker_protocol_failure`, which is recorded in
`iteration.halt_reason`.

- An iteration with a protocol failure is **excluded from the precision aggregate** (it is not a candidate failure)
- It also contributes to neither the convergence verdict (`is_converged`) nor the divergence verdict (`is_diverged`)
- Resumption procedure:
  1. Fix the harness / fixture / checker template according to the harness_error type
  2. Discard that iteration while keeping the baseline checklist's sha256
  3. Dispatch the next iteration with a new subagent

> **NG**: lowering precision by treating a protocol failure as "a fail because the checker said so" surfaces as a
> phantom regression that no prompt fix improves, and the iteration loop spins in place. Always separate it
> as a harness error.

## The instruction template for the checker

```
You are an independent grader. Judge whether the artifact satisfies the requirement checklist.

## Artifact
<paste the executor's artifact here>

## The input range of the integration fixture (when applicable)
Base your judgment **only** on the artifacts below. If you open a source not listed here
(a repository file, the internet, another iteration's artifact),
self-report that in the "isolation_note" field.
- consumer: <...>
- reference: <...>

Always include `isolation_note` in the output. Put `null` when there is no violation.
Put a string only when self-reporting a violation (never write impressions or supplementary notes).

## Requirement checklist
0. [critical] <requirement text>
1. <requirement text>
...

## Task
Judge each requirement and reply in JSON:
- requirement_index: a 0-origin integer
- result: "pass" | "fail" | "partial"
- evidence: which part of the artifact is the grounds (1 line)

## Output format (strict. A deviation is treated as a harness error)
{
  "grades": [
    { "requirement_index": 0, "result": "pass", "evidence": "..." },
    { "requirement_index": 1, "result": "fail", "evidence": "..." }
  ],
  "isolation_note": null
}

- grades must cover every requirement of the checklist, no more and no less
- put a non-empty string in `evidence` for every grade (an empty string or omission is a harness error)
- do not add extra top-level keys (a value for `--output`, comments, and so on)
- even when unsure, never return a result outside the 3 values above
```

## Computing precision (on the tuner side)

The tuner receives the checker's grades and computes:
- `pass` = 1.0, `partial` = 0.5, `fail` = 0.0
- precision = the total / the number of requirements
- success verdict: success when **every** requirement tagged `[critical]` passes

## The 2-channel fusion rule

The tuner cross-checks the checker's grading against the executor's friction report to decide the next iteration's fix:

| The checker's result | The executor's friction report | The tuner's action |
|---------------|----------------|----------------|
| some fails | related friction present | use the friction as the clue and fix the prompt |
| some fails | no related friction | the executor erred without noticing = the instruction carries an implicit premise. State the premise |
| pass | friction present | the instruction is correct in the end but hard to read. Improve the clarity |
| pass | no friction | no improvement needed (a convergence signal) |
