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
`.claude-plugin/plugin.json`. `.claude-plugin/marketplace.json` and `package.json` repeat it
for the routes that read them; both are followers, never a second source of the value.

| Path | What it holds |
|---|---|
| `skills/` | The skills themselves, one directory each. A skill is self-contained: the contracts it declares are expanded under its own `references/vendor/`, and its Python scripts sit beside their tests in `scripts/` |
| `contracts/` | The output-contract conventions (`contracts/README.md`) and the canonical text of each contract: `fixture-contract`, `severity-and-verdicts`, `fix-action-taxonomy` |
| `evals/` | Measurement assets for the skills here: `cases/<skill>/` holds one scenario per file and `inputs/<skill>/` the files a scenario stages. Outside `skills/`, so they are committed but never shipped to anyone installing a skill |
| `regression-lock.json` | What `ba0918-skill-regression` last verified, and against which content. A lock file at the root, like `vendor-lock.json` beside it |
| `vendor-lock.json` | Which contract text each skill has currently adopted. Derived — the tool's `gen` rewrites it from the canonical text; it is never edited by hand |
| `.claude-plugin/` | Distribution metadata: `plugin.json`, which declares the canonical version, and `marketplace.json`, which follows it |
| `.opencode/` | The OpenCode route's plugin entry. It registers `skills/` with the runtime and does nothing else |
| `docs/spec/` | Design decisions (Japanese) |
| `package.json`, `bun.lock` | The vendoring tool's version pin, the OpenCode route's entry declaration (`main`, `files`), and one of the two version followers |
| `.github/workflows/ci.yml` | CI: frozen install, the tool's self-test, then `verify` + `lint-selfcontain` over the repository root, the version-declaration check, the Agent Skills specification validation, and the skills' script suites |
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
| Validate the distributable skills | `gh skill publish . --dry-run` |
| Check the version declarations agree | `c=$(jq -r .version .claude-plugin/plugin.json); test "$c" = "$(jq -r '.plugins[0].version' .claude-plugin/marketplace.json)" && test "$c" = "$(jq -r .version package.json)"` |
| Enable pre-push hooks (once per clone) | `lefthook install` |

`<tree>` is `.` — this repository is the only tree the tool is pointed at. Run the lint before
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
  written in English (skills stay English to conserve tokens). The exception is test data
  whose content is itself what the test exercises: a CJK string handed to a tokenizer, or a
  non-English `SKILL.md` an audit rule has to read. That data keeps its own language,
  because translating it deletes the coverage it exists for. The comments and docstrings
  around it are English like everything else.
- Placement of measurement assets: nothing that measures a skill is written inside that
  skill's directory. Scenarios and their input files live under `evals/`, and the
  verification record is a lock at the repository root. Two things follow from the
  placement rather than from anyone's care: a scenario cannot make its own skill look
  unverified by being edited, and the copy routes, which search `skills/` and nothing else,
  never ship test material to someone who only wanted the skill. Facts about the
  environment a measurement ran in — what it cost, whether a judging model passed
  calibration — are not committed at all, since the repository is cloned into other
  environments where they would not hold.
- Reading a session history: a skill here may need the record of how an agent actually
  behaved, which lives outside any tree it measures. The read-scope clause of
  `fixture-contract` allows that only on an explicit grant stated in the invocation, so such
  a skill names in its own `SKILL.md` exactly which stores it reads and takes each location
  as a parameter. Two things follow. Where a store's records cannot show something — a
  runtime that keeps no record of a skill firing, say — the skill declares that it cannot,
  and the declaration travels into the report beside the numbers. And it never fills the gap
  by inference: a friction score built on invented firings recommends fixing a skill nobody
  ran, which is worse than a report saying the route could not be read.
  `ba0918-skill-improve` and `ba0918-context-audit` are the current cases — one reads an
  agent's session history, the other a project's memory — and the reasoning is in
  `docs/spec/`.
- Licensing: the repository is MIT and `LICENSE` at the root covers it. A skill derived from
  someone else's work carries an additional `LICENSE` in its own directory, holding that
  author's copyright notice — MIT requires the notice to travel with every copy, and a skill
  directory is what the copy routes install. `ba0918-empirical-prompt-tuning` is the current
  case. Check for a per-skill licence before porting anything else.

## Constraints

Compatibility requirements, performance budgets, regulatory limits, and anything that makes an
obvious approach wrong here.

## Glossary

Domain terms whose meaning in this project differs from ordinary usage.
