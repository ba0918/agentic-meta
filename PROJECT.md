# Project Context

## What this is

One of three repositories produced by splitting the overgrown `claude-skills` collection by
responsibility. The split assigns each repository one axis: `agentic-rules` holds the
near-invariant norms an agent obeys while working, `agentic-workflow` holds how work is carried
out, and this repository — `agentic-meta` — holds the skills that build and evaluate agent
capability itself. [agentic-rules](https://github.com/ba0918/agentic-rules) already implements
the separation policy and serves as the reference for structure and conventions.

## Stack and layout

No application code lives here. The vendoring machinery is an external tool,
`@ba0918-dev/agentic-skill-vendor`, held as a dev dependency and pinned by the integrity
hash in `bun.lock`. Bun is therefore the only toolchain the repository needs.

| Path | What it holds |
|---|---|
| `contracts/` | Canonical output contracts and the conventions around them (`contracts/README.md`) |
| `fixtures/` | Synthetic skill trees the machinery runs against; `skillset-alpha` and `skillset-beta` differ in structure, vocabulary and log format on purpose |
| `docs/spec/` | Design decisions (Japanese) |
| `package.json`, `bun.lock` | The vendoring tool's version pin |
| `.github/workflows/ci.yml` | CI: frozen install, the tool's self-test, then `verify` + `lint-selfcontain` on both fixture trees |
| `lefthook.yml` | Local pre-push gates mirroring CI (activated per clone with `lefthook install`) |

## Commands

| Purpose | Command |
|---|---|
| Install the pinned toolchain | `bun install --frozen-lockfile` |
| Check the tool against its own vectors | `bunx agentic-skill-vendor self-test` |
| Verify vendored copies | `bunx agentic-skill-vendor verify --root <tree>` |
| Regenerate vendored copies | `bunx agentic-skill-vendor gen --root <tree>` |
| Self-containment lint | `bunx agentic-skill-vendor lint-selfcontain --root <tree>` |
| Enable pre-push hooks (once per clone) | `lefthook install` |

## Conventions specific to this project

- Language: `docs/spec/` is written in Japanese; everything else — skill bodies included — is
  written in English (skills stay English to conserve tokens).

## Constraints

Compatibility requirements, performance budgets, regulatory limits, and anything that makes an
obvious approach wrong here.

## Glossary

Domain terms whose meaning in this project differs from ordinary usage.
