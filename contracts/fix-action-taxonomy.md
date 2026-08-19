# Fix-Action Taxonomy

How a detected finding may be handled: whether its fix may be applied automatically, needs a
human decision, or is reported and nothing more. This is **an axis orthogonal to severity**
([severity-and-verdicts.md](severity-and-verdicts.md)), which says how serious the finding is.

## The two axes are orthogonal

| Axis | Values | Meaning | Defined in |
|---|---|---|---|
| severity | BLOCK / WARN / OPPORTUNITY / INFO / PASS | How serious the problem is | [severity-and-verdicts.md](severity-and-verdicts.md) |
| fix action | AUTO_FIX / NEEDS_JUDGMENT / REPORT_ONLY | Whether the fix can be automated | This file |

A WARN can be AUTO_FIX, and it can equally be REPORT_ONLY. Do not conflate the two.

## The three fix actions

### AUTO_FIX

Conditions: **mechanically verifiable, idempotent, and carrying no risk of data loss**.
Running the same operation any number of times yields the same result. The tool presents the
diff and applies it after confirmation. **Deletion, and semantic rewriting of body text, are
never AUTO_FIX.**

There is one permitted variation, apply-then-report: a skill may apply its AUTO_FIX findings
immediately with no per-finding confirmation, provided it commits nothing, enumerates every
applied fix in its final report, and leaves a single human decision point downstream (a commit
or merge review). A skill taking this route states so in its own body; it is a declared
exception, not a default.

Examples: replacing an obvious path typo pointing at a real file (a unique candidate),
normalizing a frontmatter key while the body is untouched.

### NEEDS_JUDGMENT

Conditions: **semantic interpretation is required, or the intent behind the text is ambiguous**.
The tool presents the finding and a recommended action, and **a human decides**. When in doubt,
fall here rather than to AUTO_FIX.

Examples: several path candidates with no unique resolution, a coverage difference in a listing
where the omission may well be deliberate.

### REPORT_ONLY

Conditions: **informational only**. No automatic action is taken. The finding is presented as an
actionable report covering what, why and how, and nothing is changed.

Examples: vocabulary that permits destructive operations, leaked tool vocabulary, contradiction
candidates, suspected secrets (auto-masking is forbidden — masking a secret in place hides the
leak without revoking it).

## Gate Function

```
Before assigning a fix action to a finding, ask:

1. Is this fix mechanically verifiable, and does it give the same result
   however many times it runs?
   NO  -> not AUTO_FIX
2. Does it involve data loss (deletion, semantic rewriting of body text)?
   YES -> not AUTO_FIX
3. Is the intent uniquely determined (one candidate, no interpretation needed)?
   NO  -> NEEDS_JUDGMENT
4. Is it actionable at all, or does it stop at providing information?
   Information only -> REPORT_ONLY

When in doubt, fall to the safe side: REPORT_ONLY over NEEDS_JUDGMENT over AUTO_FIX.
```
