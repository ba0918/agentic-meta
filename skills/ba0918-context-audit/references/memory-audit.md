# Memory Audit

Project memory is what an agent runtime carries from one session into the next: a directory
of Markdown files, each opening with a frontmatter block that names it and says when it
applies. It instructs an agent exactly as `CLAUDE.md` and `AGENTS.md` do, it decays the same
way, and unlike them nobody reviews it — it is written mid-session by an agent and read back
silently afterwards, for as long as the project lasts.

This audit brings memory into scope and **narrows that scope hard**, because reading memory
wrongly does not cost a missed finding. It costs a privacy incident.

The severity and fix action of each rule below are stated once, in
[rule-catalog.md](rule-catalog.md), against the vocabularies of
[vendor/severity-and-verdicts.md](vendor/severity-and-verdicts.md) and
[vendor/fix-action-taxonomy.md](vendor/fix-action-taxonomy.md). What this file carries is
the detail behind the three memory rules and the constraints binding them.

## Scope

- **By default**: the Markdown files of exactly one memory directory — the one belonging to
  the project the audit was pointed at.
- **With `--include-global`**: additionally the installation-wide instruction file and the
  Markdown files of the installation-wide rules directory, both of which sit under the
  operator's home. This is an opt-in; nothing reads them without it.
- **Every project at once is not supported.** Reading another project's memory is the
  incident this scope exists to prevent, so no argument widens it.

## The home the store is looked up under is a parameter

`collect_targets.py` takes `--home`. It defaults to the home of the user running the audit,
and the resolution below derives the location no other way.

Two things follow. A run can be pointed at a staged store — a directory assembled for a
test, or a history copied off another machine — and the code path it exercises is the same
one that runs against the live store, rather than a second path kept for testing. And the
one place this audit steps outside the project it was given is a value handed to it, visible
in the invocation instead of buried inside the resolution.

## Resolving the working directory to a memory directory

The runtime keys its project store by the working directory with **every character outside
letters and digits replaced by a hyphen** — separators, dots and underscores alike, not
separators only. A rooted directory therefore yields a key that begins with a hyphen, and a
path segment whose name starts with a dot contributes two hyphens where a reader expects
one. `slugify_cwd` performs exactly that substitution.

### Reverse verification, and skipping rather than guessing

`resolve_memory_dir` hands back a directory only when both of these hold:

1. The candidate directory is really there.
2. Resolving its symbolic links lands **exactly two levels** inside the runtime's project
   store, with the second level named `memory`.

Anything else yields nothing, and the directory is **skipped unread**, recorded among the
skipped rather than guessed at. The second condition is what stops a link placed inside the
store from walking the audit back out of it.

One case stays structurally undetectable: two different working directories whose keys
collide land on a single directory, and nothing in the path distinguishes that from the
ordinary case. The answer is visibility rather than detection — the report names the
absolute directory that was opened.

### Saying what was read

`collect_targets.py` reports the resolved directory as `memory_dir`, and
`aggregate_report.py` puts it into the report when it is given `--targets`. **Pass that
argument.** The findings cannot stand in for it: a finding names its file relative to the
audited project, which for a memory is a parent-relative path, and the mask that runs over
every finding replaces a home-rooted location with a placeholder. Without `--targets` the
report can say only that no location was given to it — honest, and useless.

## The three memory rules

### CA-M001 — the shape of the frontmatter

The keys this rule knows (`name`, `description`, `type`) are **the runtime's own
convention, not this repository's**. The rule is deliberately conservative, so that a
runtime which gains a key or a type does not turn every memory in the project into a
finding at once.

- A missing `name` or `description` is left to a person. Supplying either would mean
  inventing what the memory is about.
- A `type` outside the observed set (`user`, `feedback`, `reference`, `project`, `session`)
  is left to a person as well, rather than treated as a violation: the likelier explanation
  is that the runtime moved on and this list has not.
- A key line not in the canonical `key: value` form is an automatic fix. The fix names the
  exact line it replaces and is applied **inside the frontmatter block only**, so a body
  holding the same characters is untouched and its bytes come out as they went in.

### CA-M101 — the paths a memory names

The references extracted are markdown links and code spans whose text reads as a path: made
of the path alphabet, containing a separator, and ending either in an extension or in a
separator. A bare filename is out of scope, because too much ordinary prose reads as one.

References are resolved **against the audited project's root**, not against the memory
file's own directory. A memory is written about a project and the paths it carries are that
project's paths; resolving them beside the memory would check a location nobody meant.

A path that is not there is left to a person. A memory is never rewritten automatically:
the reference may be stale, or the thing it names may have been renamed and the memory be
the record of why — and telling those apart is a reading.

### CA-M301 — suspected secrets

Every line goes to the detector in `secret_detect.py`, a byte-identical copy of the one
`ba0918-skill-improve` carries. What comes back is **one entry per kind of thing found**,
not one per occurrence, so a line naming the same kind three times is a single finding.

- A credential is BLOCK.
- Personal data — an address, a home-rooted location — is WARN. These identify a person
  rather than granting access to anything, and without the split every memory that
  legitimately notes where a file lives would report at the top severity, which is how a
  severity stops meaning anything.
- A line holding both is BLOCK.

The finding is reported and nothing more. **The value is not masked in place**: masking a
live credential inside the file hides the leak without revoking it, leaving the project
worse off than it was while looking better.

## The constraints (invariants)

- **A detected value never reaches an output.** Not the findings, not the report, not the
  baseline. What travels is the name of the kind and the place it was seen.
- **The mask runs in one place** — over every text a finding carries, before any finding
  leaves the rule engine. A rule added later cannot forget to apply it.
- **The mask is a blocklist, so it is not complete.** A credential shaped unlike every
  pattern it holds passes straight through. Wherever masked text is handed onward — into a
  report, into a reading, to a person — that limitation is stated alongside it.
- **What the contradiction reading receives is a finding's own description**, already masked
  and already cut down to the two claim lines. The files those lines came from, the content
  around them, and anything identifying a person, do not travel with it.
- **The only automatic fix against a memory is the frontmatter formatting above.** Deleting
  a memory, and rewriting what one says, are not automated by any route.
