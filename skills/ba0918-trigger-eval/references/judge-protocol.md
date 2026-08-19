# judge-protocol — the judging agent contract

The input/output contract for the Tier 1 selection simulation's judging agent (a subagent delegation, **model: sonnet stated explicitly**, a fresh subagent). Two anti-bias rules govern the delegation. **Never hand your own conclusion over**: the agent receives the description list and the cases, never an expected answer or a caller-side verdict, because a conclusion passed along pulls the judgment toward agreeing with it (anchoring). **Never put the answer inside the question**: ask which skill the instruction selects, not whether it selects a named one.

## The 2 judging modes (selection / autonomous)

Judging is run in 2 independent modes. **The input/output schema is shared**; only the framing handed to the judging agent differs.

- **selection mode** (the traditional default behavior): "Pick the skill from the list that best fits the given instruction. If none fits, return `none`" = measures the discriminability of the description list. A framing that implicitly assumes a skill will be launched.
- **autonomous mode** (new): "You are a Claude Code assistant. Decide for yourself whether to respond to this user instruction normally or to launch a skill. Return a skill name only if you launch one; return `none` if you should respond normally" = does **not** force a skill launch. It measures a distribution closer to the salience with which a model decides in real use whether something "is worth launching a skill for".

Both modes use the same input schema and the same case batches, and **produce an independent judgment result JSON per mode** (`judged-{mode}-iterN.json`). The results must never be mixed (see the validity limits below).

## What is and is not handed to the judging agent

- **Handed over**: the description list (JSON of `{name, description}`) plus the batch of fictional instruction cases (an array of `{case_id, text}`).
- **Not handed over**: the body of SKILL.md. At real firing time the model sees only the description, so showing the body diverges from that field of view and produces false positives (the same thinking as `ba0918-empirical-prompt-tuning` Iteration 0).
- **Tool prohibition**: **switch the tool-prohibition wording in the prompt to match the distribution method** (never hand over a self-contradictory contract). For inline delivery: "use no tools at all; judge only from the given input". For file delivery: "you may read only the 2 files specified. Any other tool use or file read is forbidden". Either way it is a prompt-level **soft guarantee** and does not mechanically strip tool access (state this limit explicitly).

### Input distribution methods (the formal contract)

Input to the judging agent is limited to one of these 2 forms:

1. **Inline delivery**: embed the description list and the case batch directly in the prompt body. No additional file read occurs.
2. **File delivery**: allow reading **only 2 files** — `skills.json` (the description list) and the case batch file. Any tool use or file read beyond those 2 files is forbidden.

## Input schema

```json
{
  "skills": [{"name": "commit", "description": "..."}, ...],
  "cases": [{"case_id": "c001", "text": "commit this change"}, ...]
}
```

- **Chunk the batches to at most 20 cases per call.** Dispatch multiple batches concurrently (at most 4 in parallel).
- Shuffle the case order (to counter position bias).

## Output schema

The judging agent returns one label per case:

```json
{"judgments": [{"case_id": "c001", "choice": "commit"}, {"case_id": "c002", "choice": "none"}, ...]}
```

- `choice` is one of the skill names in the description list, or `none` (firing no skill is correct).
- **A single label only.** Never list several skills.

## Validation on collection (the driver's responsibility)

1. **Verify that "the number of judgments == the number of cases".**
2. Normalize `choice` (reduce to a bare name): strip any plugin prefix and align it to the same namespace as Phase 0.
3. **Producing INVALID** (owned by this document):
   - The whole batch response is unparseable → **re-judge every case_id in the batch exactly once**. If it is still malformed, materialize every case_id as `predicted=INVALID`.
   - An individual choice is (a) unparseable, (b) a skill name outside the list, or (c) several skills → re-judge that case exactly once. If it is still malformed, `INVALID`.
   - **How INVALID is counted** is owned by `metrics-spec.md` (counted as an FN for the correct skill, and as an FP for nothing).

## Measuring stability

Judge the same case independently twice (j1, j2). From the second iteration onward, **reduce by default to a fixed sample of 20-30 cases**. Choose the sample deterministically once, record it in the ledger, and use the same one across every iteration (`--full-stability` restores the full set).

## Skill name extraction and normalization in Tier 2 (real E2E firing)

Tier 2 detects firing from the session's own output stream (`--output-format stream-json --include-partial-messages`, `content_block_start` → tool_use detection, removing the `CLAUDECODE` env var, terminating the process as soon as the first Skill tool_use is detected). Where a boolean detector would stop at "some skill fired", this skill **extracts the skill name from the Skill tool_use `input` and normalizes it to the same bare name as Phase 0** (for confusion attribution). **Do not specify a permission mode** (plan mode's system prompt changes the firing distribution and contaminates the calibration).

## Validity limits (things to state / knobs)

- **selection is an upper bound on discriminability; autonomous is an approximation of salience. Their distributions differ, so the results must never be mixed** — mixing averages two different populations and damages both signals.
- The judging model (a lightweight model) differs from the session model in real use.
- Therefore Tier 1 recall/precision is **a metric relative to a lightweight-model selector**, and **its divergence from Tier 2 real firing is the calibration signal**.
- "The judging model" and "the Tier 2 execution conditions (`--max-turns` / timeout / worktree)" are knobs.
