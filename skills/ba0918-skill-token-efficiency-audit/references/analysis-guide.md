# Analysis Guide

## Cost causality

Use `content volume × read count × path frequency × fan-out × retries` only to locate amplification. It is not a savings estimator. Trace the mechanism from source material to tokens consumed; do not flag repetition merely because text is duplicated.

Consider oversized inputs/outputs, repeated reads, broad discovery, unconditional references, ambiguous instructions, absent stop conditions, full reviews after local changes, identical context sent to multiple agents, and exception handling paid on the normal path. Add uncategorized mechanisms when the evidence supports them.

## Quality baseline

Classify quality as:

- **Required**: safety, correctness, completion, supported primary uses, mandatory gates, and prohibitions. A candidate that lowers required quality is normally rejectable.
- **Preferred**: detail, rare-case coverage, convenience, or breadth that a declared use case may trade for efficiency.

Find the baseline in this order: existing scenarios, explicit contracts, user-stated uses, the SKILL.md purpose and uses, then explicitly granted usage evidence. Never treat low observed frequency as proof that a use is unnecessary.

## Evidence and confidence

- `MEASURED`: supplied run results or token counts. State period, trials, and version when available.
- `DERIVED`: reproducible structure such as bytes, declared loop counts, or fan-out.
- `HYPOTHESIZED`: a plausible runtime effect inferred from static structure.

Do not state numeric savings without measured or mechanically derived support. Assign confidence from evidence completeness, not rhetorical certainty.

## Candidate judgment

Recommend a candidate only when the causal chain and evidence location are explicit. Preserve safety repetition unless a cheaper mechanism demonstrably carries the same role. Scoped re-review may replace full review only when changed assumptions, shared contracts, unresolved findings, or wide impact restore the full gate.

Classify lifetime as structural, migration-only, or unknown. A migration-only optimization must justify paying its implementation cost before migration ends.

Choose the overall verdict:

- `IMPROVEMENT_RECOMMENDED`: at least one supported candidate can preserve required quality.
- `EVALUATE_THEN_DECIDE`: a plausible candidate needs effect or quality measurement.
- `NO_SUPPORTED_IMPROVEMENT`: disclosed coverage supports no candidate; this is not proof that none exists.
- `INDETERMINATE`: missing required information prevents an overall judgment.
