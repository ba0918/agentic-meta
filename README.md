# agentic-meta

Skills that measure a skill set. They answer the questions an author cannot answer by
reading their own work: does each skill fire when it should, does each `SKILL.md` say
enough to be executed correctly, do the instructions themselves survive contact with an
agent, does a skill still behave the way it did before the last edit, how did a skill
actually go when somebody used it, and has the instruction layer the agent works from
rotted?

- **`ba0918-trigger-eval`** measures how accurately a set of skills fires. It judges from
  the descriptions alone — the model's field of view at real triggering time — and reports
  recall, precision, stability and a confusion matrix, names the pairs that collide, then
  runs the rewrite-and-re-evaluate loop until the numbers stop moving.
- **`ba0918-skill-interface-audit`** audits each `SKILL.md` statically, as an API
  specification. It reports what the contract leaves out: undeclared side effects,
  completion conditions that cannot be verified, undefined failure handling. Every finding
  carries a patch candidate, and none is ever applied automatically.
- **`ba0918-empirical-prompt-tuning`** measures and improves the text of an instruction.
  It runs the instruction under a separation of roles where the one doing the work never
  sees the pass criteria and the one grading never sees the instruction, classifies where
  the executor got stuck, and repeats until improvement plateaus. The verdict is computed,
  not judged by whoever is doing the tuning.
- **`ba0918-skill-regression`** keeps the criteria a skill was tuned against as scenarios,
  and re-runs only the ones a change actually reaches. A lock records what was verified
  against which content, so editing one shared contract cannot silently change every skill
  citing it. Every batch is sized before it starts.
- **`ba0918-skill-improve`** reads the session logs an agent already left behind and turns
  them into per-skill friction scores: the same skill invoked again moments later, a user
  restating the request right after an invocation, a tool call that failed. Reading is
  split from analysis, so three runtimes' stores feed one measurement, and a store that
  cannot see a route reports it as undetectable rather than filling it with a guess.
- **`ba0918-context-audit`** takes stock of the instruction layer itself — `CLAUDE.md`,
  `AGENTS.md`, `PROJECT.md`, the rules directory, and the project memory nothing else
  reaches. It reports stale references, contradictions, wording that permits destruction,
  and credentials left in a note, and it sorts every finding into what may be fixed
  automatically, what a human has to decide, and what is reported and nothing more.
  Deleting and rewriting prose are never automated.

Each of them measures something outside itself, and none is limited to this repository:
a skill directory for most, an agent's own session history for `ba0918-skill-improve`,
and a project's instruction layer for `ba0918-context-audit`.

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
all of them. Each command places them where its agent setting points: `gh skill` asks which agent
when none is named, while `npx skills` defaults to the shared `.agents/skills/`.

```
gh skill install ba0918/agentic-meta ba0918-trigger-eval --agent claude-code
npx skills add ba0918/agentic-meta --skill ba0918-trigger-eval
```

What a copy route installs is the contents of `skills/` and nothing else. The material
these skills are measured with — scenarios, their input files, the verification lock —
lives outside that directory on purpose, so it is committed here without reaching anyone
who only wanted the skills.

## License

MIT. See `LICENSE`.

Contributing: `PROJECT.md` covers the layout and the commands, `ROADMAP.md` the progress.
