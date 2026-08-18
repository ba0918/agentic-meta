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
what exists today is the foundation they will stand on: output contracts under
`contracts/` (see `contracts/README.md`), vendored into each skill that declares them
by `@ba0918-dev/agentic-skill-vendor` — an external tool held as a dev dependency and
pinned by the lockfile. CI installs that pin, checks the tool against its own vectors,
then has it verify the vendored copies and lint every skill directory for
self-containment across the synthetic skill trees under `fixtures/`. See `PROJECT.md`
for commands and layout, and `ROADMAP.md` for progress.
