# agentic-meta

Skills that build and evaluate agent capability itself, packaged as
[Agent Skills](https://agentskills.io).

This repository is one of three produced by splitting the overgrown `claude-skills`
collection by responsibility:

- [agentic-rules](https://github.com/ba0918/agentic-rules) — near-invariant norms an agent
  obeys while working
- agentic-workflow — how work is carried out
- **agentic-meta** (this repository) — building and evaluating agent capability itself

Skills arrive here as the split of `claude-skills` proceeds. No skills are ported yet;
what exists today is the foundation they will stand on: an output-contract protocol
(`contracts/README.md`) and `scripts/vendor.py`, the single CLI that generates and
verifies per-skill vendored contract copies (`gen` / `verify`) and lints every skill
directory for self-containment (`lint-selfcontain`) — exercised in CI by a pytest
suite against synthetic fixture trees under `fixtures/`. See `PROJECT.md` for
commands and layout, and `ROADMAP.md` for progress.
