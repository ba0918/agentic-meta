# Output Contracts

This directory holds the canonical text of *output contracts*: protocols that fix the
format of artifacts shared between skills. A contract is a protocol rather than a
document because each skill's copy of it is bound to the canonical text by a digest,
and because a contract may carry conformance tests of its own.

The vendoring itself — expanding each contract into every skill that declares it, and
proving each copy byte-identical to its source — is done by
`@ba0918-dev/agentic-skill-vendor`, installed as a dev dependency. The mechanism's
specification (digest rules, the vendored copy's header format, violation kinds, exit
codes) is canonical in that tool's own repository and is deliberately not restated
here, so the two cannot drift apart. `PROJECT.md` records the commands.

## Canonical contract files

A contract lives in exactly one file, `contracts/<id>.md`. **The file name is the id** —
nothing inside the file declares it.

## Declaring a dependency

A skill declares what it depends on by id, and only by id, in the frontmatter of its
`SKILL.md`:

```yaml
metadata:
  contracts:
    - report-format
```

A digest never appears beside a declaration. The declaration expresses a stable intent
to depend on a contract; the digest recording which text is adopted right now lives in
the central lock, `vendor-lock.json`, which the tool's `gen` rewrites from the
canonical text. The two answer different questions and are therefore kept apart.

## Conformance tests

A contract may ship conformance tests under `contracts/<id>/conformance/`. They are
pinned by a digest of their own, separate from the contract body's, so that either can
change without the other being silently re-adopted.

Running them is out of scope for vendoring. A digest proves that a copy matches its
source; it cannot prove that a skill still satisfies the contract. That judgment
belongs to this repository's regression machinery, not to the tool that copies files.
