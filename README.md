# agentic-meta

A collection of meta-skills that measure, evaluate and improve other skill sets. They
answer the questions an author cannot answer by reading their own work: does each skill
fire when it should, does each `SKILL.md` say enough to be executed correctly, do the
instructions survive contact with an agent, does a skill still behave the way it did
before the last edit, can its token cost be reduced without hiding quality loss, how did a
skill actually go when somebody used it, and has the instruction layer the agent works from
rotted?

## Skills

| Skill | What it measures |
|---|---|
| `ba0918-trigger-eval` | How accurately a skill set fires — judged from the descriptions alone, reported as recall, precision, stability and a confusion matrix |
| `ba0918-skill-interface-audit` | What a `SKILL.md` contract leaves out: undeclared side effects, unverifiable completion conditions, undefined failure handling |
| `ba0918-empirical-prompt-tuning` | How well the text of an instruction works, measured by running it under separated roles and classifying where the executor got stuck |
| `ba0918-skill-regression` | Whether a skill still behaves as it did, by re-running only the scenarios a change actually reaches |
| `ba0918-skill-improve` | Friction in real usage, read from the session logs an agent already left behind |
| `ba0918-context-audit` | The instruction layer itself — stale references, contradictions, wording that permits destruction, credentials left in a note |
| `ba0918-skill-token-efficiency-audit` | Where a skill amplifies token use, what quality a cheaper path risks, and what must be validated before adopting it |

Each of them measures something outside itself, and none is limited to this repository:
a skill directory for most, an agent's own session history for `ba0918-skill-improve`,
and a project's instruction layer for `ba0918-context-audit`.

## Install

Three kinds of route are supported — plugin, package manager and copy. They differ in how
updates reach you, not in what you get.

### Claude Code (plugin marketplace)

An installed copy follows the version declared in the marketplace entry, so an update
reaches you when the version is bumped.

```
/plugin marketplace add ba0918/agentic-meta
/plugin install ba0918-meta@agentic-meta
```

### Codex CLI (plugin marketplace)

Codex reads the same marketplace entry, and the skills appear under the plugin name as
`ba0918-meta:ba0918-trigger-eval` and so on.

```
codex plugin marketplace add ba0918/agentic-meta
codex plugin add ba0918-meta@agentic-meta
```

### OpenCode (plugin)

Add the repository to `plugin` in `opencode.json` — the project's or the global
`~/.config/opencode/opencode.json` — and restart OpenCode.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["agentic-meta@git+https://github.com/ba0918/agentic-meta.git"]
}
```

This route reads `package.json`, which is here as a distribution manifest rather than a
published package: `private: true` keeps it off the npm registry.

### APM (package manager)

[APM](https://github.com/microsoft/apm) manages skills for several agents from one
manifest. Installing adds a dependency to `apm.yml`; `apm.lock.yaml` pins the resolved
commit, and `apm update` moves it forward.

```
apm install ba0918/agentic-meta --target claude
apm install -g ba0918/agentic-meta
```

APM warns when a dependency is unpinned — pin a release tag (`ba0918/agentic-meta#v{version}`)
or a commit SHA.

### Copy (`gh skill` / `npx skills`)

Skills are copied into the project at install time, and updates are pulled by running the
command again. Naming one skill installs that skill alone; naming the repository installs
all of them.

```
gh skill install ba0918/agentic-meta ba0918-trigger-eval --agent claude-code
npx skills add ba0918/agentic-meta --skill ba0918-trigger-eval
```

What a copy route installs is the contents of `skills/` and nothing else — the measurement
assets live outside that directory so they are committed here without reaching anyone who
only wanted the skills.

## License

MIT. See `LICENSE`.
