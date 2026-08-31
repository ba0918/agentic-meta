# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `ba0918-skill-regression` — a skill that reads another skill by name, not by path, can
  be declared on the evaluation side (`evals/dependencies.yml`), and the declared skill's
  files then join the reader's behaviour surface. Editing a skill that others read by name
  no longer leaves their locks green. The declaration lives outside the skill because it
  exists for the measurement; a name on either side matching no skill, or a declaration
  file that cannot be read, stops the computation.

## [0.2.0] - 2026-08-23

### Added

- `ba0918-skill-token-efficiency-audit` — audits a named skill for token amplification,
  quality trade-offs, and validation needed before adopting a cheaper path, while leaving
  the target unchanged and inventing no unmeasured savings.

## [0.1.0] - 2026-08-20

### Added

- `ba0918-trigger-eval` — measures how accurately a skill set's descriptions fire. It judges
  from the descriptions alone, reports recall, precision, stability and a confusion matrix,
  names the colliding pairs, and runs the rewrite-then-re-evaluate loop to convergence. The
  target is any skill directory, not only this repository's.
- `ba0918-skill-interface-audit` — audits each `SKILL.md` statically as an API specification
  and reports what its contract leaves out: undeclared side effects, completion conditions
  that cannot be verified, undefined failure handling, and structural violations. Every
  finding carries a patch candidate, and none is ever applied automatically.
- `ba0918-empirical-prompt-tuning` — measures and improves the text instructions written for
  agents. It runs the instruction under a 3-role separation, where the role that executes the
  work never sees the pass criteria and the role that grades it never sees the instruction,
  classifies where the executor got stuck against a fixed taxonomy, and repeats until the
  convergence functions say improvement has plateaued. The verdict is computed, never judged
  by whoever is doing the tuning. It carries its own `LICENSE`: the skill derives from
  github.com/mizchi/skills and the original copyright notice travels with it.
- `ba0918-skill-regression` — a regression harness for skills. It keeps the pass criteria a
  skill was tuned against as scenario files beside the repository, and when a `SKILL.md` or a
  shared contract changes it re-runs only the scenarios that change actually reaches. A lock
  at the repository root records what was verified against which content, so editing one
  shared contract can no longer silently change the behaviour of every skill citing it.
  Every batch is sized before it starts and stops after the first scenario it has no
  measurement for, and a record going stale asks for a recorded judgment rather than a
  rerun.
- `ba0918-skill-improve` — reads the session logs an agent already left behind and scores
  each skill by the traces of being used badly: the same skill invoked again moments later,
  a request restated right after an invocation, a tool call that failed. Reading is split
  from analysis, so one measurement covers three runtime stores whose storage has nothing in
  common — Claude Code's per-project JSONL, an OpenCode SQLite database, and Codex CLI
  rollout logs. Each store declares which detection routes it can be read along, and a route
  it cannot be read along is reported as undetectable instead of being filled in with an
  inference: Codex has no record of a skill firing at all, so a skill seen only through it
  carries a lowered confidence rather than a repaired count. The skill measures and
  recommends; carrying the improvement out is deliberately not its job. Its masked prompt
  harvest is the only source of real-data seeds for `ba0918-trigger-eval`.
- `ba0918-context-audit` — takes stock of the files that instruct an agent, judged as
  instructions: `CLAUDE.md`, `AGENTS.md`, `PROJECT.md`, the rules directories, and the
  project memory carried from one session into the next. Nine deterministic rules make a
  single pass and report where a reference points at a file that is gone, where one line
  forbids what the next permits, where wording waives the confirmation before something
  destructive, where one runtime's tool vocabulary has leaked into a file meant to hold for
  any of them, and where a memory keeps a value nobody meant to keep. Every finding carries
  how it may be fixed, and the three answers stay apart: a path correction with a single
  candidate is automatic, a choice between candidates goes to a person, and a contradiction
  or a suspected credential is only ever reported. Deleting anything, and rewriting what a
  body says, are automated by no route at any severity. Whether a pair of opposing lines is
  a real contradiction is the one judgment a rule is not entitled to make, so the extraction
  is deliberately generous and the reading is done apart from it — a reading, never an edit.
  A suspected credential is never transcribed and never masked in place, since masking a
  live value hides the leak without revoking it, and the baseline that suppresses findings
  already accepted holds opaque identifiers and nothing else, which is what makes it safe to
  commit. The memory it reads is one project's, taken as an argument rather than built out
  of the home directory, and the directory actually opened is named in the report.
- The contracts these skills are bound to, canonical in `contracts/` and expanded into each
  skill that declares one: `fixture-contract` (how an instrument finds skills in a tree it
  did not write, what it may read while doing so, and where it may write its output),
  `severity-and-verdicts` and `fix-action-taxonomy` (the vocabulary a finding is reported
  in). An instrument bound to `fixture-contract` reads its own directory, the tree it
  measures and its own output area — anything else takes an explicit grant from the run
  that invoked it.
- `.claude-plugin/` metadata, which installs the skills together as the plugin
  `ba0918-meta`.

Where a skill needs something this repository does not carry yet — a sibling skill still
unported, or a verification entry point a target repository may not have — it says what is
missing and continues in a reduced form instead of failing.

[Unreleased]: https://github.com/ba0918/agentic-meta/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/ba0918/agentic-meta/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/ba0918/agentic-meta/releases/tag/v0.1.0
