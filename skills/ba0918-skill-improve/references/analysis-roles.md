# Analysis roles

Four roles read the same measurement from four angles, and a fifth composes their
answers into the friction report.

## Why four roles, and what that does not mean

The separation buys **parallelism and cost**. Four narrow readings of one JSON file run
at the same time, each cheap, each answering a question the others do not ask. That is
the whole of it.

It is **not** a bias isolation, and reading it as one will make this skill look far more
demanding than it is. The sister skill `ba0918-empirical-prompt-tuning` separates its
tuner, executor and checker because an executor that has seen the pass criteria stops
being a measurement of the instructions — there the separation is the instrument, and
substituting a self-reread invalidates the result. Here every role reads the same
already-finished measurement, and nothing any of them sees can change what was
measured. Merging two of these roles costs breadth and clarity, not validity.

The practical consequence: a run that cannot get four independent contexts is degraded,
not invalid. See below.

## Supplying the executors

**Supplying a way to start an independent model invocation is the invoking session's
responsibility.** This skill states what each role is given, what it must return, and
what it may not do. It does not carry a runner and takes no position on how one is
started.

Where independent contexts cannot be supplied — no subagent mechanism, a launch quota
already spent, an environment with no such facility at all — **degrade to sequential
in-context analysis**: work the four role prompts one after another in the current
context, in the order below, writing each answer out before starting the next.

**A degraded run says so in the report.** Put it in the header (`Analysis mode:
sequential in-context`) and in the coverage-limits section. Degrading silently is the
one forbidden outcome here — a reader comparing two reports must be able to see that
one had four fresh readings and the other had one context reading four times, which is
a weaker guard against a single early misreading colouring everything after it.

A lightweight model is enough for every role. The work is reading counts and
classifying them.

## Common rules

- **Every role is read-only.** No role edits a file under the skills being analysed.
- **Each role writes its answer as JSON** to the run's scratch directory,
  `.agents/tmp/skill-improve-{datetime}/{role}.json` — outside the tree being measured,
  as the run-output clause of [vendor/fixture-contract.md](vendor/fixture-contract.md)
  requires.
- **No original text ever appears in an answer.** Not an utterance, not a response, not
  a session identifier. Figures, classifications and scores only. The measurement
  handed to the roles already contains no bodies; the rule exists so that a role which
  is additionally shown a SKILL.md does not start quoting from what it inferred.
- **Every role is given the detection coverage, not only the counts.** `summary.stores`
  says which routes each store could be read along and whether abandonment was recorded
  or inferred. A finding drawn from an incomplete route is qualified, never presented
  whole. See [session-stores.md](session-stores.md) and the confidence section of
  [scoring-guide.md](scoring-guide.md).
- **Every role also answers the pressure question** for the skill it is looking at:
  could this skill's constraints be rationalised away under pressure? Pressure kinds to
  consider: time, sunk cost, authority, economics, fatigue, social, pragmatic. For each
  constraint, judge how likely an operator or an agent is to talk itself past that
  constraint under each kind, and recommend hardening the guard where the risk is high.
  A constraint nobody can be bothered to keep is a constraint that is not there.

## The context each role is given

1. The measurement (`context.json`), whole.
2. For the roles that need it, the `SKILL.md` of the skill under analysis.
3. Its own role prompt, from below.

## 1. friction-detector

**Purpose:** extract the retry and correction patterns, and produce each skill's score.

```
You are friction-detector. Read the measurement and detect retry and correction
patterns.

## Input
{contents of context.json}

## Analysis instructions
1. Identify the skills with a high retry_count, and classify what kind of cause the
   runs of consecutive firings point to.
2. Identify the skills with a high correction_turns, and infer what those correction
   utterances are reacting to.
3. Compute each skill's friction score by the formula in scoring-guide.md. Do not
   invent a formula of your own, and do not adjust the weights.
4. Assign a confidence by the same guide, applying both downgrades that hold: sample
   size, and `confidence_downgraded` / `stores_without_structural`. Name each one you
   applied. `stores_with_inferred_abandonment` and
   `summary.stores[*].superset_utterance_sessions` are qualifications rather than
   downgrades: name them against the term each one weakens and leave the confidence
   where the downgrades left it.
5. Answer the pressure question for each skill you score.

## Output
Write the result to {output_path} as the following JSON:
{
  "role": "friction-detector",
  "findings": [
    {
      "skill": "string",
      "friction_score": "number (0-10)",
      "confidence": "string (High | Medium | Low)",
      "confidence_notes": ["string — each downgrade and qualification applied, and why"],
      "retry_pattern": "string (classification)",
      "correction_pattern": "string (classification)",
      "pressure_risk": "string (the constraint most likely to be rationalised away, or none)",
      "recommendation": "string"
    }
  ]
}
```

The score formula lives in [scoring-guide.md](scoring-guide.md) and nowhere else. The
collector this was ported from carried a second, different formula inline in this
prompt, which meant the same measurement produced two scores depending on which
document a reader happened to follow. One home, and this prompt points at it.

## 2. pattern-analyzer

**Purpose:** frequency analysis — repeated firings and repeated identical errors.

```
You are pattern-analyzer. Read the measurement and detect repetition patterns and
abnormal frequencies.

## Input
{contents of context.json}

## Analysis instructions
1. Detect the same skill being fired several times inside the retry window — three
   turns of its own previous firing, which is what `retry_count` counts.
2. Identify the sessions with a high `tool_errors` on the `sessions` rows, and classify
   how the errors repeat. A session's error count is attributed whole to every skill
   fired in it, so a shared high count points at the session rather than at any one
   skill.
3. Analyse the transitions between skills — which tends to be fired after which, and
   where a chain looks anomalous.
4. Note where a pattern rests on a store whose structural route is unavailable: there
   the sequence of firings is only what the operator typed.

## Output
Write the result to {output_path} as the following JSON:
{
  "role": "pattern-analyzer",
  "findings": [
    {
      "pattern_type": "string (multi_invoke | error_loop | chain_anomaly)",
      "skill": "string",
      "frequency": "number",
      "description": "string — quantitative only",
      "coverage_caveat": "string | null — the route or inference this rests on",
      "recommendation": "string"
    }
  ]
}
```

## 3. expectation-auditor

**Purpose:** the gap between what a skill's definition expects and how it is used.

```
You are expectation-auditor. Compare the skill definition against the actual usage and
detect the gaps.

## Input
{contents of context.json}

## Additional context
{contents of the SKILL.md under analysis}

## Analysis instructions
1. Compare the workflow the SKILL.md defines against the firing patterns observed.
2. Identify workflows that are defined and never reached.
3. Detect usage the definition did not anticipate.
4. For a skill with a high correction_turns, infer where the expectation gap sits.
5. Answer the pressure question: which of this skill's constraints would be
   rationalised away first, and under which pressure.

## Output
Write the result to {output_path} as the following JSON:
{
  "role": "expectation-auditor",
  "findings": [
    {
      "skill": "string",
      "gap_type": "string (unused_workflow | unexpected_usage | expectation_mismatch)",
      "expected": "string",
      "actual": "string — quantitative only",
      "pressure_risk": "string | null",
      "recommendation": "string"
    }
  ]
}
```

## 4. drift-detector

**Purpose:** divergence from the use the skill was designed for.

```
You are drift-detector. Compare the skill's design intent against how it is actually
being used, and detect the drift.

## Input
{contents of context.json}

## Additional context
{contents of the SKILL.md under analysis}
{the project's own agent instructions, where the run has them}

## Analysis instructions
1. Compare each skill's description — its design intent — against the context it is
   actually fired in.
2. Detect skills fired far more or far less often than the design implies, and judge
   the drift.
3. Check that the dependencies between skills, seen as chained firings, match the
   design.
4. Detect uses that were not anticipated at design time.
5. Before calling a skill underused, check whether it was seen only through a store
   with no structural route. A skill the agent fires on its own is invisible there, and
   "underused" is exactly the wrong conclusion to draw from a blind route.

## Output
Write the result to {output_path} as the following JSON:
{
  "role": "drift-detector",
  "findings": [
    {
      "skill": "string",
      "drift_type": "string (underused | overused | misused | evolved)",
      "design_intent": "string",
      "actual_usage": "string — quantitative only",
      "drift_score": "number (0-10, 10 = fully diverged)",
      "coverage_caveat": "string | null",
      "recommendation": "string"
    }
  ]
}
```

## 5. The integrating role

Reads the four answers and writes the friction report. The report's schema is in
[friction-schema.md](friction-schema.md); this role composes, it does not re-judge.

```
Read the four JSON answers in the run's scratch directory and write the friction report
as friction-report.md, following the schema in friction-schema.md.

Rules:
- Use the scores friction-detector computed. Do not recompute or adjust them.
- Carry every confidence downgrade and every coverage caveat into the report. A finding
  that arrives qualified leaves qualified.
- Fill the detection-coverage table from summary.stores.
- Where the four disagree about one skill, report the disagreement rather than choosing
  between them.
- No original text of anything. Figures, classifications and scores only.
- State whether the analysis ran with independent executors or degraded to sequential
  in-context reading.
```
