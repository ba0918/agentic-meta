# Project Context

## What this is

One of three repositories produced by splitting the overgrown `claude-skills` collection by
responsibility. The split assigns each repository one axis: `agentic-rules` holds the
near-invariant norms an agent obeys while working, `agentic-workflow` holds how work is carried
out, and this repository — `agentic-meta` — holds the skills that build and evaluate agent
capability itself. [agentic-rules](https://github.com/ba0918/agentic-rules) already implements
the separation policy and serves as the reference for structure and conventions.

## Stack and layout

Python 3.12, standard library only, tested with pytest (the same shape as agentic-rules).

| Path | What it holds |
|---|---|
| `contracts/` | Canonical output contracts and the protocol spec (`contracts/README.md`) |
| `scripts/vendor.py` | The single CLI: `gen` / `verify` / `lint-selfcontain` |
| `tests/` | pytest suite for the vendor machinery |
| `fixtures/` | Synthetic skill trees the machinery is tested against; `fixtures/contracts-basic/bad-*` are deliberately broken |
| `docs/spec/` | Design decisions (Japanese) |

## Commands

| Purpose | Command |
|---|---|
| Test | `uv run --with pytest -- pytest tests/ -q` |
| Verify vendored copies | `python3 scripts/vendor.py verify --root <tree>` |
| Regenerate vendored copies | `python3 scripts/vendor.py gen --root <tree>` |
| Self-containment lint | `python3 scripts/vendor.py lint-selfcontain --root <tree>` |

## Conventions specific to this project

- Language: `docs/spec/` is written in Japanese; everything else — skill bodies included — is
  written in English (skills stay English to conserve tokens).

## Constraints

Compatibility requirements, performance budgets, regulatory limits, and anything that makes an
obvious approach wrong here.

## Glossary

Domain terms whose meaning in this project differs from ordinary usage.
