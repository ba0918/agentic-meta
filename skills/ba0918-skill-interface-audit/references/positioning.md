# Positioning and Architecture

## Positioning

| Layer | Skill | Question |
|---|---|---|
| Selection layer | ba0918-trigger-eval | Does it fire correctly? (dynamic measurement) |
| **Contract layer** | **ba0918-skill-interface-audit** | **Is it complete as a specification? (static)** |
| Execution layer | ba0918-empirical-prompt-tuning | Is the execution quality high? (dynamic) |
| Regression layer | ba0918-skill-regression | Does the behavior hold after a change? (fixtures) |
| Operations layer | ba0918-skill-improve | Is there friction in real use? (log measurement) |

**The boundary against instruction-file auditing is cut exclusively by the target file set**:
`ba0918-context-audit` owns the resident instruction files an agent carries into every task,
and this skill owns the skills themselves — each `SKILL.md` plus the reference files beside it.

**Relation to the target repository's own checks**: what a target's own validation entry point
already enforces mechanically — frontmatter shape, description trigger wording, link existence
— is not re-decided here; this skill owns the structural quality such a check does not look at.
The relation runs both ways, and that is the exit strategy: a rule that proves stably
machine-decidable in the audit is a candidate to move into the target's own checks and out of
this catalog. A target with no validation entry point subtracts nothing — say so in the report
rather than assuming the checks ran elsewhere.

## Architecture: the hybrid model

This is not a purely static audit: contract completeness is a reading of intent, so the SI-C\*
rules are decided by the LLM and stay REPORT_ONLY.

| Phase | Verdict by | Target rules | fix action ceiling |
|---|---|---|---|
| Phase 1 | pure functions (script) | SI-S\* | NEEDS_JUDGMENT |
| Phase 2 | LLM | SI-C\* | NEEDS_JUDGMENT (the finding itself is REPORT_ONLY; only the decision to apply a patch is NEEDS_JUDGMENT) |
