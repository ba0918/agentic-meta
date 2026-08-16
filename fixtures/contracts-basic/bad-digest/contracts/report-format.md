---
id: report-format
version: 1.2.0
---

# Report Format

A report produced under this contract is a Markdown document with the
following shape.

## Required structure

1. The first line is a level-1 heading starting with `# Report:` followed by
   the subject.
2. A `## Result` section states the outcome in one of the words `pass`,
   `fail`, or `blocked`.
3. An `## Evidence` section lists at least one observation supporting the
   result.

## Forbidden content

- No wall-clock timestamps; reports must be reproducible.
- No paths outside the producing skill's own directory.
