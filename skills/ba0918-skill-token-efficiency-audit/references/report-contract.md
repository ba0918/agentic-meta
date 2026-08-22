# Report Contract

Start with exactly one overall verdict: `IMPROVEMENT_RECOMMENDED`, `EVALUATE_THEN_DECIDE`, `NO_SUPPORTED_IMPROVEMENT`, or `INDETERMINATE`, followed by a one-paragraph basis.

Then report:

1. **Required-quality baseline** — each required property and whether it is confirmed or inferred.
2. **Candidates** — a compact table, then only decision-relevant detail. Each `TE-<N>` includes current mechanism, causal chain, root-relative evidence location, evidence class, confidence, proposed change, expected effect, required-quality impact, preferred-quality impact, validation, migration lifetime, and current recommendation.
3. **Coverage and limitations** — full reads, partial reads with ranges/sections and reasons, structural-only files, unread files and reasons, unresolved references, supplied measurements, and approximate input bytes. Never reproduce source or prompt bodies.
4. **Brainstorm handoff** — candidate IDs, undecided trade-offs, required-quality invariants, current and proposed variants, evaluation use cases, token metrics, and adoption/rejection conditions. Name an existing evaluation skill when one is available. Do not start the brainstorm.

If there are no candidates, keep the candidate section explicit and explain the evidential limit. If coverage prevents judgment, identify the missing information that would resolve it.

Never include raw sessions, session identifiers, credentials, private identifiers, fabricated measurements, or persistent artifact paths created by the audit.
