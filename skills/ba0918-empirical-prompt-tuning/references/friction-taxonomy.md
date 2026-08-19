# Friction Taxonomy

The fixed taxonomy for classifying the executor's friction reports.
It makes free text comparable across iterations and sharpens the divergence verdict.

## The 6 categories

| Category | Definition | A typical executor remark |
|---------|------|---------------------|
| `ambiguous_term` | wording open to multiple interpretations | "I cannot tell what level 'appropriately' means" |
| `missing_premise` | implicit background knowledge is required | "the version of this API is unknown" |
| `contradictory` | contradiction between instructions | "section A and section B say opposite things" |
| `over_specified` | unnecessarily strict, leaving no room for judgment | "even the variable names are dictated and they do not match reality" |
| `rationalization_hook` | an instruction that can be dodged by rationalizing | "it says 'as needed', so I skipped it" |
| `self_containment_gap` | does not stand alone without external references | "I cannot tell what to do without reading references/X.md" |

`uncategorized` is the fallback when none of the above applies.

## Category → fix pattern mapping

| Category | Recommended fix pattern |
|---------|----------------|
| `ambiguous_term` | add a definition or narrow the term (e.g. "appropriately" → "conforming to RFC 7231") |
| `missing_premise` | state the premise, or add a minimal complete example inline |
| `contradictory` | state the priority order, or delete one side |
| `over_specified` | loosen the constraint, or demote it to "recommended" |
| `rationalization_hook` | close the escape hatch ("as needed" → enumerate the concrete conditions) |
| `self_containment_gap` | inline the necessary information, or state the reference and when to read it |

## Connection to the divergence verdict

When the same category appears `threshold` times in a row (3 by default),
`is_diverged()` in `convergence.py` declares divergence.
This is the signal that "the same kind of problem is not being fixed by patches → the structure should be rewritten".

## Instructions to the executor

Include the following in the executor's friction report template:

```
## Friction report
Report the places where the instructions tripped you up, using these categories:
- ambiguous_term: wording open to multiple interpretations
- missing_premise: implicit background knowledge is required
- contradictory: contradiction between instructions
- over_specified: unnecessarily strict
- rationalization_hook: an instruction that can be dodged by rationalizing
- self_containment_gap: does not stand alone without external references

Format: { "category": "<category>", "detail": "<detail>" }
Return an empty array [] when none apply.
```
