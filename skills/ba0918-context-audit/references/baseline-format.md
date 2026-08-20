# Baseline Format

A baseline records the findings a project has already looked at and decided are deliberate,
so that they stop being reported. It lives at
`.agents/config/context-audit-baseline.json` inside the audited project.

## Why it is committed while nothing else is

Everything else a run produces — the collected targets, the findings, the report — goes to
`.agents/tmp/context-audit/`, the scratch area a project keeps out of version control. It is
one run's output, and the next run supersedes it.

A baseline is not that. It is an agreement — *this finding is intentional here* — and an
agreement belongs to the project rather than to the run that first wrote it down. So the
baseline alone is tracked, and it is the one file this audit expects to see in a diff.

A project with no version control loses nothing by it: the file is read from where it sits.

## What it stores, and why committing that is safe

**Nothing but opaque identifiers.** No detected value, no line out of a file, no
description of a finding.

An identifier is the first 16 hexadecimal digits of a sha256 digest taken over three things
joined together: the rule's identifier, the place the finding names (its file and line), and
the finding's description.

Two independent properties make it safe to commit:

- The description passed through the credential mask before the digest was taken, so a
  detected value never entered the input in the first place.
- The digest is one-way. Even the masked description cannot be read back out of the stored
  string, so the file discloses neither what was found nor anything about where the project
  keeps it.

Stated plainly: a baseline can be reviewed, committed and read by anyone who can already see
the repository, and it tells them nothing the repository does not. A file that recorded
*which* findings were accepted in readable form could not be treated that way — it would be
an index of every soft spot the audit knows about, sitting in version control.

The three parts together identify one finding. Two different findings landing on the same
identifier is not something sha256 leaves worth planning around.

## Schema

```json
{
  "version": 1,
  "suppressions": [
    "3f2a1b0c9d8e7f60",
    "a1b2c3d4e5f60718"
  ]
}
```

- `version` — the format's version. Version 1 is a plain list of identifiers.
- `suppressions` — the identifiers to withhold.

## Writing one

`--update-baseline` is an argument of `aggregate_report.py` and takes the path to write.
`{skill_dir}` below is the directory this skill is installed in, and `{ts}` the timestamp
the run mints once and reuses:

```bash
python3 {skill_dir}/scripts/aggregate_report.py \
  .agents/tmp/context-audit/findings-{ts}.json \
  --update-baseline .agents/config/context-audit-baseline.json
```

**Given that argument the script writes the baseline and stops.** It prints the path it
wrote and how many identifiers the file holds, and it produces no report in that run — the
reporting arguments have nothing left to act on. A run that wants both a baseline and a
report runs the script twice over the same findings.

### Fixing only part of what was found

`--baseline-below` names a severity and puts **only the findings less grave than it** into
the file, leaving the graver ones to keep being reported:

```bash
python3 {skill_dir}/scripts/aggregate_report.py \
  .agents/tmp/context-audit/findings-{ts}.json \
  --update-baseline .agents/config/context-audit-baseline.json \
  --baseline-below WARN
```

A finding *at* the named severity stays out of the baseline; the cut is strict. So the
invocation above fixes the INFO findings and goes on reporting WARN and BLOCK.

This is what makes the first run's middle option real. Facing a project's whole accumulated
history at once, a reader can settle the noise and keep the serious findings in front of
them, instead of choosing between accepting everything and reading everything.

Writing is a re-fixing rather than an appending: the file is built from the findings in
hand, whatever it held before. Run twice over the same findings, it produces the same file.

## Reading one

`--baseline` takes the path to read. A finding the file records is withheld, and **the
number withheld goes into the summary line**. Dropping them quietly is forbidden: a
suppression nobody can see is indistinguishable from a rule that stopped firing.

## A suppression is tied to a line number

The place a finding names is a file *and a line*, and the place goes into the digest.
So **a finding that moves to another line hashes to a different identifier, the baseline
stops covering it, and it is reported again.**

That is the safe direction to fail in. A suppression that survived any edit would go on
hiding a finding long after the thing it agreed to had changed, and nothing in the report
would show it. But the cost is worth expecting rather than discovering: after an edit that
shifts lines in an audited file, the findings that file holds come back looking new. They
are not new. Re-fix the baseline deliberately instead of reading the reappearance as fresh
decay.

A baseline that does not shift with line numbers, and that lapses on its own after a while,
is recorded as a later candidate in [rule-catalog.md](rule-catalog.md). Version 1 chooses to
be simple and to fail loudly.
