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
- The contracts both skills are bound to, canonical in `contracts/` and expanded into each
  skill that declares one: `fixture-contract` (how an instrument finds skills in a tree it
  did not write, and where it may write its output), `severity-and-verdicts` and
  `fix-action-taxonomy` (the vocabulary a finding is reported in).
- `.claude-plugin/` metadata, which installs both skills together as the plugin
  `ba0918-meta`.

Where a skill needs something this repository does not carry yet — a sibling skill still
unported, or a verification entry point a target repository may not have — it says what is
missing and continues in a reduced form instead of failing.
