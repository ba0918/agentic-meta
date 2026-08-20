# CA-* Rule Catalog

Every rule this audit runs. **This table and the `RULES` registry inside
`scripts/static_checks.py` both state what a rule is**, so either can be edited without the
other; `scripts/test_catalog_sync.py` holds the identifier, category, severity and fix action
of every rule against the registry so the two cannot diverge unnoticed.

- **Severity** is how serious the finding is, defined in
  [vendor/severity-and-verdicts.md](vendor/severity-and-verdicts.md). This audit uses
  BLOCK, WARN and INFO only: no rule reports an improvement opportunity, because every rule
  here fires on something already wrong.
- **Fix action** is whether the fix may be automated, defined in
  [vendor/fix-action-taxonomy.md](vendor/fix-action-taxonomy.md). It is an axis orthogonal
  to severity. This audit does not take the apply-then-report variation the taxonomy permits:
  an automatic fix is shown and confirmed before it is applied, never applied first.
- Every rule is a deterministic pure function. CA-C001 alone is split: candidate extraction is
  the pure function, and whether a candidate is a real contradiction or a deliberate
  distinction is left to a reading, which reports and changes nothing.

## The identifier bands

The last three digits fix the band, so a rule added later never lands on an arbitrary number:

| Band | Meaning |
|---|---|
| `0xx` | schema and staleness (shape, and what has gone out of date) |
| `1xx` | existence of what is referenced |
| `2xx` | reserved, unused |
| `3xx` | secrets and credentials |

The category prefix is `S` for stale, `U` for unsafe, `D` for drift, `C` for contradiction,
and `M` for memory.

## The rules

| ID | Category | Severity | Action | Verification | Content |
|----|----------|----------|--------|--------------|---------|
| CA-S001 | stale | WARN | AUTO_FIX / NEEDS_JUDGMENT | Pure function | A reference to a file or directory that is not there. Only path-shaped text containing a separator is extracted; a bare filename is out of scope, for precision. It is an automatic fix only when exactly one existing name a single edit away sits beside the reference, and left to a human otherwise. Only the audited project's own files are judged: a reference written in an installation-wide file is passed over, because the tree the judgment would use is not the tree that file belongs to |
| CA-S002 | stale | WARN | NEEDS_JUDGMENT | Pure function | A reference to a `skills/<name>/` directory that is not there. As with CA-S001, a reference written in an installation-wide file is passed over |
| CA-U001 | unsafe | WARN | REPORT_ONLY | Pure function | Wording about skipping confirmation or performing a destructive operation. What is matched is the vocabulary alone; which way the line points is not read, so a line forbidding one of these is reported beside a line permitting it and telling them apart is the reader's part. The line is quoted when it comes from an instruction file, and held back when it comes from a memory, which is named by its place and the kind of wording instead |
| CA-D001 | drift | INFO | REPORT_ONLY | Pure function | Runtime-specific tool vocabulary (`Edit`, `Write` and the like, including the Japanese 「〜ツール」 wording) leaking into a file meant to be runtime-independent — `AGENTS.md` and `PROJECT.md`. `CLAUDE.md` is addressed to one runtime, so it is out of scope. A finding is made per line, and a line naming several such tools is reported once under one representative term |
| CA-D002 | drift | WARN | NEEDS_JUDGMENT | Pure function | The gap between the skill directories that exist and the skills the instruction files record. The instruction files read are the project's own; a skill written down only in an installation-wide file is not recorded in this project |
| CA-C001 | contradiction | WARN | REPORT_ONLY | Split | One subject forbidden in one place and permitted in another. Candidate extraction is a pure function favouring recall; the judgment is a reading. A side of the pair taken from a memory travels as its place, its direction and the overlap, without its line |
| CA-M001 | memory | WARN | AUTO_FIX / NEEDS_JUDGMENT | Pure function | The shape of a memory's frontmatter. A key written without the canonical spacing is an automatic fix, normalised with the body left byte for byte as it was; a missing required key or an unknown type is left to a human, never supplied. A finding names the key at fault, never the value beside it; the line the fix replaces travels inside the fix alone |
| CA-M101 | memory | WARN | NEEDS_JUDGMENT | Pure function | Whether the files a memory references are there. The finding names the place, not the path a memory wrote |
| CA-M301 | memory | BLOCK / WARN | REPORT_ONLY | Pure function | Suspected secrets in a memory: a credential is BLOCK, personal information (an address, a home-relative location) is WARN. The detected value is neither transcribed into the finding nor masked in place |

## What this audit owns

- **CA-S001 and CA-S002** look like the structural check that compares code against its
  documentation, but the territory differs. This audit owns the files that carry instructions
  to an agent — `CLAUDE.md`, `AGENTS.md`, `PROJECT.md`, the rules directory, and project
  memory — and it owns them as instruction quality. Checking arbitrary documents for accuracy
  against the code they describe, or against each other, belongs elsewhere.
- **CA-D002** reports a gap in a listing without deciding it is a fault: leaving a skill out
  of an instruction file is as often deliberate as it is decay, which is why the finding is
  left to a human rather than fixed.
- **An installation-wide file is not the project's own**, so every question asked of the
  audited project's tree leaves those files out of both sides of it: the tree the judgment
  would use is not the tree they belong to, which is why a name one of them writes is never
  reported as missing from this project (CA-S001, CA-S002) and a skill only one of them
  records is never counted as written down in it (CA-D002).

## Implementation notes

- **CA-D002** is a set difference between the skill directories and the names the instruction
  files mention. It does not read each skill in full.
- **CA-C001** buckets claims by the subjects they name and pairs only claims sharing a bucket
  with opposite polarity, so the overlap threshold (0.2 by the Jaccard measure) does the work
  a sweep over every pair would otherwise do. **Which way a line points is read by pattern,
  so that reading is incomplete in the way the credential mask is**: a prohibition or a
  permission worded unlike every pattern it holds is passed over rather than paired, and a
  pair the rule does not offer is therefore no evidence that none is there.
- Each rule is listed in `RULES` as a pure `check(targets, ctx) -> list[Finding]`. Adding a
  rule is writing the function, listing it, and adding its tests; no existing rule is touched.
- Every finding carries `id`, `severity`, `action`, `where` (file and line), `what`, `why`,
  `how` and `fix_action` (old to new, or nothing), and the credential mask is applied to every
  text a finding carries before it is written out.

## Left for later

- `CLAUDE.md` and `AGENTS.md` in nested subdirectories.
- A baseline that does not shift with line numbers. As it stands a baseline is a plain list of
  opaque identifiers, so a finding that moves to another line stops being suppressed and is
  reported again — the safe direction to fail in.
- The `2xx` band, for drift rules not yet written.
- Memory formats belonging to runtimes other than the one supported today.
