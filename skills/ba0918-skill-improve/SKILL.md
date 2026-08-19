---
name: ba0918-skill-improve
description: Detects friction in skill usage by reading the session logs an agent already left behind, and turns those traces into per-skill friction scores that name what to fix. Reading is split from analysis, so the same measurement runs over three agent runtime stores — Claude Code JSONL, an OpenCode SQLite database, and Codex CLI rollout JSONL — and each store declares which detection routes it actually supports rather than filling an undetectable route with a guess. Use when the user says "skill-improve", "improve the skills", "analyze the friction", or asks which skills are being used badly.
license: MIT
metadata:
  contracts:
    - fixture-contract
---

# ba0918-skill-improve

An agent's session log is the only record of how a skill behaved in real use. This skill
reads that record, counts the traces of a skill being used badly — the same skill invoked
again moments later, a user restating the request right after an invocation, a tool call
that failed — and scores each skill so the worst friction is the thing that gets fixed.

Reading is separated from analysis. An adapter per store yields normalized events and
declares its own detection capabilities; the aggregation layer never learns a store's
storage format, and a route a store cannot detect is reported as undetectable rather
than estimated.
