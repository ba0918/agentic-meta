# agentic-meta

Skills that build and evaluate agent capability itself, packaged as
[Agent Skills](https://agentskills.io).

This repository is one of three produced by splitting the overgrown `claude-skills`
collection by responsibility:

- [agentic-rules](https://github.com/ba0918/agentic-rules) — near-invariant norms an agent
  obeys while working
- agentic-workflow — how work is carried out
- **agentic-meta** (this repository) — building and evaluating agent capability itself

Two skills are ported so far, and they install together as the plugin `ba0918-meta`:
`ba0918-trigger-eval` measures how accurately a skill set's descriptions fire, and
`ba0918-skill-interface-audit` audits each `SKILL.md` statically as an API
specification. More arrive as the split of `claude-skills` proceeds.

The contracts a skill depends on are canonical in `contracts/`, declared by id in the
skill's frontmatter, and expanded into that skill by `@ba0918-dev/agentic-skill-vendor`
— an external tool held as a dev dependency and pinned by the lockfile. CI installs that
pin, checks the tool against its own vectors, then has it verify the vendored copies and
lint every skill directory for self-containment, across the repository root and the
synthetic skill trees under `fixtures/`, and runs the skills' Python script suites. See
`PROJECT.md` for commands and layout, and `ROADMAP.md` for progress.
