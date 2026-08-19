---
name: ba0918-trigger-eval
description: A meta skill that mechanically measures how accurately a skill set's descriptions fire (recall / precision / stability / confusion matrix) by judging from the descriptions alone, identifies colliding pairs, and runs the rewrite then re-evaluation loop to convergence. The target is this repository's skills/, any skill directory, or the user scope. Use when the user says "trigger-eval", "firing accuracy", "measure skill firing", "trigger evaluation", "rewrite the descriptions", or "show me skill collisions with a confusion matrix". Sister skill of `ba0918-empirical-prompt-tuning`, which covers the quality of body execution; this one measures the selection layer, description to firing.
metadata:
  contracts:
    - fixture-contract
---

# ba0918-trigger-eval

Spontaneous skill triggering from natural-language instructions degrades as a skill set grows. This skill treats that as a property of description quality: the judging agent is passed **nothing but the list of descriptions** — the model's field of view at real triggering time — so recall / precision / stability / confusion matrix are measured mechanically, and the revise→re-evaluate loop runs to convergence.

## Minimal execution recipes

```
ba0918-trigger-eval                # Phase 0→6 over this repository's skills/
ba0918-trigger-eval --dir PATH     # any flat skill directory
ba0918-trigger-eval --user-scope   # the runtime's user-scope skill directory (resolved by collect_descriptions.py)
ba0918-trigger-eval --no-e2e       # skip the Tier 2 live-firing check (it runs by default)
ba0918-trigger-eval --selection-only  # measure Tier 1 in selection mode only (the default is selection + autonomous)
```

No command is created; being single-workflow, it needs no named entry point.

## Architecture: a static pre-pass plus two evaluation tiers

| Tier | Method | Cost |
|----|------|--------|
| Phase 1.5 static collision pre-pass | Compute all pairwise collision candidates deterministically from the vocabulary Jaccard of the descriptions (`static_collisions.py`, no LLM) | Nearly zero |
| Tier 1 selection simulation | Pass a bias-free subagent only the description list plus a batch of fictional instructions, and have it choose the skill to use (or none) as JSON | Low (a lightweight model, ≤20 cases per call, dispatched in parallel) |
| Tier 2 E2E real-triggering verification | Pass the fictional instructions raw to a fresh non-interactive agent session and detect the skill invocation from its execution trace (invocation mechanics: [references/judge-protocol.md](references/judge-protocol.md)). **Run it in a throwaway git worktree** | High (a total cap of 6 sessions, enforced by a driving-side shell loop) |

The detailed contracts for judging and aggregation are split into reference material (progressive disclosure):

- The judging agent's contract: [references/judge-protocol.md](references/judge-protocol.md)
- Case design guidelines: [references/testcase-design.md](references/testcase-design.md)
- The strict definition of the metrics: [references/metrics-spec.md](references/metrics-spec.md)

Subagent invocations state a high-capability model explicitly — judging work has no verification gate, so never let it fall to a default cheap tier.

## Workflow

### Phase 0: Collect the targets

```bash
python3 skills/ba0918-trigger-eval/scripts/collect_descriptions.py --dir skills \
  --output .agents/tmp/trigger-eval-{ts}/skills.json
```

- Turn the `{name, description}` list into JSON. With no argument, the current repository's `skills/*/SKILL.md`. Apply it generally with `--user-scope` / `--dir PATH`.
- **Resolve the target and place the output per [references/vendor/fixture-contract.md](references/vendor/fixture-contract.md)**: find the skill container in the target tree by that contract's layer order and hand it to `--dir`, and keep every artifact this run produces outside the target tree.
- **Normalize the skill names to the bare name with the plugin prefix removed**, and use that same namespace thereafter for the cases' correct labels, the judging choices, and the aggregation.
- **Duplicate bare names are fail-fast** (v1 does not support duplicate namespaces).
- **Out of scope for v1**: the hashed nested layout of the runtime's plugin cache directory. Add the glob to `collect_descriptions.py` when it becomes necessary.

### Phase 1: Harvest real-data seeds (optional)

Real-data seeds come from the prompt harvest of `ba0918-skill-improve`. **When that skill is absent from the environment, record "no real-data seeds — synthetic cases only" in the report and go straight to Phase 1.5.** The absence is stated, never silent.

When it is present, harvest the triggering record and the missed-triggering candidates (the `correction_after_skill` signal plus the masked `user_text_masked`) into `.agents/tmp/trigger-eval-{ts}/prompts.jsonl`:

- The harvester **verifies before writing that the path is ignored, via `git check-ignore --quiet <the resolved actual output path>`, and refuses on a non-zero result** (fail-closed; it does not scan the root .gitignore as a string).
- **The masking is a denylist and is not complete**, so treat a harvested body file as sensitive even after masking (delete it in Phase 6).

### Phase 1.5: Static collision pre-pass

```bash
python3 skills/ba0918-trigger-eval/scripts/static_collisions.py \
  .agents/tmp/trigger-eval-{ts}/skills.json --top-n 30 \
  --output .agents/tmp/trigger-eval-{ts}/collisions.json
```

The top pairs define the "neighboring skills" for hard-negative generation and nothing else. Do not use the ranking to prioritize revisions or to nominate merge candidates: the 2026-07-27 measurement (188 cases) showed the top 3 static pairs had zero measured confusion while the only confused pair ranked 7th — confusion comes from missing discriminating information, which set operations on vocabulary cannot see. Hard-negative material needs pairs that *look* confusable, not pairs that *are* confused, so that use survives.

### Phase 2: Generate the test cases and freeze them in advance

**The generator is a dedicated subagent (a lightweight model) separate from the reviser.** [testcase-design.md](references/testcase-design.md) owns the case ratios, the per-call chunk limit, the stratified holdout split and the triple anonymization gate. On top of that contract:

- **Freeze the cases into `cases.json` (train) and `cases_holdout.json` (holdout)**. No substitution thereafter, and never show the holdout to the revision loop.
- **Apply the anonymization gate before freezing**, not after.

### Phase 3: Judging round

Pass the judging agent (**a lightweight model, stated explicitly**, a fresh subagent) the description list plus a batch of cases, and collect its JSON answers. [judge-protocol.md](references/judge-protocol.md) owns the input and output schemas, the input distribution methods, the batching and shuffling rules, the collection validation and the stability sampling. On top of that contract:

- **Judge in two modes** (selection / autonomous). **The default measures both**, and `--selection-only` restores the former behavior. The schemas are shared and only the framing differs. Generate `judged-{mode}-iterN.json` separately per mode, and never mix them.

### Phase 4: Aggregation

```bash
# run the same script separately per mode (aggregate_metrics.py stays unmodified)
python3 skills/ba0918-trigger-eval/scripts/aggregate_metrics.py \
  .agents/tmp/trigger-eval-{ts}/judged-selection-iterN.json \
  --output .agents/tmp/trigger-eval-{ts}/metrics-selection-iterN.json
# unless --selection-only is set, aggregate autonomous the same way
python3 skills/ba0918-trigger-eval/scripts/aggregate_metrics.py \
  .agents/tmp/trigger-eval-{ts}/judged-autonomous-iterN.json \
  --output .agents/tmp/trigger-eval-{ts}/metrics-autonomous-iterN.json
```

Compute recall / precision / specificity / stability / confusion matrix / invalid_rate with the formulas of `metrics-spec.md`. **Never mix the two modes' results**: selection is authoritative for the convergence and regression guards, and autonomous is a reference series ("The mode axis" of `metrics-spec.md`).

### Phase 5: Revision

- Narrow the revision to the worst offenders (the top confusion pair, or the skill with the lowest recall) and revise its description (**one theme per iteration**).
- Conform to the frontmatter contract (trigger words mandatory, a 1024-character cap, no workflow summaries). **Make the target repository's own validation entry point the completion condition for a revision; when the target has none, state that absence explicitly in the report** rather than treating the revision as validated.
- **When revising, visually confirm consistency with the SKILL.md body** (do not promise capabilities beyond the body for the sake of the trigger rate).
- **One revision = one git unit per skill.** If re-evaluation regresses or validation fails, revert that description to its pre-revision state (the rollback path).
- This phase rewrites its target, so it runs against a working copy taken per the mutating-instrument model of [references/vendor/fixture-contract.md](references/vendor/fixture-contract.md). The canonical target tree stays read-only for the whole run.

### Phase 6: Re-evaluation → convergence judgment

Repeat Phases 3-5, judging the stopping conditions on the selection series (Phase 4). The stopping conditions are any of:

1. **Convergence**: the improvement in macro recall / precision is under +1pt for two consecutive iterations.
2. **Hard cap**: `max_iterations = 5`.
3. **Regression guard**: any skill's recall / precision, or specificity / invalid_rate, regresses by **more than 5pt** against the previous iteration → revert the last revision and stop (a defined↔undefined transition in precision is a non-comparison; see metrics-spec.md).

After stopping:

- (a) **The holdout judgment (mandatory, an adoption gate)**: if the holdout's macro recall / precision is not non-degraded against the pre-loop baseline, **revert the last adopted revision and state "holdout FAIL" explicitly in the report**.
- (b) **Tier 2 real-triggering verification** (a stratified, fixed 6 sessions, with the cap enforced by a driving-side shell loop, **run by default**, skippable with `--no-e2e`). Record the Tier1↔Tier2 divergence rate.

**Tier 2's stratified allocation (fixed)**: 2 positives for the revised skill / 1 positive for the worst unrevised skill / 1 none / 1 hard negative / 1 at random from all cases. **When no revision was adopted (immediate convergence, or everything reverted by a holdout FAIL), reallocate the revised-skill slots to positives for the worst-recall skill.** Always attach a note to the divergence-rate report that it is a stratified small sample and not an estimate of the whole.

### Report

Emit to `.agents/tmp/trigger-eval-{ts}/report.md`:

- The metric trajectory / the top confusions (**only the non-zero cells and the top N pairs, not a full matrix dump**, listing both the raw value and the normalized rate `confusion(A,B)/related_cases(A,B)`)
- **The selection / autonomous modes side by side** (selection only under `--selection-only`). Place selection as the primary metric and autonomous as a reference series, and note the divergence between them as a salience signal. **Never emit a mixed value**
- The revision diffs / the Tier1↔Tier2 divergence rate / the holdout judgment
- **Candidate pairs for merging or redesigned separation** (only pairs whose measured confusion does not resolve after two revisions — never the static pre-pass ranking; see Phase 1.5)
- Execution metadata (the judging model / the date / the sha256 of `cases.json` and `cases_holdout.json` / the stability sample ledger)

**What is retained is report.md / cases.json / cases_holdout.json / the metrics JSON of each iteration** (the anchors for reproduction and cross-run comparison). **The harvest files containing raw prompt bodies are deleted**, along with `trigger-eval-*` directories older than 30 days.

## The four-part set of resource caps

Leave no dimension unbounded:

1. Judging batches of ≤20 cases per call, plus the judgments==cases verification
2. Case generation of ≤10 skills per call, plus the count verification
3. The `max_iterations = 5` hard cap on the revision loop, plus the regression guard
4. JSONL is pre-filtered by mtime and streamed line by line; Tier 2 is 6 sessions × (a 2-turn cap + a 180s timeout)

## Red flags (signs of a trigger-eval violation)

- Passing the SKILL.md body to the judging agent
- Editing the cases after freezing them / showing the holdout to the revision loop
- Adopting despite the regression guard or the holdout gate on the grounds that "it is written in the report", without reverting
- Leaving the harvested prompt bodies among the retained artifacts
- Always skipping Tier 2 without a reason
- A revised description promising capabilities beyond the SKILL.md body
