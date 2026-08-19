# Running a batch through separate processes

Subagent launches are a limited resource, and a large batch or an unattended run exhausts
them. This route delegates each scenario to a separate process instead, which consumes
none. The judging rules do not change: the executor contract governs both routes.

Keep using subagents for a check of one or two scenarios. Building a batch costs more
setup than it saves at that size.

## The two halves

`regression_queue.py` is the producer and the grader — the part specific to this
harness. `process_runner.py` drains the queue by starting processes. They meet at
`work.jsonl`, so a batch can also be drained by whatever the operator already has.

```
python3 {skill_dir}/scripts/regression_queue.py build \
  --case evals/cases/<skill>/<scenario>.yaml --inputs evals/inputs/<skill> \
  --batch <dir> --repo-root .

python3 {skill_dir}/scripts/process_runner.py run \
  --work <dir>/work.jsonl --backends backends.json --backend <name> --root <dir>

python3 {skill_dir}/scripts/regression_queue.py grade --batch <dir>
```

## What the process route forces, and what it removes

- **The report is JSON at a declared path**, because the artifact is what gets graded.
  Prose bullets are not machine-checkable.
- **The critical flags stay out of the prompt**, exactly as with a subagent. They live in
  the batch manifest, so grading stays on the caller's side of the fence.
- **The reporting-channel problem disappears.** A subagent's completion message may never
  be delivered; a file either exists or does not.

## The permission boundary

The runner carries no vendor name. Every executable, flag and permission decision lives
in an operator-authored registry, and a work-queue entry can never contribute an argument
to a command line. That is the whole of the boundary: what runs is decided by the
operator, never by the queue.

The verdict comes from the artifact, never from the exit code. A process reporting its
own success is the same class of evidence as an implementer saying "it passed" — which is
to say, not evidence.

## Rerunning a unit

```
python3 {skill_dir}/scripts/regression_queue.py rerun --batch <dir> [--unit <id>...]
```

restores unfinished units to their declared baseline. Named units are **added** to the
unfinished set, never substituted for it: rerunning only the named ones would leave the
unfinished ones on contaminated trees, which is the failure this guard exists to stop.

A rerun re-materialises the scenario and demands a byte-for-byte match against what the
manifest recorded. A scenario whose declaration changed since the batch was built is
refused — that is a rebuild, not a rerun.

## Inlining the skill body

`--inline-skill` embeds the target `SKILL.md` in each prompt, so a backend without file
access reads the same words as one with it. A batch built that way carries different
scaffolding from one built without, so the two are not comparable evidence. The flag is
recorded per unit in the manifest, so a later reader can tell which shape produced a
report without diffing the prompts.

## Grading

`grade` reduces the returned artifacts to a mechanical tally and never returns a bare
pass. It collapses the part that is mechanical and names what still needs adjudication,
because a self-report the artifacts do not corroborate is re-judged by the caller.

An expectation carrying a machine-judged predicate is decided by fixed grader code, and
that verdict outranks the self-report in both directions.
