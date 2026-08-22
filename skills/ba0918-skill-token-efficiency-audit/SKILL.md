---
name: ba0918-skill-token-efficiency-audit
description: Audit a named skill for token-efficiency improvements without changing it. Trace repeated reads, oversized input or output, broad scans, reviewer fan-out, full-review loops, retries, and conditional material loaded unconditionally; distinguish measured facts, structural derivations, and hypotheses; and expose quality trade-offs and validation needs. Use when the user asks whether a skill can use fewer tokens, lower token cost, avoid repeated reads, narrow review loops, or become cheaper without hiding a possible quality loss.
license: MIT
metadata:
  contracts:
    - fixture-contract
---

# Skill Token Efficiency Audit

Audit one explicitly named skill and report supported ways to reduce total input and output tokens while preserving its required quality. Stop after presenting the analysis; do not brainstorm, plan, or apply a candidate.

## Inputs and boundaries

- Require a skill name or path. If a name is ambiguous, list the candidates and ask for a path.
- Resolve the target by [the fixture contract](references/vendor/fixture-contract.md). Treat the selected skill directory as the granted target tree.
- Accept existing evaluations or aggregated measurements only at paths explicitly granted in the invocation. Never search session stores, home directories, sibling projects, or the network.
- Remain read-only: do not change the target, write a report or cache, execute target scripts or commands, start evaluations, or launch agents/models.

## Workflow

1. Run `python3 {skill_dir}/scripts/inventory.py <target-or-container> [--name <skill-name>]`. Use its JSON as the structural record; do not infer contents for unresolved references.
2. Read the selected `SKILL.md` in full. From its normative words (`must`, `always`, `before`, `required`) and workflow, identify references that are mandatory at runtime and read those in full.
3. For other reachable files, begin with inventory metadata and headings. Read only sections needed to reconstruct a relevant execution path. Record each file as full, partial (with the section/range), structural-only, unread, or unresolved.
4. Reconstruct `input -> reads -> decisions -> branches/repetition/delegation -> output`. Read [analysis-guide.md](references/analysis-guide.md) in full before judging causes, quality, evidence, or migration lifetime.
5. For every supported candidate, assign a stable `TE-<N>` ID. Read [report-contract.md](references/report-contract.md) in full before writing the response, then follow it exactly.
6. Present the report in the conversation and stop. Never turn the handoff into a brainstorm or implementation plan.

## Completion and failure

Complete only when the response names the target and coverage, checks every visible amplification point, labels evidence strength and confidence, separates required from preferred quality, states validation and migration lifetime, avoids invented numbers, and records every unread or unresolved dependency.

If the target is absent or unusable, report `INDETERMINATE` without analysis. If a reference is unreadable or dynamic, continue with partial results and explain how the gap affects the verdict. If required quality or a major execution path is unknown, the overall verdict is `INDETERMINATE`.
