# Authoring Principles

The canon the SI-\* rules audit against. A skill is a set of instructions an agent executes,
so these principles are about what an instruction must carry to be executed correctly by a
reader that cannot ask a follow-up question.

This file is the audit's source of truth. The rules never invent criteria of their own: every
finding traces to a principle stated here, and a defect with no principle behind it is a
request to amend this file, not to widen a rule.

## The five principles

1. **Process over prose** — a skill is a workflow, not a reference document. Write it as
   phases, steps and transition conditions. Knowledge that is not a step belongs in a
   reference file, read at the moment the workflow reaches it.
2. **Specific over general** — not "check the tests" but "run the project's test command and
   confirm zero failures". A general instruction is one an executor can satisfy without doing
   anything.
3. **Evidence over assumption** — every completion condition is paired with the evidence that
   proves it. A condition whose satisfaction cannot be observed is not a completion condition.
4. **Progressive disclosure** — the body is an entry point. Detail lives in reference files
   one level away, and a reference does not itself chain into further references: an executor
   that must follow a chain to learn what it is meant to do has already lost the thread.
5. **Do not restate a contract** — where a protocol is fixed elsewhere, reference it instead
   of copying it. Two copies of a rule are edited separately and then disagree, and neither
   copy announces that it has become the stale one.

## Frontmatter contract

```yaml
---
name: <the skill's name>
description: <what it does>. <when to use it>.
---
```

- `name` and `description` are both required.
- `description` is capped at 1024 characters. It is resident in the executor's context
  whether or not the skill runs, so its cost is paid on every unrelated task.
- `description` states trigger conditions in the vocabulary a user would actually speak.
  Selection is decided by a model reading descriptions alone, so a description without
  trigger wording translates directly into a skill that never fires.
- `description` does not summarize the workflow. A procedure visible in the description
  invites the executor to act on the summary without ever reading the body.

## Entry points

The body is the single source of truth for a skill's logic, and any platform-local wrapper
that invokes it stays a wrapper — it holds no logic of its own. Portability is the reason:
naming conventions and invocation sugar differ per runtime, and a skill whose behavior lives
partly in one runtime's wrapper cannot be executed by another. Discoverability is secured by
the description, which every runtime reads.

Where a wrapper's name does not match the skill it invokes, the wrapper's own text names the
target skill; otherwise the two look like separate namespaces to whoever is choosing.

## Platform-neutral vocabulary

Bodies and references avoid one runtime's proprietary tool names (`Edit`, `Read`, `Bash`,
`Agent` and the like) and specific model identifiers. Name the operation — "read the file",
"delegate to a subagent", "state a high-capability model" — so the instruction survives the
runtime it was written on. Where a platform difference genuinely matters, express it with
shared vocabulary and a fallback rather than forking the body into per-runtime copies.

Quoted material and code examples are exempt: showing a command is not depending on it.

## Instruction budget

Precision pursued through more prose degrades execution rather than improving it. The longer
the instructions, the more of the executor's attention goes to following procedure instead of
doing the task, and low-salience lines drop out entirely. Before adding a sentence, ask
whether it improves the executor's judgment or describes a state transition that code should
guarantee. If the latter, the behavior belongs in a script with tests, not in the body.

Treat roughly 500 lines loaded in one run — body plus every reference that run actually reads
— as a signal to re-place responsibilities. It is a diagnostic threshold, never a gate: a
lean body in front of heavy mandatory references carries the same load as a heavy body.
Rationale, rejected alternatives and rare-exception walkthroughs go to history or to
reference files the runtime path does not load.

Reduction has limits worth knowing before applying them. Ambiguous terms, missing premises
and unstated dependencies on other skills are cured by making things explicit and adding one
worked example — not by cutting. Do not cut disambiguation, defaults, or the single worked
example to reach a budget.

## Non-interactive execution

Any body that requires a human answer states what it does when no answer is obtainable. The
fallback is a safe-side default — do nothing, report only, or stop — because a run that
cannot ask and does not know how to proceed will otherwise guess.
