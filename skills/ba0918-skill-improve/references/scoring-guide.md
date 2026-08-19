# Scoring guide

How to turn one skill's counts in the measurement into a friction score, what the score
means, and how much of it to believe.

The score exists to rank. It says which skill's friction is worst and therefore which
one is worth reading closely — nothing more. Carrying an improvement out is outside
this skill; what a score produces is a recommendation in the report.

## The score

```
friction_score = min(10, (
    retry_rate       × 3.0 +
    correction_rate  × 2.0 +
    abandonment_rate × 3.0 +
    error_rate       × 2.0
))
```

| Rate | Formula | Range |
|---|---|---|
| retry_rate | `retry_count / invocation_count` | 0 to 1 |
| correction_rate | `correction_turns / (invocation_count × 5)` | 0 to 1, saturating at 5 turns per firing |
| abandonment_rate | `session_abandoned_count / invocation_count` | 0 to 1 |
| error_rate | `tool_error_count / max(total_turns_to_completion, 1)` | 0 to 1, saturating at 1 |

Every field named above is read from that skill's entry in `friction_signals`. A skill
with `invocation_count` 0 does not appear there at all: every rate divides by the
firings, so a skill never fired has no rate to compute and is not scored as
frictionless.

### Two things the counts mean that their names do not say

**`retry_count` is the length of a run, not the number of repeats.** The first repeat of
a skill reads as 2, not 1. The thresholds below were calibrated against that counting,
and changing the counting without recalibrating them would move every verdict silently.

**Session-wide counts are attributed whole to every skill fired in that session.**
`tool_error_count` and `total_turns_to_completion` are the session's, not the skill's
share of it. What is being measured is the friction *around* a skill, and a session
that failed throughout failed around each of them. A skill fired in a session alongside
three others therefore carries the same error count they do.

## Threshold table

| Score | Verdict | Meaning |
|---|---|---|
| 0.0 – 0.9 | **Excellent** | No friction. Nothing to change |
| 1.0 – 1.9 | **Good** | Minor friction. Worth watching, not worth acting on |
| 2.0 – 2.9 | **Acceptable** | Within tolerance. Record it and move on |
| 3.0 – 4.9 | **Needs Attention** | The report should recommend a change and say where |
| 5.0 – 6.9 | **Problematic** | The report should recommend a change and rank it above the others |
| 7.0 – 10.0 | **Critical** | The report should say this is the first thing to fix, and why |

## What the report recommends

The score decides what the report says, not what the run does. This skill produces a
recommendation and stops there; whoever reads the report decides whether and how to act
on it.

| Score | The report says | Size estimate |
|---|---|---|
| 0 – 2 | Record the numbers. No change recommended | — |
| 3 – 5 | Recommend a change, scoped to a SKILL.md or a reference: wording, an added guard, a clarified step | **Small** |
| 6+ | Recommend a change the size of a plan: a phase that should not exist, a responsibility in the wrong place, a guard that has to be structural rather than textual | **Large** |

The size estimate stays in the report because sizing is measurement information — the
counts are what distinguish a skill whose wording misleads from one whose shape is
wrong. What the size no longer does is name a workflow to hand the work to. The source
this was ported from routed Small to one improvement workflow and Large to another, and
that routing is deliberately gone: an instrument that measures skills and also rewrites
them cannot say afterwards which of the two it was doing.

Each hypothesis in the report carries what the old pre-change preview carried: the
files a change would touch, an outline of the change, and the expected movement in the
score. That is reporting, not a gate before an edit — there is no edit.

## Confidence

Confidence is not a smaller score. It says how much the score itself can be relied on,
and it is reported beside every score. Three downgrades apply, and they stack: apply
each one that holds, and name every one applied in the report.

### 1. Sample size

| `invocation_count` | Confidence | Meaning |
|---|---|---|
| 1 – 2 | Low | Not a sample. The score is indicative only |
| 3 – 9 | Medium | A tendency is visible, statistically insufficient |
| 10+ | High | A score worth acting on |

A Low-confidence skill is recorded in the report and is not recommended for change.

### 2. Seen only through a store with no structural route

Read from `confidence_downgraded`; `stores_without_structural` names the stores that
caused it. **Drop the confidence one step** — High to Medium, Medium to Low — and say
in the report which store forced it.

A store with no structural route cannot observe a skill the agent fired on its own;
only one the operator typed as a slash command is visible there. The firing count from
such a store is therefore systematically incomplete, and every rate divides by it. An
incomplete denominator inflates every rate built on it, so the resulting score
overstates friction rather than understating it.

Never repair this by estimating the missing firings. The measurement refuses that
inference for a reason recorded with its evidence in
[session-stores.md](session-stores.md), and a score is exactly the place where an
invented number would do its damage: it drives a recommendation to change a skill that
was never used.

### 3. Abandonment that was inferred rather than recorded

Read from `stores_with_inferred_abandonment`; `summary.stores[*].abandonment` says the
same thing per store. Where a skill's `session_abandoned_count` includes sessions from
such a store, **treat the abandonment term as the least reliable of the four** and say
so in the report.

Only one of the three stores writes down that a session was broken off. For the other
two it is inferred: a session whose failed tool runs exceed 30% of its turns is read as
having been broken off. That inference and a recorded fact are not the same
measurement, and `abandonment_rate` carries the heaviest weight in the formula, so a
score dominated by an inferred term deserves the qualification.

The inference also became easier to trip than the calibration behind it assumed. Turns
are now counted as speech only — a runtime's own bookkeeping no longer swells the
denominator — so the same session has fewer turns than the collector this replaces
would have counted, while its failed runs are unchanged. The 30% share is reached
sooner. Treat an inferred abandonment as a reason to read the session rows, not as a
number to rank on.

### A fourth qualification, not a confidence downgrade

`summary.stores[*].superset_utterance_sessions` counts sessions whose utterances could
only be read as a superset of what the operator actually said — tool output and
harness-injected text filed under the operator's role, with no field separating them.
`correction_turns` counts utterances, so in those sessions it is an over-count.

This qualifies one term rather than the whole score, so it is stated where the
correction rate is reported instead of moving the confidence. If the correction term
dominates a skill's score and its sessions were read that way, say so plainly.
