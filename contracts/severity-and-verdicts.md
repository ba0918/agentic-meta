# Severity and Verdicts

The severity vocabulary a finding carries, and the verdicts a review as a whole reaches.
A finding is one detected problem; a verdict is the judgment over a whole review. Both
are shared between skills, so both are fixed here rather than restated per skill.

Whether a finding's fix can be automated is a separate, orthogonal axis, defined by
[fix-action-taxonomy.md](fix-action-taxonomy.md).

## Severity definitions

| Severity | Meaning | Criteria for choosing it | Examples |
|---|---|---|---|
| **BLOCK** | Cannot proceed. Continuing as-is causes a serious problem | Security vulnerability, risk of data loss, fundamental design defect | Unmitigated SQL injection, authentication bypass, inverted layer dependency |
| **WARN** | Needs consideration. Not fatal if unaddressed, but should be improved | Performance concern, reduced maintainability, unhandled edge case | An O(n^2) algorithm (when n is small), a duplicated rule, insufficient error messages |
| **OPPORTUNITY** | An improvement opportunity. Acting on it is optional, and it states both what improves and what is risked by acting | Nothing is currently wrong, but a distinct gain is identifiable together with its cost | Capturing an existing behavior as a regression fixture, consolidating a duplicated explanation into a contract reference |
| **INFO** | For reference. Acting on it is optional | Style suggestion, future improvement idea, introduction of an alternative approach | Naming suggestions, library recommendations, future refactoring candidates |
| **PASS** | No problem | No problem was detected for the aspect in question | - |

> **Beware the ambiguity of `PASS`**: the severity PASS (no problem for a given aspect) and
> the review verdict PASS below (the review as a whole passed) are different axes. Make clear
> from context which one is meant. An aspect that was never examined must not be reported as
> PASS — PASS is a result of examining, not of skipping.

## Implementation review verdicts

| Verdict | Condition | Action |
|---|---|---|
| **PASS** | No BLOCK, no WARN. Implementation is sound | Proceed |
| **WARN** | No BLOCK. WARN-level issues remain | Review warnings, fix if necessary |
| **BLOCK** | Critical implementation issues detected | Fix before proceeding |
| **ESCALATE** | The finding cannot be resolved without changing an already-agreed specification | Return it to whoever owns that agreement. A review cannot close a specification gap on its own authority |

## Code review verdicts

| Verdict | Condition | Action |
|---|---|---|
| **PASS** | No problems, or INFO only | Continue |
| **PASS WITH NOTES** | WARN-level findings exist. Not fatal | Record the findings and continue |
| **NEEDS FIX** | A BLOCK-level problem exists | Issue fix instructions and re-implement, then re-review (at most one retry) |

### Handling NEEDS FIX

- **Interactive run**: pass the fix instructions on, re-implement, re-review (at most one retry)
- **Non-interactive run**: emit the review result and stop. The decision on what happens next
  belongs to whoever reads it, and there is nobody to ask mid-run
