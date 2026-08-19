# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
