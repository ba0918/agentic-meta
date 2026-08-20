---
name: ba0918-context-audit
description: An inventory skill that audits LLM instruction files (CLAUDE.md / AGENTS.md / PROJECT.md / .claude/rules / project memory) for decay, contradiction, harmful instructions, and cross-tool divergence. It verifies mechanically with a pure-function rule engine (the CA-* rule system), handles findings with the 3 values AUTO_FIX / NEEDS_JUDGMENT / REPORT_ONLY, and never automates deletion. It owns "quality as instructions", which neither code-versus-docs nor docs-versus-docs checking looks at. Use when the user says "context-audit", "audit the instruction files", "take inventory of CLAUDE.md", "audit AGENTS.md", "review the memory files", "the instructions have rotted", or "check whether the instructions are stale".
license: MIT
metadata:
  contracts:
    - severity-and-verdicts
    - fix-action-taxonomy
    - fixture-contract
---

# ba0918-context-audit

The behaviour of an agent rests on the instruction layer it reads: `CLAUDE.md`, `AGENTS.md`,
`PROJECT.md`, the rules directory, and the project memory carried from one session into the
next. That layer decays under long use. References point at files that were deleted. One
file forbids what another permits. Wording creeps in that waives confirmation before a
destructive step. Vocabulary belonging to one runtime leaks into a file meant to be
independent of any. And memory, which nobody reviews, keeps values nobody meant to keep.

This audit takes stock of it. Checking a document against the code it describes, and
checking documents against each other, belong elsewhere; what this one owns is the files
that instruct an agent, judged as instructions.

## Architecture

The deterministic work sits in the scripts. This body holds only what a script cannot: the
sequencing of the phases, the one classification a rule is not entitled to make, and the
confirmation before anything is applied. **No decision procedure belongs here.**

| Script | Role |
|---|---|
| `scripts/collect_targets.py` | Finds the audit targets by allowlist, and resolves the project's memory directory |
| `scripts/static_checks.py` | The rule engine: the `RULES` registry and its dispatcher. Emits the findings |
| `scripts/apply_fixes.py` | Findings plus a file's content to new content. Idempotent, and a body's bytes are left as they were |
| `scripts/aggregate_report.py` | Findings plus a baseline to a summary-first report. Also writes the baseline |
| `scripts/secret_detect.py` | Detection and masking of credentials. A byte-identical copy of the one `ba0918-skill-improve` carries |

Reference material (progressive disclosure):

- The rules, one row each: [references/rule-catalog.md](references/rule-catalog.md)
- Auditing memory, and the constraints on it: [references/memory-audit.md](references/memory-audit.md)
- The baseline's format and operation: [references/baseline-format.md](references/baseline-format.md)
- What a severity means: [references/vendor/severity-and-verdicts.md](references/vendor/severity-and-verdicts.md)
- What the three fix actions mean: [references/vendor/fix-action-taxonomy.md](references/vendor/fix-action-taxonomy.md)
- The clause bounding what an instrument may read: [references/vendor/fixture-contract.md](references/vendor/fixture-contract.md)

## What this reads, and the permission to read it

**Invoking this skill is the explicit grant the read-scope clause of
[references/vendor/fixture-contract.md](references/vendor/fixture-contract.md) requires.**
That clause bounds an instrument to its own directory, the tree it audits, and the area it
writes to, and demands a grant stated in the invocation before it reads anything else the
executing user has on the machine.

The grant is exactly this and nothing wider:

- **The project's own instruction files** — the audited project's `CLAUDE.md`, `AGENTS.md`
  and `PROJECT.md`, and the Markdown in its `.claude/rules/` and `rules/` directories.
- **One project's memory** — the memory directory belonging to the project the audit was
  pointed at, found under the operator's home or under the directory given as `--home`.
  **One project's.** Reading across projects is not supported, and no argument enables it.
- **The installation-wide instruction file and rules directory**, under that same home, and
  only when `--include-global` is given.

Nothing else on the machine is read. The memory directory is derived from the working
directory and then verified to sit where it should before anything is opened; where that
check does not hold it is skipped unread rather than guessed at. The derivation, its failure
modes, and the constraints on what may leave a memory are in
[references/memory-audit.md](references/memory-audit.md).

### What this writes

Three places, and nowhere else:

- **`.agents/tmp/context-audit/` under the audited project** — every artefact a run
  produces: the collected targets, the findings, the report.
- **`.agents/config/context-audit-baseline.json` under the audited project** — only when
  a baseline was asked for.
- **The file an automatic fix names**, and only under `apply_fixes.py --write`. This is
  the one write that can land outside the audited project: a fix against a memory writes
  that memory back, and a memory sits under the operator's home rather than in the
  project. **It is never a file outside the read scope above** — a fix names the file the
  finding came out of and no other. Nothing here creates a file or deletes one; a fix is
  a path corrected inside a line, or a frontmatter key put into canonical form with the
  body's bytes unchanged. It runs only after the change has been shown and confirmed,
  and not at all when there is nobody to ask.

## Arguments

- **No argument** — audit the project's instruction files and the memory belonging to it.
- **`--include-global`** — also audit the installation-wide instruction file and rules
  directory. A deliberate widening of what is read, never a default. **The checks that ask
  something of the audited project's tree pass over these files**: whether a path is there,
  whether a skill directory is there, and whether a skill is written down are all questions
  about a tree these files do not belong to.
- **`--update-baseline`** — fix the current findings as the baseline, so later runs present
  only what is new. It is an argument of `aggregate_report.py`, which **writes the baseline
  and stops**: that run produces no report. See
  [references/baseline-format.md](references/baseline-format.md).
- **`--interactive {ts}`** — resume the decisions the run with that timestamp left
  undecided. The timestamp is **required and is the one in that run's file names** under
  `.agents/tmp/context-audit/`: every run writes under a name of its own, so there is no
  "the previous run" for the argument to mean. No script implements this; it is a phase of
  the workflow below.

No command is created; being a single workflow, it needs no named entry point.

## Execution contract

- **Script paths.** `{skill_dir}` is the directory this skill is installed in, and the
  scripts are called by absolute path. `{project_root}` is the audited project's root.
- **`{project_root}` is the root of the tree being audited — not necessarily the working
  directory.** It is both the root references are resolved against and the input the memory
  directory is derived from. When the audited tree sits below the working directory — a copy
  handed over for review, one project inside a larger checkout — pass that subdirectory:
  resolving the references against the outer tree checks the wrong files. Memory follows the
  same root, so a tree nobody ever worked in under its own path resolves no memory at all,
  and the run reports that rather than substituting another project's.
- **`{ts}`** is minted once with `date +%Y%m%d-%H%M%S` and reused across the phases, so a run
  never overwrites an earlier run's artefacts.
- **Output location.** Every artefact a run produces goes to `.agents/tmp/context-audit/`
  under the audited project. **Create that directory before the first script runs** — no
  script creates it. The baseline is the exception and goes to
  `.agents/config/context-audit-baseline.json`, which is committed while the rest is not.
  An applied fix is not an artefact of the run: it writes back the file the finding came
  out of, under the write scope stated above.
- This is not the placement a skill measuring *another* tree uses. Here the tree under audit
  is the invoking project itself — that is what keeping the root equal to the working
  directory means — so the run's scratch area and the audited tree are the same place, and
  writing outside it would leave one project's artefacts in another. The fixture contract is
  invoked above for its read scope, which does bind this skill.

### When there is nobody to ask

Running headless, or as a subagent, no question has an answer.

- **An explicit instruction from the user outranks everything below.** Where one already
  says which way to go — "take the current state as the baseline" is option (a) of the
  first-run choice — follow it.
- Absent one, **fall to the side that changes no state.** Emit the full report. Do not write
  the baseline. Apply neither the automatic fixes nor the decisions. The report already
  holds both, each finding carrying the fix action it was given, so one waiting on a person
  reads as `NEEDS_JUDGMENT` rather than as one that was only ever informational. **Say in
  the reply that neither was applied**, so the untouched state is stated rather than assumed.

## Workflow

### Phase 0 — Discovery

```bash
mkdir -p .agents/tmp/context-audit
python3 {skill_dir}/scripts/collect_targets.py {project_root} \
  --output .agents/tmp/context-audit/targets-{ts}.json
```

Add `--include-global` when it was asked for, and `--home` when the memory store to read is
not the operator's own.

- The targets come from an allowlist, so an area nobody thought about cannot leak in: the
  project's `CLAUDE.md`, `AGENTS.md` and `PROJECT.md`, the Markdown of `.claude/rules/` and
  `rules/`, and the project's memory. Copies nested deeper in the tree, and archival areas
  such as `.agents/artifacts/`, sit outside it.
- A target that is not there is a normal state: it is recorded among `skipped` and the run
  carries on. So is a file that cannot be read or decoded — one of them never ends the run.
- **Read `memory_dir` in the output before going on.** It says which memory directory was
  opened, or that none was. A run that resolved none audits the instruction files only, and
  the report has to say so.
- **Check whether the baseline file exists**, and where it does not, present the first-run
  choice below.

#### The first run

A project audited for the first time has no baseline, so every finding it has accumulated
since it began arrives at once. Do not simply hand that over. Ask which of three:

- **(a) Take the current state as the baseline**, and report only what appears after it.
- **(b) Triage** — go on reporting from one severity upward, and baseline everything under
  it.
- **(c) The full report**, with no baseline written.

**The answer is acted on in Phase 3, not here.** A baseline is written over findings and
there are none until Phase 1 has run, so what (a) and (b) amount to is one extra invocation
ahead of the Phase 3 report, over that same findings file:

```bash
# (a) — every current finding goes into the baseline
python3 {skill_dir}/scripts/aggregate_report.py \
  .agents/tmp/context-audit/findings-{ts}.json \
  --update-baseline .agents/config/context-audit-baseline.json

# (b) — only what is less grave than the named severity does, and the rest keeps reporting
python3 {skill_dir}/scripts/aggregate_report.py \
  .agents/tmp/context-audit/findings-{ts}.json \
  --update-baseline .agents/config/context-audit-baseline.json \
  --baseline-below WARN
```

Given `--update-baseline` the script writes the baseline and stops, producing no report of
its own; Phase 3 then runs as written and suppresses against what was just fixed. Under (c)
neither invocation happens.

### Phase 1 — Static checks

```bash
python3 {skill_dir}/scripts/static_checks.py \
  .agents/tmp/context-audit/targets-{ts}.json --root {project_root} \
  --output .agents/tmp/context-audit/findings-{ts}.json
```

- Every rule in the registry runs in one pass. The rules are defined in
  [references/rule-catalog.md](references/rule-catalog.md); which one fired, how serious it
  is, and whether its fix may be automated are decided here and **nowhere else in this
  workflow**.
- Every finding carries `id`, `severity`, `action`, `where`, `what`, `why`, `how` and
  `fix_action`, and the credential mask runs over the text of every one of them before they
  are written out.

### Phase 2 — The classification only a reading can make

CA-C001 extracts pairs of claims pointing opposite ways about one subject. The extraction is
deliberately generous — it would rather offer a pair that turns out to be fine than miss a
real conflict — and deciding which a pair is, is this phase.

Classify each candidate as **a real contradiction**, **a deliberate difference**, **already
settled by one file taking precedence over the other**, or **undecidable**. Record the
classification. **Change nothing**: this phase produces a reading, not an edit.

- **With no candidates, skip the phase entirely.** There is nothing to read.
- **What goes into the reading is the finding's own `what` and nothing else** — already
  masked, already cut down to the two claims. The `where` that names the two files stays
  out of it, along with the content around those lines and anything identifying a person.
  (`where` is for the report and for Phase 4's presentation, not for this reading.)
- **A claim taken from a memory arrives without its line.** All the `what` carries for
  that side is which way it points and how far the two overlap: a memory holds the
  vocabulary of the work — a customer's name, an internal hostname — and the mask knows
  neither shape. Where that leaves a pair genuinely unreadable, **undecidable** is the
  classification; do not go to the file for the line.

### Phase 3 — Aggregate

```bash
python3 {skill_dir}/scripts/aggregate_report.py \
  .agents/tmp/context-audit/findings-{ts}.json \
  --targets .agents/tmp/context-audit/targets-{ts}.json \
  --baseline .agents/config/context-audit-baseline.json \
  --markdown \
  --output .agents/tmp/context-audit/report-{ts}.md
```

- **`--targets` is not optional.** It carries two things no rule produces: the memory
  directory that was actually read, and the targets the collection passed over. Without it
  the report can state neither, and a file nobody opened passes for one that came back
  clean.
- **The checks that ran come out of the findings file**, which names them, and the report
  repeats them. That is what separates a count of zero from a check that never happened.
- **The report states that the mask is a blocklist** and so incomplete, alongside the
  masked text it hands onward.
- Suppression, the counts and the ordering are the script's. It carries each finding's fix
  action through untouched — recomputing it here would produce a second opinion with no way
  of saying afterwards which one the report shows.
- A suppressed finding appears in the count. Never drop one quietly.
- **The report names a fix without carrying its text.** The line an automatic fix replaces
  stays in the findings file, which is what Phase 4 applies from; a report is written to be
  handed to another person and has no use for it.
- Drop `--markdown` for the structured form, which carries the same report as JSON.

### Phase 4 — Apply, decide, report

**Automatic fixes.** Show them, then apply them together:

```bash
python3 {skill_dir}/scripts/apply_fixes.py \
  .agents/tmp/context-audit/findings-{ts}.json
python3 {skill_dir}/scripts/apply_fixes.py \
  .agents/tmp/context-audit/findings-{ts}.json --write
```

The first form changes nothing and says how many files would change. That count, and the
difference each fix makes, is what the confirmation is asked over. Only `--write` edits
anything.

**Decisions.** Take them **in the order the report lists them** — gravest first, then by
rule identifier, then by place. That order is the aggregate script's rather than one you
choose, and fixing it is what lets a capped run be resumed. Offer the run of findings a
single rule holds as a group ("apply these path corrections together / go through them one
at a time / skip them").

**Cap the decisions at ten per run.** Past that, stop asking: a person asked thirty
questions in a row stops reading them, and an answer given that way is worse than no answer
at all. Nothing has to be added to the report for the remainder — Phase 3 wrote every
finding out, answered or not, and the ones you did not reach are sitting in it under
`NEEDS_JUDGMENT`. **State the deferred count when you close the phase, in the reply**: the
report file was written before the first question was asked, so it cannot carry a number
that only exists afterwards.

**Resuming.** `--interactive {ts}` picks the deferred decisions back up. Read
`.agents/tmp/context-audit/findings-{ts}.json` and the report written beside it, and take
that run's `NEEDS_JUDGMENT` findings in the order above. **Nothing records how many of them
a person was already shown.** The order is fixed and the cap is ten, so a run that was
putting questions stopped ten in — but a run with nobody to ask put none, and no artefact
tells those two apart. Ask which it was; where there is nobody to ask, start from the
beginning of the order, because putting a decided finding again costs a repeated question
while skipping one nobody saw loses it in silence. **Do not re-run Phases 0 through 3.**
Re-running them would re-derive findings against a tree the earlier decisions have since
changed, and the answers already given would be answers to a different set. When the files
that run wrote are gone, say so and start a fresh run rather than reconstructing them.

**Reported findings.** Present what, why and how together. For a contradiction, put both
locations side by side with the classification Phase 2 gave it.

## Critical rules

- **Deleting anything, and rewriting what a body says, are never automated** — by any route,
  at any severity. An automatic fix is only ever a path correction whose candidate is
  unique, or a frontmatter line normalised with the body's bytes unchanged. In doubt, fall
  to a decision, and from there to a report.
- **A run is bounded to one project's memory.** Widening it is the incident the scope exists
  to prevent.
- **A suspected secret is never transcribed and never masked in place.** What travels is the
  kind and the place. Masking the value inside the file would hide the leak without revoking
  it.
- **The mask is a blocklist and therefore incomplete.** A credential shaped unlike anything
  it knows passes through it. Say so wherever masked text is handed onward, the report
  included.
- **The report says what was actually read** — the memory directory by its absolute path,
  the targets that were skipped, and the number suppressed. A file nobody read cannot be
  reported as clean.
- **Where no rule fired, report that no rule fired.** Do not manufacture something to show.

## Completion conditions

- Phases 0 through 3 have run, and Phase 4 has disposed of every finding: applied, decided,
  deferred with the deferred count stated in the reply, or reported.
- The report exists, leads with its counts, and names the memory directory that was read.
- The baseline was written exactly when it was asked for, and not otherwise.
- The report names the checks that ran, the findings they produced, and the targets that
  were passed over unchecked. All three come out of the scripts, so a report missing one is
  a run that dropped an argument rather than a project with nothing to say. A completion
  claim standing on anything but a command run in this session and its output is not a
  completion claim.

## Handling failures

- **A script fails to run**: report the error and carry on to the next phase with whatever
  was collected. Partial findings are worth more than none.
- **A target cannot be read or decoded**: `collect_targets.py` records it among the skipped.
  Repeat that in the report.
- **The memory directory does not resolve**: audit the instruction files, and say in the
  report that no memory was read.
- **Every phase fails**: emit an error report holding whatever could be collected.

## Tests

The scripts' pure functions are covered by the suites sitting beside them:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest {skill_dir}/scripts -q
```

`test_catalog_sync.py` is the one worth naming: it holds
[references/rule-catalog.md](references/rule-catalog.md) against the registry in
`static_checks.py`, so the two statements of what a rule is cannot drift apart unnoticed.
