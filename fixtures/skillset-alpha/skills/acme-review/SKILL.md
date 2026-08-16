---
name: acme-review
description: Synthetic fixture skill that reviews work and writes handoff notes.
metadata:
  contracts:
    - id: handoff-note
      digest: sha256:9b59eb583dc0724d03c8aec63649bff2b465e9f78497867b74e3ccf906eeadfc
---

# Acme Review (fixture)

Review the work item against references/checklist.md, then write a handoff
note following the vendored handoff-note contract.
