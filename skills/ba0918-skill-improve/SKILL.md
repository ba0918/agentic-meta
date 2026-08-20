---
name: ba0918-skill-improve
description: Detects friction in skill usage by reading the session logs an agent already left behind, and turns those traces into per-skill friction scores that name what to fix. Reading is split from analysis, so the same measurement runs over three agent runtime stores — Claude Code JSONL, an OpenCode SQLite database, and Codex CLI rollout JSONL — and each store declares which detection routes it actually supports rather than filling an undetectable route with a guess. Its masked prompt harvest is the only source of real-data seeds for `ba0918-trigger-eval`. Use when the user says "skill-improve", "improve the skills", "analyze the friction", or asks which skills are being used badly.
license: MIT
metadata:
  contracts:
    - fixture-contract
---

# ba0918-skill-improve

An agent's session log is the only record of how a skill behaved in real use. This skill
reads that record, counts the traces of a skill being used badly — the same skill invoked
again moments later, a user restating the request right after an invocation, a tool call
that failed — and scores each skill so the worst friction is the thing that gets fixed.

Reading is separated from analysis. An adapter per store yields normalized events and
declares its own detection capabilities; the aggregation layer never learns a store's
storage format, and a route a store cannot detect is reported as undetectable rather
than estimated.

## Terminology

| Term | Meaning |
|---|---|
| store | One agent runtime's session history, in whatever form that runtime keeps it. Three are supported: [references/session-stores.md](references/session-stores.md) |
| detection route | How a skill firing becomes visible. **text** — a slash command in what the operator typed. **structural** — the runtime's own record of the tool call |
| friction signal | A counted trace of a skill going badly: a retry, a correction, an abandoned session, a failed tool run |
| measurement | The JSON `collect.py` writes. Counts, classifications and declarations only — never a body |
| friction report | The Markdown a run composes from the measurement. The deliverable |
| harvest | The masked utterance bodies `capture.py` writes. The one route by which words leave a store |

## What this reads, and the permission to read it

**Invoking this skill is the explicit grant the read-scope clause of
[references/vendor/fixture-contract.md](references/vendor/fixture-contract.md)
requires.** That clause bounds an instrument to its own directory, the target tree and
its output area, and demands a grant stated in the invocation before it reads the
executing user's session history or anything else on the machine.

The grant is exactly this and nothing wider:

- **Claude Code** — the per-project session log directory under the operator's home, or
  the directory given as `--claude-root`.
- **OpenCode** — the runtime's SQLite database under the operator's home, or the file
  given as `--opencode-db`. Opened read-only, and the `session`, `message` and `part`
  tables are the whole of what any statement names. The credential tables in the same
  database are never named by any statement this skill can issue.
- **Codex CLI** — the rollout log directory under the operator's home, or the directory
  given as `--codex-root`.

Nothing else on the machine is read. Every path is resolved and required to stay inside
the location it was read from, links included. A store that is not there is reported and
stepped over, never substituted for by looking somewhere else, and a store that is there
and cannot be read stops that one reading rather than the run.

## What each store can be read for

| Store | text | structural | Session abandonment | Tool errors |
|---|---|---|---|---|
| Claude Code | yes | yes | inferred | fully readable |
| OpenCode | yes | yes | inferred | fully readable |
| Codex CLI | yes | **no** | recorded by the store | **newer logs only** |

**A route that cannot be read is reported, never estimated.** Codex has no skill tool at
all — across 114,117 records, not one tool name corresponds to a skill call — and the
available inference is to read a firing out of a shell command string. It is refused:
33% of the recorded commands mention a skill directory, which is a command that read or
wrote a skill's files, not one that fired the skill. The same holds for the older
generation of Codex logs, where a failure sits in the body of a call's output with no
exit status beside it, and for the second copy of every Codex utterance, which is a
superset holding tool output rather than a second source.

The full evidence — every measurement behind those three refusals, plus how turns are
counted the same way in all three stores — is in
[references/session-stores.md](references/session-stores.md).

Why this matters downstream: a friction score built on invented firings recommends
fixing a skill nobody ran. That is worse than a report saying the route could not be
read, which is why a skill seen only through a store without the structural route
carries a confidence downgrade rather than a repaired count.

## Execution contract

- Call the scripts by absolute path: `python3 {skill_dir}/scripts/<name>.py`, where
  `{skill_dir}` is the directory holding this SKILL.md.
- Everything a run produces goes to `.agents/tmp/skill-improve-{datetime}/` under the
  working directory — outside whatever tree is being measured, as the run-output clause
  of the fixture contract requires. Nothing is ever written into a skill being analysed.
- **Create that directory before the first script runs.** Neither script creates it, and
  neither says so when it is missing: `collect.py` ends in an uncaught
  `FileNotFoundError`, and `capture.py` refuses with a message naming the containment
  rule rather than the absent directory.
- **Write `--project=KEY`, not `--project KEY`.** A project key is a working-directory
  path with every character outside letters, digits and hyphen replaced by a hyphen, so
  it begins with a hyphen and a space-separated value is read as another option.
- `--store` selects what to read: `claude`, `opencode`, `codex`, or `all` (the default).
  A name no store answers to is refused rather than read as an empty selection — a
  misspelt store would otherwise produce a report of no friction anywhere, which reads
  exactly like a clean measurement.
- `--days N` sets the period (default 30). `--all-projects` reads every project instead
  of the working directory's.

## Choosing a workflow

| Input | Workflow |
|---|---|
| "improve the skills" / "analyze the friction" / "which skills are being used badly" | **analyze** (default) |
| "just the numbers" / "give me the raw data" | **report** |
| "harvest the prompts" / a `ba0918-trigger-eval` run asking for real-data seeds | **capture** |

## Workflow: report — the measurement alone

```bash
mkdir -p .agents/tmp/skill-improve-{datetime}
python3 {skill_dir}/scripts/collect.py \
  --days 30 \
  --project=<project key> \
  --output .agents/tmp/skill-improve-{datetime}/context.json
```

Across every project instead of one, replace `--project=<key>` with `--all-projects`.
Use that form for user-scoped skills, or to see usage tendencies across all of them.

Read the result and show its summary:

```
── Data collection ──
Project: {project_filter} (all projects: {true/false})
Projects scanned: {count}
Period: {days} days
Stores: {per store — present, text, structural, abandonment recorded or inferred,
        error detection full or partial}
Sessions: {sessions_found}
Skill invocations: {total_skill_invocations}
Unique skills: {unique_skills_used}
Secret warnings: {count}
```

**Report the store situation even when it is boring.** A store that was absent, a route
that was unavailable, and a session read as a superset of what was said all belong in
what a reader sees, not only in the JSON. The schema is
[references/friction-schema.md](references/friction-schema.md).

In `report` the workflow ends here.

**When `analysis.proceed` is false**, say what the result says and stop:

```
No skill invocation was found in the last {days} days.
Widen the period with --days, or check the project filter.
```

Every friction rate divides by the number of firings, so an analysis of nothing
produces scores out of nothing. Do not go on.

## Workflow: analyze — the friction analysis (default)

**Scoring and writing the report belong to the roles, not to this list.**
friction-detector scores; the integrating role writes the report from the four answers
and is told not to recompute a score. Doing either here as well would produce a second
set of numbers with no way of saying afterwards which set the report carries.

1. **Collect**, exactly as in `report` above. Stop there if nothing fired.
2. **Run the four analysis roles** over the measurement, then the integrating role over
   their four answers. Roles, their prompts, and their output schemas are in
   [references/analysis-roles.md](references/analysis-roles.md).
   - The four roles are separated for parallelism and cost, **not** to isolate a bias.
     Every role reads the same finished measurement, so merging two of them costs
     breadth, not validity — unlike the three-role separation of
     `ba0918-empirical-prompt-tuning`, where the separation is the instrument itself.
   - **Supplying a way to start an independent model invocation is the invoking
     session's business.** Where none can be had, degrade to sequential in-context
     analysis and **say so in the report**. Degrading silently is the one forbidden
     outcome.
3. **Check the two things no role is free to decide.** Where a check fails, have that
   role redo its answer; do not repair the answer yourself, which is the same second
   set of numbers by another route.
   - Every score came from the formula in
     [references/scoring-guide.md](references/scoring-guide.md). It is the only one, and
     a role that weighed the terms its own way has not scored this measurement.
   - The report names every confidence downgrade and every qualification that holds,
     and carries figures,
     classifications and scores only — never the original text of an utterance or a
     response, never a session identifier, never a credential even masked. Its schema is
     [references/friction-schema.md](references/friction-schema.md).
4. **Present the hypotheses and stop.** Each carries a target, the change, the expected
   impact, a Small or Large size estimate, and a confidence.

```
── Friction analysis ──
Roles: {4/4, or how many ran} ({parallel | sequential in-context})
Skills analysed: {N}
Top friction skill: {name} (score: {score}, confidence: {confidence})
Coverage limits: {routes unavailable, counts resting on an inference}
Report: .agents/tmp/skill-improve-{datetime}/friction-report.md
```

## Workflow: capture — the prompt harvest

The one route by which utterance bodies leave a store, and the only source of real-data
seeds for `ba0918-trigger-eval`.

```bash
mkdir -p .agents/tmp/skill-improve-{datetime}
python3 {skill_dir}/scripts/capture.py \
  --days 30 \
  --project=<project key> \
  --output .agents/tmp/skill-improve-{datetime}/prompts.jsonl
```

- **The record shape is frozen.** Five fields — `ts`, `project`, `user_text_masked`,
  `fired_skill`, `signals` — and two signal names, `slash_fired` and
  `correction_after_skill`. `ba0918-trigger-eval` names all of them in its own body.
- **Four guards stand before the write, and all four fail closed**: the output must
  resolve inside `.agents/tmp` under the working directory; git itself must say the
  path is ignored, with any answer it cannot decide refused like a negative one; the
  neighbouring name the write lands on first must be created new, so a link or a
  leftover already sitting there is refused rather than written through; and the file is
  replaced in one step. A guard that refuses is an answer, not an obstacle — do not work
  around one by harvesting some other way. A leftover is cleared by removing the file
  the refusal names, never by harvesting elsewhere.
- **The masking is a blocklist and is therefore not complete.** A credential shaped
  unlike any pattern it knows survives it. A harvest is sensitive material even after
  masking: treat it that way, and delete it when the run that needed it is done.

## Where this stops

**This skill measures and recommends. It does not carry the improvement out.**

The collector it was ported from ended by handing small changes to one improvement
workflow and large ones to another, and that routing is deliberately gone. An instrument
that measures skills and also rewrites them cannot afterwards say which of the two it
was doing, and its own measurements stop being evidence about anything but itself. The
Small / Large size estimate stays in the report, because sizing a change is measurement
information; naming who performs it is not.

Also outside scope: reading anything on the machine beyond the three stores named above,
and reconstructing a detection route a store does not have.

## Cleaning up

Delete the intermediate files inside `.agents/tmp/skill-improve-{datetime}/` when the run
ends, whether it ended well or badly: the measurement, the four role answers, and the
harvest if one ran.

**The friction report stays where it was written, and the directory holding it stays with
it.** The report is the deliverable, it holds no bodies, and the directory is named after
the run that produced it. Deleting the directory would take the report with it, which is
why the instruction above is about what is inside rather than about the directory.

A harvest is deleted rather than kept, masked or not.

## Error handling

| Situation | What to do |
|---|---|
| The output directory does not exist yet | `collect.py` ends in an uncaught `FileNotFoundError`; `capture.py` refuses, naming the containment rule instead. Create `.agents/tmp/skill-improve-{datetime}/` and run again |
| A store's location is not there | Already handled: it is reported in `notes`, read as empty, and the run goes on. Carry the absence into the report |
| A store is there and cannot be read | Already handled: that store's reading stops where it broke, the reason goes in `notes`, and the remaining stores are still read. Carry it into the report separately from an absence — its counts are a floor, not a total |
| `--store` names nothing | The run refuses. Fix the name; do not read it as "no stores" |
| No firing found in the period | Stop after collection. Say the period and the project filter |
| There is no way to start an independent model invocation at all | Degrade: work all four role prompts one after another in the current context, and say so in the report. Not the row below — nothing failed here, the mechanism is simply absent |
| Roles were started and some did not answer | Go on where two or more answers came back, naming the roles that are missing. With fewer than two answers, stop — one reading is not an analysis |
| The harvest is refused by a guard | Report that no real-data seeds were produced, and why. Never harvest by another route |

## Red flags

- A report that names no coverage limits at all, when a store with no structural route
  was among those read.
- A recommendation to change a skill whose confidence is Low.
- A friction score computed from a formula other than the scoring guide's.
- A harvest kept after the run that asked for it finished.
- Any original text in the report — an utterance, a response, or a path naming somebody.

## Related

- [references/session-stores.md](references/session-stores.md) — the three stores, what each can be read for, and the measurements behind every refusal to guess
- [references/friction-schema.md](references/friction-schema.md) — the measurement JSON, the frozen harvest record, and the report's schema and forbidden fields
- [references/scoring-guide.md](references/scoring-guide.md) — the score, the thresholds, what the report recommends, and the three confidence downgrades
- [references/analysis-roles.md](references/analysis-roles.md) — the four roles, their prompts and schemas, and the sequential degradation
