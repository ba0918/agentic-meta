# metrics-spec — the strict definition of the trigger-eval metrics

The single canon for the formulas that `aggregate_metrics.py` and its unittests implement. Fixture expectations are hand-computed from these formulas. Judging is non-deterministic, but aggregation over a judgment result JSON is deterministic, so the tests use hand-written judgment result JSON as fixtures.

## The mode axis (selection / autonomous)

Judging is run in 2 modes, selection and autonomous (see `judge-protocol.md`). **The mode does not affect the aggregation schema**:

- Produce an independent judgment result JSON per mode (`judged-{mode}-iterN.json`) and **pass each of them through the existing `aggregate()` unchanged** to obtain `metrics-{mode}-iterN.json`. `aggregate_metrics.py` is unmodified (it takes no mode argument; the modes are separated by filename only).
- **Never mix the judgment results of the 2 modes into one JSON for aggregation** (the populations differ; see the validity limits in `judge-protocol.md`).
- **The convergence and degradation guards of the rewriting loop (SKILL.md Phase 6) treat selection as authoritative.** autonomous is treated as a **reference series** plus the calibration signal for the Tier1(selection)↔Tier2 divergence (never make a revert decision from autonomous alone).

## Input JSON schema (the wrapper)

What `aggregate_metrics.py` reads is not a bare case array but an object wrapping it. The wrapper keys are part of the contract, not an implementation detail of the script:

```json
{
  "cases": [ ... ],
  "valid_skills": ["skill-a", "skill-b"],
  "stability_sample_ids": ["c1-001", "c1-002"]
}
```

| Key | Required | Meaning |
|---|---|---|
| `cases` | yes | The array of the case schema below |
| `valid_skills` | yes | The label space, as bare skill names. **Do not include `none`** — it is added automatically, and anything outside `set(valid_skills) \| {none}` normalizes to `INVALID` |
| `stability_sample_ids` | no | The fixed sample of `case_id` for the stability series. Omitted means the full set |

Writing a caller from this document alone used to fail with `KeyError: 'valid_skills'`, because the wrapper was specified nowhere and the script was its own only canon. A producer that emits the case array under any other key (`skills`, a bare array, ...) is wrong even if every case inside it is well-formed.

## Case JSON schema

```json
{"case_id": "str", "gold": "skill-name | none", "judgments": ["j1", "j2?"]}
```

- **The metrics (TP/FN/FP, confusion, specificity, invalid_rate) treat j1 alone as authoritative.** The `(j1, j2)` pair is **for stability only**.
- INVALID normalization is applied per judgment (independently to j1 and j2).

## Label space

The set of normalized bare skill names + `none` + `INVALID` (an aggregation-only bucket).

## Judgment normalization (the counting side)

A judgment is `INVALID` if it is (a) unparseable, (b) a skill name outside the list, or (c) several skills. **The rules for producing INVALID are owned by judge-protocol.md** (settled after exactly one re-judgment). This document owns only how they are counted. `aggregate_metrics.normalize_judgment(j, valid_labels)` is the last line of defense for the invariant: any value not in `valid_labels = set(skills) | {none}`, any list, and None all become `INVALID`.

## per-skill aggregation

For a skill S (the judgment is j1):

- **TP** = (gold=S ∧ j1=S)
- **FN** = (gold=S ∧ j1≠S)  — includes none, another skill, and INVALID
- **FP** = (gold≠S ∧ j1=S)  — includes both gold=none and gold=another skill
- **recall(S)** = TP / (TP + FN)
- **precision(S)** = TP / (TP + FP)
- **When TP+FP=0, precision(S) is undefined** (`None`) and is excluded from the macro precision average (include this case in the fixtures).

## Overall aggregation

- The headline metrics are the **macro averages**:
  - macro recall = averaged over the skills whose recall is defined (= having at least 1 gold case)
  - macro precision = averaged over the skills whose precision is defined (TP+FP>0)
- Also report **micro** for reference: micro recall = ΣTP / Σ(TP+FN), micro precision = ΣTP / Σ(TP+FP).

## Handling none (specificity)

none has no recall/precision row.

- **specificity** = (gold=none ∧ j1=none) / (all gold=none cases)
- An error of gold=none ∧ j1=S is attributed to **S's FP**.
- gold=none ∧ j1=INVALID is **included in the denominator of specificity but not in the numerator**.
- If there are 0 gold=none cases, specificity = `None`.

## invalid_rate

- **invalid_rate** = (number of judgments with j1=INVALID) / total cases.
- INVALID is counted **as an FN for the correct skill, and as an FP for no skill**.
- With 0 cases, it is 0.0.

## stability

- **stability** = the exact-match rate of `(j1, j2)` for the same case (compared on normalized labels; INVALID matching INVALID counts as a match).
- **The cross-iteration trend series is always computed over the fixed sample subset** (so the population is aligned and the series is comparable). Restrict the sample with `aggregate(cases, skills, stability_sample_ids=[...])`. Even iteration 1, which judges the full set twice, computes its series value restricted to the sample subset (the full-set value is reported separately for reference).
- If 0 cases have a j2, value = `None` and sample_size = 0. **Always state sample_size.**

## confusion matrix

- Rows = gold, columns = j1 (including the `none` / `INVALID` columns). The output contains **only non-zero cells** (never dump the full matrix).
- **Pair ranking**:
  - `raw(A,B)` = count[gold=A, j1=B] + count[gold=B, j1=A] (descending is the primary key)
  - `related_cases(A,B)` = **the total number of cases whose gold label is A or B**
  - `normalized(A,B)` = raw / related_cases (reported alongside; prevents a skew in how many cases were fed from distorting the top entries)
  - Pairs with raw=0 are not emitted. Sorting is (raw desc, normalized desc, a, b).
- The pair space is `skills ∪ {none}` (INVALID is never a member of a pair).

## The defined-transition convention for the degradation guard

In an iteration where a per-skill precision crossed between defined and undefined, that skill's **precision term is excluded from the 5pt degradation guard comparison** (non-comparison). recall, specificity, and invalid_rate are always comparable because the case set is fixed. This convention is applied by the rewriting loop (SKILL.md Phase 6); `aggregate_metrics.py` only reports whether each per-skill precision is defined or undefined (`None`).

## Division-by-zero conventions (summary)

| Metric | When the denominator is 0 |
|------|-------------|
| recall(S) | TP+FN=0 → `None` (excluded from macro recall) |
| precision(S) | TP+FP=0 → `None` (excluded from macro precision) |
| specificity | 0 gold=none cases → `None` |
| invalid_rate | 0 cases → `0.0` |
| stability | 0 cases with a j2 → `None` (sample_size=0) |
| normalized(A,B) | related 0 → `0.0` |
