# testcase-design — test case design guidelines

The guidelines for generating and pre-fixing cases in Phase 2.

## Case types and ratios

For each target skill:

- **positive**: a fictional instruction that should fire that skill. 2 per skill.
- **hard-negative**: a confusable instruction **whose correct answer is a neighboring skill** from the top collision pairs of Phase 1.5 (`static_collisions.py`). 1-2 per skill. It must satisfy "confusable, but exactly one correct answer".
- **none**: an instruction for which firing no skill is correct. **At least 25% of the whole.**

Every case carries **a single correct label** (a skill name or `none`). Ambiguous or polysemous instructions are excluded at generation time (**handling ambiguous cases is out of scope for v1**).

## Generation limits and chunk validation

- Split into chunks of **at most 10 skills per call** (a limit designed symmetrically with the judging batch of ≤20).
- **Verify that the number of emitted cases == the expected number.** Regenerate on a mismatch.

## The pre-fixing principle and stratified holdout split

- Fix the cases in Phase 2 and **never move them in later iterations** (no substitutions).
- **Fix them into 2 files: `cases.json` for train and `cases_holdout.json` for holdout**:
  - The holdout is **about 20%** of the whole. This is a target, not a fixed value — see below.
  - **A stratified split that keeps the none ratio at 25% or more on both the train and holdout sides.** **The stratification constraint dominates the fraction**: satisfy it first, then land as close to 20% as it allows.
  - Never show the holdout to the rewriting loop; the post-convergence holdout verdict is the acceptance gate (SKILL.md Phase 6).

### Computing the feasible split before splitting

The two rules above are not always jointly satisfiable, so **compute the feasible range first and fail loudly when it is empty** — do not discover it by a split that silently violates one of them. For a total of `N` cases with `M` of them `none`, a holdout of size `H` needs a holdout-`none` count `h` such that

```
ceil(0.25 * H) <= h <= M - ceil(0.25 * (N - H))
```

Choose the `H` closest to 20% for which that range is non-empty. Worked example from the 2026-07-27 run (`N = 188`, `M = 47`):

| `H` | `H / N` | required `h` | feasible |
|---:|---:|---|---|
| 37 | 19.7% | `10 <= h <= 9` | no |
| 38 | 20.2% | `10 <= h <= 9` | no |
| 39 | 20.7% | `10 <= h <= 9` | no |
| **40** | **21.3%** | `10 <= h <= 10` | **yes (h = 10, unique)** |
| 41 | 21.8% | `11 <= h <= 10` | no |

A flat 20% fails here for every rounding, and the only feasible split is 40 with exactly 10 `none`. If no `H` in a reasonable band works, the corpus itself is the problem — go back to generation and raise the `none` count rather than bending either rule.

## The triple anonymization gate (always applied before fixing)

Including the case where you paraphrase and adopt a real-data seed from the Phase 1 harvest, apply the following mechanically **before** fixing the cases. The cases file is the only thing that gets persisted, so stop it here:

1. **Re-apply the masker**: re-apply the Phase 1 harvester's secret masker to every case string. **When no harvest ran** (`ba0918-skill-improve` absent from the environment) there is no masker and no real-data seed to mask; record that and go on to rule 3.
2. **Near-match check against the raw real-data seed**: reject a case whose normalized edit distance is **below 0.30 (= 70% or more identical)** as "insufficiently paraphrased" (a check that the LLM's anonymization has not effectively become a copy).
3. **High-entropy token screen**: reject cases where a prefix-less secret value survived the paraphrase. Decide mechanically: **among consecutive tokens of 20 or more characters matching `[A-Za-z0-9+/=_-]{20,}`, treat as high-entropy only those mixing all 3 of digits, uppercase letters, and lowercase letters**. Tokens without all 3 kinds (e.g. long lowercase-and-hyphen skill names such as `migrate-cycles-to-plans` or `design-guide-mockup`) are out of scope to avoid false positives. Redact or reject any case containing a high-entropy token.

## How to use real-data seeds

- The files captured in Phase 1 hold firing records and misfire candidates. These are **seeds**, not cases as such: always run them through paraphrasing + the triple gate, and prefer a paraphrased real seed to an invented one.
- Failure examples put into `report.md` must be **anonymization-checked cases only** (transcribing a raw seed is forbidden).

## Generator separation

The case-generating subagent and the description rewriter must be **different agents**. When one agent does both, it has a conflict of interest: generating cases that are easy to rewrite for.
