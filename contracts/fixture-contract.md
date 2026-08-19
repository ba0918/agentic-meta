# Fixture Contract

What a measurement instrument may assume about a skill tree it has never seen, and
what a verification fixture provides in return. An *instrument* is a skill that
measures, audits, or improves other skills. A *target tree* is the directory tree
holding the skills under measurement. A *fixture* is a synthetic target tree kept in
this repository to prove that an instrument completes on unfamiliar ground.

## Target resolution

An instrument locates skills in a target tree by trying these layers in order and
taking the first layer that yields at least one skill. Layers are never mixed: once a
layer matches, later layers are not consulted. At every layer, directories whose name
starts with `.` and installed-dependency directories (`node_modules`) are skipped.

1. `<target>/skills/*/SKILL.md` — the conventional layout. A `skills/` directory is
   the position every copy-route installer searches, so a tree holding one is
   declaring where its skills live. That declaration outranks the root `SKILL.md`
   below, which a single skill bundling example skills under `skills/` also carries.
2. `<target>/SKILL.md` — the target tree is itself a single skill. A root `SKILL.md`
   claims the whole tree as one skill, so it outranks the sibling-directory layer
   that would otherwise misread the skill's own subdirectories as separate skills.
3. `<target>/*/SKILL.md` — a tree whose root holds skill directories directly.
4. `<target>/**/SKILL.md` — a recursive search at any depth, ignoring any `SKILL.md`
   nested beneath a directory already identified as a skill.

A *skill* is the directory containing a `SKILL.md`. Its identity is read as follows:

- **name** — the `name` key of the `SKILL.md` YAML frontmatter; when the key or the
  frontmatter block is absent, the directory's basename. Names are opaque tokens:
  dots, underscores, and hyphens are all legal and carry no structure.
- **description** — the `description` key of the frontmatter. A missing description
  is a reportable observation, never a crash and never a silent skip; the skill still
  counts as resolved.
- Frontmatter key order is not significant, and keys beyond these two (`license`,
  `tags`, arbitrary `metadata` entries) are tolerated and ignored.
- A frontmatter block that fails to parse is treated as absent; the failure is a
  reportable observation, and the skill still counts as resolved.
- Two skills resolving to the same name is not a resolution failure; each remains
  identified by its directory path. An instrument that cannot represent colliding
  names may stop and state why. Silently dropping one of them is the only forbidden
  outcome.

Nothing beyond `SKILL.md` itself may be required to *find* a skill. In particular,
the completion declaration below is an obligation on fixtures, not on target trees;
an unknown third-party tree will not carry one.

These obligations bind the *instrument* — the agent executing the skill — over the
resolution result it works from. A helper script serving one purpose inside a run may
operate on a container the instrument has already resolved and return only the subset
that purpose needs: a description collector handed a resolved directory carries
neither the search order nor the exclusions above, and may pass over an entry it
cannot read a name or a description from. What the instrument may not do is let that
subset stand in silently for the whole — whatever a helper left out is the
instrument's to report.

## Run output placement

Everything a run produces — reports, metrics, logs, intermediate state — is written
outside the target tree, into a scratch area owned by the executing session. The
target tree is never written to: a write into it would change file contents that
digest verification proves against a lock, and would dirty the `git status` that the
post-run cleanliness check relies on. The same discipline protects a real target from
being polluted by its own measurement.

## Read scope

An instrument reads three places: the directory it is installed in, the target tree, and
the output area it writes to. Anything else — the executing user's session history, other
projects on the machine — requires an explicit grant from the run that invoked it, stated
in the invocation. Without that grant, an instrument that cannot obtain something it needs
says what is missing and continues in a reduced form; it does not go looking for a
substitute of its own.

This is the write placement above read from the other side. A measurement whose reach is
not bounded stops being a measurement of its target, and when the instrument delegates,
whatever it gathered travels into another model's context.

## Mutating instruments

An instrument whose procedure rewrites its target — for example, a phase that edits
descriptions and commits each rewrite — never runs those phases against the canonical
tree. Instead it:

1. copies the target into the scratch area, leaving the target's own `.git` behind —
   the mutating phases need a base to diff against, not the target's history, and
   carrying that history in would make the initial commit below mean something other
   than the state the run started from,
2. runs `git init` in the copy and records an initial commit, giving the mutating
   phases a diffable base and a place to commit, and
3. runs every mutating phase against that working copy only.

The canonical tree — fixture or real — stays read-only for the entire run. After the
run it must show a clean `git status` and pass the same verification it passed before
the run.

## What a fixture provides

A single fixture cannot prove generality; the fixture *set* can. Fixtures in this
repository therefore differ from one another on purpose — in directory vocabulary,
naming style, frontmatter shape, bundled asset kinds, and log format — so that an
instrument completing on all of them has demonstrated its fallbacks rather than one
lucky compatibility.

Each fixture tree declares the ground truth needed to judge that a run *completed*:
an `expected-skills.json` at the fixture root, listing the resolved name of every
skill the tree contains — one entry per skill, so if two skills share a resolved
name, that name appears once for each of them.

```json
{
  "skills": ["acme-notes", "acme-review"]
}
```

A run against a fixture is judged complete when the skills the instrument's report
covers match the declaration exactly, counted with multiplicity — no declared skill
missing, no skill reported that is not declared — and the canonical fixture tree is
unchanged afterwards. Exact equality cuts both ways: a declared skill the report
never reaches fails the run, as does a skill invented by the instrument; and a skill
added to the fixture without updating the declaration is caught by the first run
that resolves it. The declaration exists for that judgment only — it is
evaluation-side ground truth, and instruments must not read it to resolve targets.

## Conformance tests

This contract ships none. Its clauses bind how an instrument behaves at run time
against an arbitrary tree — search order, write placement, working-copy discipline —
which is observable only in a run's evidence. The one static surface, the agreement
between a fixture tree and its `expected-skills.json`, could be tested — but only by
re-implementing the resolution rules in code, a second statement of them that would
drift from this text unnoticed. The completion judgment above exercises the
declaration directly instead, against whichever instrument is actually under
acceptance.
