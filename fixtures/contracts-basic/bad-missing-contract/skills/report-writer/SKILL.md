---
name: report-writer
description: Synthetic fixture skill that produces reports and changelog entries.
metadata:
  contracts:
    - id: report-format
      digest: sha256:017156e79c2eb67bef20f8615994b02a1c78ce97d4d10f6ec51ca398a0d6f111
    - id: changelog-entry
      digest: sha256:50c256ff60e9960bc01d4fe385bcb7c31604fbf1585394c5be22ae610f122c70
---

# Report Writer (fixture)

A synthetic skill used only to exercise the vendor machinery. It declares two
contracts and expects their vendor copies under references/vendor/.
