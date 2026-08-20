---
name: ba0918-context-audit
description: An inventory skill that audits LLM instruction files (CLAUDE.md / AGENTS.md / PROJECT.md / .claude/rules / project memory) for decay, contradiction, harmful instructions, and cross-tool divergence. It verifies mechanically with a pure-function rule engine (the CA-* rule system), handles findings with the 3 values AUTO_FIX / NEEDS_JUDGMENT / REPORT_ONLY, and never automates deletion. It owns "quality as instructions", which neither code-versus-docs nor docs-versus-docs checking looks at. Use when the user says "context-audit", "audit the instruction files", "take inventory of CLAUDE.md", "audit AGENTS.md", "review the memory files", "the instructions have rotted", or "check whether the instructions are stale".
license: MIT
metadata:
  contracts:
    - severity-and-verdicts
    - fix-action-taxonomy
    - fixture-contract
---

# ba0918-context-audit
