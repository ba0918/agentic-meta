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

## Install

Three kinds of route are supported — plugin, package manager and copy. They differ in how
updates reach you, not in what you get. Claude Code, Codex CLI and OpenCode install by the
plugin route, each from metadata already in this repository; APM installs by the
package-manager route; `gh skill` and `npx skills` install by the copy route.

### Claude Code (plugin marketplace)

Updates arrive when the plugin's version is bumped. An installed copy follows the version
declared in the marketplace entry rather than the latest commit, so a change that leaves
the version untouched does not reach it.

```
/plugin marketplace add ba0918/agentic-meta
/plugin install ba0918-meta@agentic-meta
```

### Codex CLI (plugin marketplace)

Codex reads the same `.claude-plugin/marketplace.json`, and the skills appear to the model
under the plugin name, as `ba0918-meta:ba0918-trigger-eval` and so on.

```
codex plugin marketplace add ba0918/agentic-meta
codex plugin add ba0918-meta@agentic-meta
```

### OpenCode (plugin)

Add the repository to `plugin` in `opencode.json` — either the project's or the global
`~/.config/opencode/opencode.json` — and restart OpenCode. The bundled entry registers
`skills/` and does nothing else.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["agentic-meta@git+https://github.com/ba0918/agentic-meta.git"]
}
```

`package.json` exists to make this repository installable by that route. It is a
distribution manifest, not a published npm package — `private: true` keeps it off the
registry.

### APM (package manager)

[APM](https://github.com/microsoft/apm) manages skills for several AI agents from one
manifest: installing adds a dependency line to the project's `apm.yml`, `apm.lock.yaml`
pins the resolved commit, and `apm update` moves it forward.

```
apm install ba0918/agentic-meta --target claude
apm install -g ba0918/agentic-meta
```

The first form installs into the project; the second into the user scope under `~/.apm/`.
This repository carries no APM-specific file: APM resolves a repository holding
`.claude-plugin/plugin.json` as a plugin collection and finds `skills/` through it. APM
warns when a dependency is unpinned — pin a release tag (`ba0918/agentic-meta#v{version}`)
or a commit SHA.

### Copy (`gh skill` / `npx skills`)

Skills are copied into the project at install time, and updates are pulled by running the
command again. Naming one skill installs that skill alone:

```
gh skill install ba0918/agentic-meta ba0918-trigger-eval --agent claude-code
npx skills add ba0918/agentic-meta --skill ba0918-trigger-eval
```

Both commands can also take the whole repository, and both resolve to the same two skills
that the plugin route installs. What they must not be given is an option that widens
discovery past its default — `gh skill --allow-hidden-dirs` or `npx skills --full-depth`.
The synthetic trees under `.fixtures/` exist to be measured, not installed: they carry
skills that violate the Agent Skills naming rules on purpose, so a regression in the
instruments shows up as those violations going unreported.

The contracts a skill depends on are canonical in `contracts/`, declared by id in the
skill's frontmatter, and expanded into that skill by `@ba0918-dev/agentic-skill-vendor`
— an external tool held as a dev dependency and pinned by the lockfile. CI installs that
pin, checks the tool against its own vectors, then has it verify the vendored copies and
lint every skill directory for self-containment, across the repository root and the
synthetic skill trees under `.fixtures/`, and runs the skills' Python script suites. See
`PROJECT.md` for commands and layout, and `ROADMAP.md` for progress.
