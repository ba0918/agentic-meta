---
name: pipeline_runner
license: MIT
tags: [pipeline, tracing, synthetic]
description: Heterogeneous fixture skill bundling a script and a sample log.
metadata:
  maintainer: nobody
  contracts:
    - id: trace-log
      digest: sha256:671830a6d82ecf4bb96a4c196b3457f7a046d19cd773df4db0e075215892ea71
---

# pipeline_runner (fixture)

See HOWTO.md. This skill deliberately uses a different layout and vocabulary
from skillset-alpha: an underscore name, extra frontmatter fields, a bundled
shell script, and a pipe-separated log format.
