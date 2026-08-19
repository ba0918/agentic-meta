# Iteration Record Schema

Appended one record per line to `.agents/tmp/empirical-prompt-tuning-{ts}/iterations.jsonl`.
Structured fields only. Free text is forbidden.

## Schema

```json
{
  "iteration": 1,
  "prompt_bytes": 4200,
  "checklist_sha256": "abc123...",
  "instruction_fingerprint": "def456...",
  "eval_strategy": "task_scenario | compliance_probe",
  "k_runs": 1,
  "scenarios": [
    {
      "id": "A",
      "title": "the median scenario",
      "success": true,
      "precision": 0.9,
      "steps": 4,
      "duration_ms": 20000,
      "retries": 0,
      "friction": [
        {
          "category": "ambiguous_term | missing_premise | contradictory | over_specified | rationalization_hook | self_containment_gap | uncategorized",
          "detail": "free text (supplementary)",
          "checklist_item_index": null
        }
      ],
      "checker_grades": [
        { "requirement_index": 0, "result": "pass | fail | partial", "evidence": "..." }
      ],
      "harness_error": null
    }
  ],
  "exit_verdict": "continue | converged | diverged | bloat_advisory | halt",
  "halt_reason": null
}
```

## harness_error (scenarios[])

The field that records checker / harness deviations separately from candidate failure.
`null` when normal. On an anomaly, the form is:

```json
{
  "type": "malformed_output | missing_grade | extra_grade | duplicate_grade | invalid_result_value | empty_checklist | missing_evidence | missing_isolation_note | isolation_violation | input_range_violation",
  "detail": "free text (supplementary)"
}
```

`type` is kept in sync with `PROTOCOL_FAILURE_TYPES` in `scripts/convergence.py`
(every classification is emitted from `validate_input_range()` / `validate_checker_output()`).
A scenario carrying a harness_error is excluded from the precision aggregate and the convergence/divergence verdict, and
`resolve_exit_verdict()` returns halt (`halt_reason == "checker_protocol_failure"`).

For details, see the "Separating protocol failure from candidate failure" section of
[checker-protocol.md](checker-protocol.md).

## Field definitions

| Field | Required | Meaning |
|-----------|------|------|
| `iteration` | yes | 0-origin. Iteration 0 is the static description/body consistency check |
| `prompt_bytes` | yes | the byte size of the target prompt. Used for bloat detection |
| `checklist_sha256` | yes | the checklist sha256 at baseline. Used for tamper detection |
| `instruction_fingerprint` | yes | the content sha256 of the target files. Tracks the instruction version |
| `eval_strategy` | yes | `task_scenario` (an active workflow) or `compliance_probe` (a passive constraint) |
| `k_runs` | yes | how many times the same scenario is run in parallel (1 by default) |
| `scenarios[].success` | yes | every `[critical]` requirement passed |
| `scenarios[].precision` | yes | the requirement achievement rate (0.0-1.0) |
| `scenarios[].steps` | yes | the executor's tool_uses count |
| `scenarios[].duration_ms` | yes | the executor's duration_ms |
| `scenarios[].friction` | yes | the friction report (an empty array is fine). category comes from the fixed taxonomy |
| `scenarios[].checker_grades` | yes | the checker's grading results |
| `scenarios[].harness_error` | yes | a protocol failure (null allowed). Details above |
| `exit_verdict` | yes | the value returned by `resolve_exit_verdict()` in `convergence.py` |
| `halt_reason` | no | on halt only: `max_iter` / `max_wallclock` / `kill_file` / `checklist_tampered` / `checker_protocol_failure` |

## Conversion into a portable fixture

On convergence (`exit_verdict == "converged"`), emit the final iteration's scenarios + checklist as
`fixture.json`. For the format, see §E of SKILL.md.
