---
name: ba0918-skill-interface-audit
description: Audit each SKILL.md statically as an API specification and report what its contract is missing — undeclared side effects, completion conditions that cannot be verified, undefined failure handling — alongside structural violations. Every finding carries a patch candidate, and none is ever applied automatically. Use when the user says "skill-interface-audit", "audit the interfaces", "check the skill contracts", "audit SKILL.md", or "check the API specification".
metadata:
  contracts:
    - fixture-contract
    - severity-and-verdicts
    - fix-action-taxonomy
---

# ba0918-skill-interface-audit

Taking the principles of [references/authoring-principles.md](references/authoring-principles.md) as the source of truth, statically audit each SKILL.md as an "API specification".
Where the sibling measurement skills own dynamic measurement and the quality of resident instructions, this skill owns **the contractual completeness of a skill tree's SKILL.md files**.

## Positioning and architecture

Reference material (progressive disclosure):

- Positioning and architecture: [references/positioning.md](references/positioning.md)
- Rule definitions: [references/rule-catalog.md](references/rule-catalog.md)
- The audit's source of truth: [references/authoring-principles.md](references/authoring-principles.md)
- The definition of the three fix-action values: [references/vendor/fix-action-taxonomy.md](references/vendor/fix-action-taxonomy.md)
- The definition of severity: [references/vendor/severity-and-verdicts.md](references/vendor/severity-and-verdicts.md)
- Finding the skills in a target tree, and where a run may write: [references/vendor/fixture-contract.md](references/vendor/fixture-contract.md)

## Arguments

- No argument: audit every skill in the target tree.
- One or more skill names: audit only the named skills. For example: `ba0918-skill-interface-audit ba0918-trigger-eval`
- `--update-baseline`: fix the current findings as the baseline (thereafter only new findings are presented).
- `--bridge`: generate the bridging output toward dynamic verification (Phase 3).

No command is created; being single-workflow, it needs no named entry point.

## Execution contract

- **Resolving script paths**: `{skill_dir}` is the directory this skill is installed in (an absolute path). `{target}` is the tree under audit, defaulting to the current project root.
- **Non-interactive fallback**: when running headless or as a subagent, fall to the safe side and change no state. Do not write the baseline; emit the full report.
- `{ts}` is minted with `date +%Y%m%d-%H%M%S` and the same value is reused across the phases.
- **Output location**: `.agents/tmp/skill-interface-audit-{ts}/` in the repository of the session running the audit — **never inside `{target}`**, per the run-output placement clause of [references/vendor/fixture-contract.md](references/vendor/fixture-contract.md). The baseline lives on the same side and is keyed to the target it was taken from. This audit needs no working copy of its target.

## Workflow

### Phase 0: Discovery

1. Resolve `{target}`'s skill container by the layer order of [references/vendor/fixture-contract.md](references/vendor/fixture-contract.md), and build the target list. Narrow it if skill names were given as arguments
2. Pass the resolved container to `static_checks.py` as `--skills-dir`. The script serves this phase only and reports what it could read; **anything it passed over is yours to state in the report**
3. Also collect the files under each skill's `references/` as secondary targets
4. Check whether the baseline file (`.agents/config/skill-interface-audit-baseline.json`) exists
5. How the baseline is handled:
   - **Auditing every skill with no baseline present**: present the first-run flow — (a) fix the current state as the baseline and present only new findings thereafter, or (b) the full report only (the baseline is not written)
   - **A single skill specified**: do not present the baseline first-run flow. Emit the full report. Write the baseline only when `--update-baseline` is explicit

### Phase 1: Static checks (pure functions)

Run the SI-S\* rules in one batch and emit a findings JSON.

```bash
python3 {skill_dir}/scripts/static_checks.py --root {target} --skills-dir <the resolved container> \
  --output .agents/tmp/skill-interface-audit-{ts}/findings-static.json
```

Target rules: SI-S001 through SI-S004, plus SI-S006 (details in [references/rule-catalog.md](references/rule-catalog.md)).

The finding schema:
`id / severity / action / where(skill:file:line) / what / why / how / fix_draft(null | suggested text)`

### Phase 2: Contract assessment (LLM, REPORT\_ONLY)

The LLM evaluates the SI-C\* rules. Keep this clearly separate from Phase 1.

1. Read each skill's SKILL.md and evaluate the contract elements SI-C001 through SI-C006. [references/rule-catalog.md](references/rule-catalog.md) owns their definitions, the cases where an element is legitimately unnecessary, and the discipline behind their severities
2. The criterion is not "does the section exist" but "**could an LLM misunderstand this point and cause an accident**"
3. Every finding is REPORT\_ONLY, and a patch candidate is **never applied automatically** — rewriting the meaning of a body is not an automatic fix. That single rule is quoted here in full, so do not read the taxonomy for this step; the reference stays available for the three-value definitions

### Phase 3: Aggregate and bridge

1. Merge the findings of Phase 1 and Phase 2
2. Apply the baseline suppression and present only the new findings (state the suppressed count explicitly; silent truncation is forbidden)
3. Generate a summary-first report:
   ```
   N findings: X NEEDS_JUDGMENT / Y REPORT_ONLY; M suppressed
   ── Phase 1 (structural) ──
   [findings grouped by rule, severity descending]
   ── Phase 2 (contract) ──
   [findings grouped by rule, severity descending]
   ```
4. When `--bridge` is given, generate the bridging output toward dynamic verification:
   - The ambiguous spots of an SI-C\* finding → scenario candidates for `ba0918-empirical-prompt-tuning` (mapped onto the friction-taxonomy categories)
   - The diff after applying a patch candidate → fixture candidates for `ba0918-skill-regression`
   - **When a destination skill is absent from the environment, do not delegate**: write the bridging output as a file under the output directory and state in the report which destination was missing. The absence is reported, never silent
5. Emit the completion report the completion conditions below require

### The friction-taxonomy mapping (for the bridge output)

Map SI-C\* findings onto the fixed taxonomy of `ba0918-empirical-prompt-tuning` to prevent the vocabulary from being duplicated:

| SI-C rule | friction category | Basis |
|---|---|---|
| SI-C001 side effects | rationalization\_hook | Undeclared side effects get rationalized away |
| SI-C002 completion conditions | ambiguous\_term / missing\_premise | An ambiguous completion condition produces multiple readings |
| SI-C003 failure handling | missing\_premise | Implicit premises about failure scenarios |
| SI-C004 input | missing\_premise / ambiguous\_term | Implicit premises about the arguments |
| SI-C005 output | ambiguous\_term | An ambiguous definition of the deliverable |
| SI-C006 delegation | self\_containment\_gap | Implicit dependence on another skill |

## Important rules

- **Findings are proposals, never edits**: every output is REPORT\_ONLY or NEEDS\_JUDGMENT, and applying a patch candidate is the user's decision
- **Do not turn it into template enforcement**: do not make it a pressure to "add N sections to every skill". The criterion is "could an LLM misunderstand this point", not uniformity of form
- **Do not re-decide what the target's own validation entry point already enforces**; where the target has none, say so in the report
- **Ground the basis of a severity in experience**: "directly causes accidents" at a given tier is an empirical claim. Anything that cannot be tied to measured friction data stays at INFO
- **Do not invent new criteria**: every finding traces to a principle of `authoring-principles.md`

## Side effects

- Writes a report and a findings JSON into the output directory, and the baseline file only when `--update-baseline` is given
- **Never changes** the target tree

## Completion conditions

- Phase 1 and Phase 2 are complete for every target skill
- The summary-first report has been generated
- When a baseline update was requested, the baseline file has been written
- The report names the checks that were run, their results, and what was left unchecked. A completion claim standing on anything but a command run in this session and its output is not a completion claim

## Handling failures

- The Phase 1 script fails to run: report the error and proceed to Phase 2 (do not discard the partial results)
- The Phase 2 LLM evaluation fails for a particular skill: skip that skill and continue with the rest
- Every phase fails: emit an error report containing whatever information could be collected

## Prerequisites

- Python 3 must be available
- `{target}` resolves to at least one skill

## Delegation conditions

| Situation | Delegate to |
|---|---|
| You want to measure the triggering accuracy of the descriptions | `ba0918-trigger-eval` |
| You want to evaluate the execution quality of a skill body | `ba0918-empirical-prompt-tuning` |
| You want to verify regressions after changing a skill | `ba0918-skill-regression` |
| You want to detect friction in real operation | `ba0918-skill-improve` |
| You want to audit the resident instruction files an agent carries | `ba0918-context-audit` |
| Code and documentation consistency inside a skill | `ba0918-doc-check` |

**When the destination is absent from the environment, state that in the report and stop there.** Do not substitute another skill, and do not carry out the destination's work yourself.
