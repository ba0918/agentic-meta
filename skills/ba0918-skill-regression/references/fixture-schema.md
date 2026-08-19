# The scenario schema, and how to design one

One scenario is one file under `evals/cases/<skill>/`. It declares a situation to hand
the skill and the expectations its result must satisfy, plus every premise the run
depends on. Reading it is `fixture_setup.py`, and `--validate` checks it without
materialising anything.

The format is the block subset described in `yaml_subset.py`: mappings, sequences,
literal blocks, and plain or quoted scalars. Anything outside it is refused with a line
number rather than read approximately.

## Shape

```yaml
skill: acme-config                    # required — the skill under test
id: ac-001                            # required — unique within the skill
title: The settings migration keeps the documentation in step
source: empirical-tuning:20260819     # where the criteria came from
executor_tier: standard               # standard (default) | high | economy
isolation: worktree                   # worktree (default) | none

files:                                # staged into the isolated area
  - project/config.ini                # a path under evals/inputs/<skill>/
  - from: project/README.after.md     # a different source for a later state
    to: project/README.md
mtimes:                               # whole seconds from the run's base time
  project/config.ini: -7200
env:                                  # passed through to the executor
  TZ: UTC
git:
  init: true
  commit: true                        # true, or a list of staged paths
  message: baseline
  commits:                            # commits stacked after the baseline
    - files: [{from: project/README.after.md, to: project/README.md}]
      message: point the documentation at the new file

exercises:                            # which surface files this scenario touches
  - skills/acme-config/references/migration.md

prompt: |
  The settings file is moving from INI to TOML.
  Convert it and keep the documentation in step.
expected_output: |
  A converted settings file plus documentation that names it.
expectations:
  - text: A TOML settings file exists and carries the same values
    critical: true
  - text: The README no longer names the INI file
    critical: true
  - text: The conversion is explained in the commit message
    critical: false
```

`id`, `prompt`, `expected_output`, `files` and `expectations` carry the names Anthropic's
skill-creator uses for the same things, so a reader who knows that format reads most of
this one. `expectations[].critical`, `exercises`, `executor_tier`, `isolation`, `mtimes`,
`env` and `git` are this harness's own additions — the file is not a drop-in for a
skill-creator runner.

An unknown key is refused rather than ignored. A declaration silently dropped is the
worst failure available here: the premise its author meant to pin gets filled in at run
time by whoever runs it.

## Input files

`files` names paths under `evals/inputs/<skill>/`, and their contents live there as
ordinary files. Contents are not embedded in the scenario: embedding them is what made
the format this replaces unreadable, and a real file is what makes a change to an input
show up as a diff anyone can review.

The `from` / `to` form exists for a scenario that needs two states of one path — a
baseline and the version a later commit introduces.

Paths must stay inside the isolated area, and none may name `.git`; materialising into
git's own metadata would let a hook reach outside the isolation on its own.

## Seeded history

A scenario can start after the baseline: `git.commits` stacks further commits, so a
scenario measuring a later phase does not have to re-run the earlier ones. A document
that must name the baseline writes `{{fixture:sha:baseline}}` or
`{{fixture:sha:commits[0]}}`, substituted once every commit exists. An unknown
placeholder stops the run; left in place it would send the run down a "cannot resolve
the sha" path instead of the one under test.

Commit times are fixed, not taken from the clock, so a seeded scenario stays
reproducible — rerunning re-materialises it and demands a byte-for-byte match.

## Designing one

1. **Two or three scenarios.** One at the median of real usage plus one or two edges.
   One overfits; four or more do not pay for what a run costs.
2. **Write expectations in observable form.** Not "works correctly" but "the three-valued
   verdict appears in the output" — at a granularity where the artifact settles it.
3. **Reserve `critical` for what the skill exists to do.** Marking everything critical
   means nothing is, and the regression loses its resolution.
4. **Fix them before the run.** Expectations settled during capture are not moved after
   seeing a result. They move only when the skill's specification deliberately changed,
   and then the scenario is redone from capture with `source` updated.
5. **Never edit toward an easier scenario.** Simplifying the prompt or dropping a
   critical because it failed hides the regression. Separating the cause — a regression
   in the skill, or a specification that changed — comes first.
6. **No secrets.** Scenarios are committed. No real credentials, internal hostnames, or
   personal data in a prompt or an input file.

## When a declaration and reality diverge

Some runtimes overlay a device file onto sensitive-looking names such as `.env`, and the
write is silently discarded. `--materialize` reports those paths as `unmaterialized`.
A scenario must not rest an expectation on the contents of such a file — one judged by
name or kind still holds — and the divergence belongs in the run's report.
