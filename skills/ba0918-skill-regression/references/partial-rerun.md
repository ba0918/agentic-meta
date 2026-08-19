# Scenario-granular reruns

A change rarely reaches every scenario a skill has. Running the ones it does not reach
costs the same as running the ones it does, and buys nothing. This is how the harness
narrows the set, and how it carries the rest forward without pretending they ran.

## Declaring what a scenario touches

```yaml
exercises:
  - skills/acme-config/references/migration.md
```

The declaration is complete: it claims that nothing outside those files and the skill's
own `SKILL.md` affects this scenario. Because it is a complete claim, one path that is
not on the current surface discredits the whole of it — a typo or a moved reference
would otherwise buy a carry-over the scenario has not earned. A scenario with no
declaration, or with a discredited one, is reached by every change.

Adding a declaration costs no rerun. It is impact metadata and does not change what the
scenario measures, so it is left out of the scenario's content hash; otherwise putting
one on an existing scenario would cost a full run and nobody would.

## Narrowing

```
python3 {skill_dir}/scripts/lock.py --impact-scenarios <changed>... .
```

prints `skill<TAB>scenario` for what the change reaches. The rules all prefer the safe
answer whenever the material runs out:

- the skill's own `SKILL.md` is an implicit dependency of every scenario
- a changed path that is neither on the surface nor a scenario file cannot be reconciled
  with any declaration, so everything is reached
- a changed scenario file reaches the scenario it declares, when its content actually
  moved
- any other surface file reaches the scenarios declaring it, plus every scenario that
  makes no usable claim

## Carrying the rest forward

```
python3 {skill_dir}/scripts/lock.py --update <skill> --partial --scenario <id>... .
```

records the scenarios that ran and carries the others. Validity is established by
induction on the previous entry: that entry held the scenario as valid, so if its own
declaration has not moved and not one byte of what it depends on has moved, the pass
still holds. That is what lets the lock carry scenarios forward without storing
per-scenario file hashes.

A scenario is refused a carry-over when the material for that induction is missing: no
record in the previous entry, a dependency that was absent when it was recorded, or one
that has since changed. **One refusal stops the whole update** and names what could not
be carried — recording the rest anyway would leave the lock claiming verification for a
scenario whose ground moved underneath it.

Running nothing is legitimate. A change that reaches no scenario advances the lock with
no run at all.

## What the entry then says

The skill-level result is decided by the per-scenario records, not asserted:

| Every scenario | The skill reads as |
|---|---|
| a real run | `pass` |
| a run or a judged `unaffected` | `accepted-semantic` |
| anything else in the mix | `accepted-without-run` |

One scenario that was not actually run keeps the skill from claiming a pass. A carried
scenario keeps the date of its last real run, so freshness stays readable from the
record: an acceptance that stamped today would be indistinguishable from a run.
