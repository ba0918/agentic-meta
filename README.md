# agentic-meta

Skills that measure a skill set. They answer two questions an author cannot answer by
reading their own work: does each skill fire when it should, and does each `SKILL.md`
say enough to be executed correctly?

- **`ba0918-trigger-eval`** measures how accurately a set of skills fires. It judges from
  the descriptions alone — the model's field of view at real triggering time — and reports
  recall, precision, stability and a confusion matrix, names the pairs that collide, then
  runs the rewrite-and-re-evaluate loop until the numbers stop moving.
- **`ba0918-skill-interface-audit`** audits each `SKILL.md` statically, as an API
  specification. It reports what the contract leaves out: undeclared side effects,
  completion conditions that cannot be verified, undefined failure handling. Every finding
  carries a patch candidate, and none is ever applied automatically.

Both take any skill directory as their target, not only this repository's.

## Install

Three kinds of route are supported — plugin, package manager and copy. They differ in how
updates reach you, not in what you get.

### Claude Code (plugin marketplace)

An installed copy follows the version declared in the marketplace entry rather than the
latest commit, so an update reaches you when the version is bumped.

```
/plugin marketplace add ba0918/agentic-meta
/plugin install ba0918-meta@agentic-meta
```

### Codex CLI (plugin marketplace)

Codex reads the same marketplace entry, and the skills appear to the model under the
plugin name, as `ba0918-meta:ba0918-trigger-eval` and so on.

```
codex plugin marketplace add ba0918/agentic-meta
codex plugin add ba0918-meta@agentic-meta
```

### OpenCode (plugin)

Add the repository to `plugin` in `opencode.json` — either the project's or the global
`~/.config/opencode/opencode.json` — and restart OpenCode.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["agentic-meta@git+https://github.com/ba0918/agentic-meta.git"]
}
```

This route reads `package.json`, which is here as a distribution manifest rather than a
published package: `private: true` keeps it off the npm registry, so the git URL above is
the only way in.

### APM (package manager)

[APM](https://github.com/microsoft/apm) manages skills for several AI agents from one
manifest: installing adds a dependency line to the project's `apm.yml`, `apm.lock.yaml`
pins the resolved commit, and `apm update` moves it forward.

```
apm install ba0918/agentic-meta --target claude
apm install -g ba0918/agentic-meta
```

The first form installs into the project, the second into the user scope under `~/.apm/`.
APM warns when a dependency is unpinned — pin a release tag
(`ba0918/agentic-meta#v{version}`) or a commit SHA.

### Copy (`gh skill` / `npx skills`)

Skills are copied into the project at install time, and updates are pulled by running the
command again. Naming one skill installs that skill alone; naming the repository installs
both. Each command places them where its agent setting points: `gh skill` asks which agent
when none is named, while `npx skills` defaults to the shared `.agents/skills/`.

```
gh skill install ba0918/agentic-meta ba0918-trigger-eval --agent claude-code
npx skills add ba0918/agentic-meta --skill ba0918-trigger-eval
```

One caveat specific to this route: do not pass an option that widens discovery past its
default (`gh skill --allow-hidden-dirs`, `npx skills --full-depth`). This repository keeps
deliberately malformed skills under `.fixtures/` as test material for the two instruments,
and a widened search installs those alongside the real ones.

## License

MIT. See `LICENSE`.

Contributing: `PROJECT.md` covers the layout and the commands, `ROADMAP.md` the progress.
