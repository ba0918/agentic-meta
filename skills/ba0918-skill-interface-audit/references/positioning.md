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

**Relation to the target repository's own checks**: a repository that ships a validation entry
point already enforces some of this mechanically — frontmatter shape, description trigger
wording, link existence. Those are not re-decided here; this skill owns the structural quality
that a repository-level check does not look at. The relation runs both ways, and that is the
exit strategy: a rule that proves stably machine-decidable in the audit is a candidate to move
into the target repository's own checks and out of this catalog. When a target has no
validation entry point at all, nothing is subtracted — say so in the report rather than
assuming the checks ran elsewhere.

## Architecture: the hybrid model

**Pure functions deliver deterministic verdicts; the LLM is used for semantic judgment only.**
This is not a purely static audit: contract completeness is a reading of intent, so the SI-C\*
rules are decided by the LLM and stay REPORT_ONLY.

| Phase | Verdict by | Target rules | fix action ceiling |
|---|---|---|---|
| Phase 1 | pure functions (script) | SI-S\* | NEEDS_JUDGMENT |
| Phase 2 | LLM | SI-C\* | NEEDS_JUDGMENT (the finding itself is REPORT_ONLY; only the decision to apply a patch is NEEDS_JUDGMENT) |
