# Judging whether a diff reaches a scenario

When a change lands as `contract-change`, three answers are available. Narrowing by
`exercises` is mechanical and costs nothing. An acceptance costs nothing and is
defensible, but its ground is a person's word. This third option gets a judge to read
the diff against each scenario's expectations, so that "this does not reach it" can be
recorded with a machine's backing instead.

It is the least-used of the three by design. It is for the case where an acceptance is
not wanted and a run is too expensive — not for skipping runs in general.

## The judging input

```
python3 {skill_dir}/scripts/semantic_diff.py <skill> [--skeleton FILE] .
```

produces the canonical diff hash, the unified diff of everything that moved since the
lock was written, the scenarios the change reaches, and a skeleton of the judgment file
to fill in.

Restoring the earlier side is the one place git history is consulted, and the lock stays
free of it so its own answers keep coming from content compared against content.
Restoration is **by content hash, never by commit position**: the lock records a
verification by content and is tied to no commit, so working back from "the commit
around then" grabs the wrong base whenever history moved on by another route.

A file whose earlier content cannot be restored has `unclear` pre-filled for the
scenarios it reaches, rather than being left blank. Handed over as a blank to fill in,
it would be filled in — and the judge's reach would grow to declaring safe something it
never saw.

A file that has left the surface is drawn as a full deletion. Judged by presence on
disk instead, an edit that merely unlinks a reference would be named among the changed
files and then show an empty body, which reads as unaffected.

## The three answers

| Verdict | Meaning | What it does |
|---|---|---|
| `unaffected` | the change cannot reach this scenario | recorded as `accepted-semantic` |
| `unclear` | the judge does not commit | the question goes to a human |
| `affected` | the change reaches it | the scenario is run |

Only `unaffected` reaches the record. `unclear` is not a failure of the judge — it is
the answer that routes the question correctly.

Every verdict carries a rationale. A verdict nobody can audit is not evidence, and one
without a rationale is refused along with the whole file.

## What the judge may not do

The judge never launches anything, in any direction. It reads a diff and answers. That
boundary is held by the absence of the dependency rather than by a promise in prose:
`semantic_calibration.py` imports nothing that can start a process or open a socket, and
a test walks its source to keep it that way.

Its verdicts also start nothing. An `affected` does not queue a run; it reports that one
is needed.

## Calibration

Handing a model the judgment this harness otherwise says a machine cannot make is
defensible only after the model's own unreliability has been measured. The corpus holds
two sides:

```
calibration/must_flag/*.json   edits that indisputably change behaviour
calibration/must_pass/*.json   edits that indisputably do not
```

Neither side names any skill: the corpus measures the judge, not the target, and is the
same whatever is being judged. It ships with this skill because the model being measured
lives in the operator's environment, so calibration happens there.

```
python3 {skill_dir}/scripts/semantic_calibration.py --validate {skill_dir}
python3 {skill_dir}/scripts/semantic_calibration.py --score RESULTS.json {skill_dir}
```

`RESULTS.json` is `{"model": "<identifier>", "results": {case_id: verdict}}`. A missing
verdict is an error rather than a quiet exclusion; otherwise a perfect calibration could
be assembled from one judged case.

The gate opens on **zero false negatives** — no behaviour-changing case called
unaffected — with both sides above the case floor. False positives do not close it: they
only cost a rerun, which is the safe way to be wrong.

**The result is not stored.** A calibration record names a model and a date, and the
same name can be serving something else tomorrow with nothing in the record to show it.
The corpus is small, so a run that wants this route measures the judge as part of that
run and carries the result in its own evidence.

## Recording

```
python3 {skill_dir}/scripts/lock.py --update <skill> --partial \
  --scenario <ran>... --semantic JUDGMENT.json .
```

The judgment is checked in full before anything is written, and one failure refuses the
whole record: the diff hash must match the change actually in front of it — which is
what stops an old judgment being reused — the model must be named, every verdict must be
one of the three, every rationale must be there, and no scenario may be named that does
not exist.

## When to stop trusting it

If `accepted-semantic` outnumbers `pass` in the lock and stays that way, the route has
stopped being the exception it was meant to be. That is a separate signal from a lock
full of `accepted-without-run`, which is why the counts are kept apart.
