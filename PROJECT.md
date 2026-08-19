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
hash in `bun.lock`. The ported skills carry Python scripts with test suites of their own,
run through `uv`, which fetches pytest per run and needs no Python project here. Bun and uv
are therefore the toolchains the checks themselves need; lefthook, which runs them ahead of
a push, is installed separately per clone.

The distributed plugin's version lives in exactly one canonical place: the `version` field of
`.claude-plugin/plugin.json`. The copy in `.claude-plugin/marketplace.json` is a follower of
that value, never a second source of it.

| Path | What it holds |
|---|---|
| `skills/` | The skills themselves, one directory each. A skill is self-contained: the contracts it declares are expanded under its own `references/vendor/`, and its Python scripts sit beside their tests in `scripts/` |
| `contracts/` | The output-contract conventions (`contracts/README.md`) and the canonical text of each contract: `fixture-contract`, `severity-and-verdicts`, `fix-action-taxonomy` |
| `vendor-lock.json` | Which contract text each skill has currently adopted. Derived — the tool's `gen` rewrites it from the canonical text; it is never edited by hand |
| `fixtures/` | Synthetic skill trees the machinery runs against; `skillset-alpha` and `skillset-beta` differ in structure, vocabulary and log format on purpose |
| `.claude-plugin/` | Distribution metadata: `plugin.json`, which declares the canonical version, and `marketplace.json`, which follows it |
| `docs/spec/` | Design decisions (Japanese) |
| `package.json`, `bun.lock` | The vendoring tool's version pin |
| `.github/workflows/ci.yml` | CI: frozen install, the tool's self-test, then `verify` + `lint-selfcontain` over both fixture trees and the repository root, the plugin version check, and the skills' script suites |
| `lefthook.yml` | Local pre-push gates mirroring CI (activated per clone with `lefthook install`) |

## Commands

| Purpose | Command |
|---|---|
| Install the pinned toolchain | `bun install --frozen-lockfile` |
| Check the tool against its own vectors | `bun ./node_modules/.bin/agentic-skill-vendor self-test` |
| Verify vendored copies | `bun ./node_modules/.bin/agentic-skill-vendor verify --root <tree>` |
| Regenerate vendored copies | `bun ./node_modules/.bin/agentic-skill-vendor gen --root <tree>` |
| Self-containment lint | `bun ./node_modules/.bin/agentic-skill-vendor lint-selfcontain --root <tree>` |
| Run the skills' script suites | `PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest skills -q` |
| Check the plugin version declarations agree | `test "$(jq -r .version .claude-plugin/plugin.json)" = "$(jq -r '.plugins[0].version' .claude-plugin/marketplace.json)"` |
| Enable pre-push hooks (once per clone) | `lefthook install` |

`<tree>` is `.` for this repository itself as well as either fixture tree. Run the lint before
the script suites, never after: the lint reads the working tree rather than the index, and the
`.pyc` files pytest leaves under `skills/*/scripts/__pycache__/` are reported as absolute-path
violations. `PYTHONDONTWRITEBYTECODE=1` belongs to the documented command for the same reason —
it leaves a tree that has run the suites still lintable.

The tool is invoked by its installed path, not as `bunx agentic-skill-vendor`: with no local
install, bunx fetches the unscoped registry name `agentic-skill-vendor`, which is a different
package from the pinned `@ba0918-dev/agentic-skill-vendor`. A path can only ever run the
pinned install, and says so plainly when that install is missing.

## Conventions specific to this project

- Language: `docs/spec/` is written in Japanese; everything else — skill bodies included — is
  written in English (skills stay English to conserve tokens).

## Constraints

Compatibility requirements, performance budgets, regulatory limits, and anything that makes an
obvious approach wrong here.

## Glossary

Domain terms whose meaning in this project differs from ordinary usage.
