# Sizing a batch before it runs

Running a scenario drives an agent through a whole task, which is what makes this
harness expensive. A batch whose size only becomes visible while it is already spending
is how one run ends up consuming a fifth of a week's allowance. Three things keep that
from happening, and the third is the one that actually protects the first run.

## 1. The dry-run

```
python3 {skill_dir}/scripts/cost.py dry-run \
  --skill <skill> --route <route> --inputs evals/inputs/<skill> [--history PATH]
```

Executes nothing. For every selected scenario it reports:

- **the input size**, and an approximation in tokens derived from it. This is knowable
  whether or not the scenario has ever run: it is the prose, the staged files, and the
  text of the skill under test, all of which are on disk.
- **what it actually cost last time**, when there is a measurement for this scenario on
  this route, scaled by how much the input has changed since.
- **that there is no measurement**, when there is none.

The two figures are reported side by side and never folded together. One is derived
from bytes; the other was observed. The total covers only the scenarios there is a
measurement for — folding an unmeasured one in as zero would make the batch read small,
which is the exact misreading this exists to prevent.

**A route is part of the measurement.** What a scenario costs is a fact about the model
and the path that ran it, so a record from another route does not answer for this one.

## 2. The stop after the first unmeasured scenario

History cannot help the first time a scenario runs, and that is when the surprise hurts.
`stop_after_first` is set whenever the batch holds a scenario with no measurement: run
one, report what it actually cost, and ask before going on. An unknown cost is then
bounded by a single scenario, structurally, rather than by anyone's judgment.

Record what a run cost as soon as it is known:

```
python3 {skill_dir}/scripts/cost.py record --skill <skill> --scenario <id> --route <route> \
  --input-bytes N --input-tokens N --output-tokens N --wall-seconds S
```

## 3. The ceiling

Estimates are wrong; a hard stop is not. A batch may carry a ceiling in tokens, and a
secondary one in seconds against a runaway. Reaching either stops the batch where it is.
A ceiling that names nothing never stops anything, which is the state a caller who set
no budget is in — deliberately, so that the absence of a budget is visible rather than
implied.

## Where the history lives

Not in the lock, and not in the target repository at all. What a scenario cost is a fact
about the environment that ran it, and the lock travels to every environment that clones
the repository. The path is named by the invocation; failing that, the
`SKILL_REGRESSION_COST_HISTORY` variable; failing that, a directory under the executing
user's own state area.

Judge calibration is kept out of the repository for the same reason, and the semantic
triage reference says so on its own account.

## What this does not do

It does not express cost as a share of a quota. A quota is not observable from here, and
a figure derived from a limit someone typed in once would go stale without any sign.
Tokens and seconds are what can be measured; converting them into "how many runs are
left" needs an anchor a human sets, and that is deliberately left out until there is
enough history to make it worth the manual step.
