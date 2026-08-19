# SI-\* Rule Catalog

Definitions of every skill-interface-audit rule. The canon is `authoring-principles.md`
(a sibling reference, read directly from the body); this catalog audits compliance with it
mechanically.

- **Severity** (BLOCK / WARN / INFO / PASS) is the seriousness of the problem, defined by
  [vendor/severity-and-verdicts.md](vendor/severity-and-verdicts.md).
- **Action** (AUTO\_FIX / NEEDS\_JUDGMENT / REPORT\_ONLY) is whether the fix can be automated —
  an axis orthogonal to severity, defined by
  [vendor/fix-action-taxonomy.md](vendor/fix-action-taxonomy.md).
- Phase 1 (SI-S\*) decides deterministically with pure functions. Phase 2 (SI-C\*) is semantic
  judgment by the LLM, all REPORT\_ONLY.

## ID band convention

| prefix | band | Meaning |
|---|---|---|
| `S` | `0xx` | structural — mechanical verification of structure and form |
| `C` | `1xx` | contract — semantic completeness of the API contract elements |

Update this table when a band is added in v2.

## Finding ID numbering rule

When one rule matches in several places, add a suffix to the finding ID:

- single match: `SI-S004`
- multiple matches: `SI-S004-1`, `SI-S004-2`, ... (in detection order)

Because the `where` field (`skill:file:line`) identifies findings uniquely in the report, the
suffix is an aid to readability only — use `where` for matching against a baseline.

## Phase 1: Structural Rules (pure functions)

This phase owns structural quality that a repository-level validation entry point does not
look at. Where the target repository has one, do not re-decide what it already enforces
(frontmatter shape, description trigger wording, link existence); where it has none, say so in
the report rather than assuming those checks ran elsewhere.

| ID | Severity | Action | Canon | Verification | Content |
|---|---|---|---|---|---|
| SI-S001 | WARN | REPORT\_ONLY | authoring-principles #4 | pure function | **Reference chain depth exceeded**: SKILL.md → a file in references/ → an md link to yet another file (depth > 1). Progressive disclosure goes one level only |
| SI-S002 | WARN | REPORT\_ONLY | authoring-principles frontmatter | pure function | **A workflow summary leaked into the description**: detects numbered lists, phase keywords (Phase/Step/まず/次に), and procedure description patterns. A description stays at "what it does + when to use it" |
| SI-S003 | INFO | REPORT\_ONLY | authoring-principles #1 | pure function | **Prose bloat**: sections in SKILL.md without a `Workflow` / `Phase` / `Step` style heading exceed 60% of the whole. An indicator of deviation from the process-over-prose principle |
| SI-S004 | WARN | NEEDS\_JUDGMENT | authoring-principles, platform-neutral vocabulary | pure function | **Platform-specific tool vocabulary leaked in**: SKILL.md or references/ contains one runtime's proprietary tool name or a specific model identifier. Code blocks and quotes are excluded |
| SI-S006 | WARN | NEEDS\_JUDGMENT | authoring-principles #5 | pure function | **A contract is inlined**: a run of 12 words matches verbatim between a file (SKILL.md or references/) and a vendored contract that same file links to. Code blocks are excluded |

SI-S005 is reserved and not implemented, so the numbering has a gap.

### SI-S001 detail: reference chain depth

Detection method:

1. Extract the relative md links in SKILL.md and treat the links into references/ as primary
   references. Each distinct reference file counts as one primary reference — linking the same
   file several times from SKILL.md does not multiply the edges
2. Extract the relative md links inside the primary reference files
3. If a primary reference links to md outside the skill's own `references/vendor/`, that is a
   finding. A vendored contract is the allowed terminal of the chain: it is the canonical text
   of a protocol, generated into the skill rather than authored there, and its own outbound
   links are not the skill's to fix. For the same reason a vendored copy is never traversed as
   a primary reference

### SI-S002 detail: workflow summary in the description

Detection patterns (regex-based):

- `\d+[.)]\s` — a numbered list
- `Phase\s*\d` / `Step\s*\d` — phase and step numbers
- `まず.*次に` / `最初に.*その後` — a chain of procedural connectives
- 2 or more `→` — a chain of flow arrows

### SI-S003 detail: prose bloat verdict

Heuristic:

1. Classify the `##` headings of SKILL.md: workflow-type (`Workflow` / `Flow` / `Phase` /
   `Step` / フロー / ワークフロー) vs prose-type (everything else). Subheadings at `###` and
   below inherit the classification of their parent `##`. A standalone `###` with no parent
   `##` is classified as prose-type
2. The denominator is **the total line count of SKILL.md excluding the frontmatter** (blank
   lines included). If the total lines of prose-type sections / the denominator > 0.6, it is a
   finding
3. A pile of knowledge should be moved out into references/ (authoring-principles #1 + #4)

### SI-S004 detail: platform-specific vocabulary

The vocabulary detected is the same set an instruction-file audit looks for, applied to a
different file set:

- tool API names: `Edit`, `Write`, `Read`, `Bash`, `Agent`, `Workflow`, `WebFetch`,
  `WebSearch`, `Grep`, `Glob`, `LSP`, `NotebookEdit`
- the Japanese 「〜ツール」 form: `Edit ツール`, `Bash ツール`, etc.
- the English "X tool" form: `the Read tool`, `Read tool's`, etc. (high-confidence pattern)
- model-specific names: `claude-opus-*`, `claude-sonnet-*`, `claude-haiku-*`, `gpt-*`, `o1-*`

**Case rules (to prevent false positives in an English SKILL.md)**:

- A PascalCase tool name (`Edit`, `Read`, `Write`, etc.) is detected only when it appears
  standalone **outside sentence-initial position**
- A capital at the start of a sentence (line start, or right after a period) is ordinary
  English orthography and is excluded
- Lowercase `edit`, `read`, `write`, etc. are excluded as ordinary verbs (they are also used
  as command names)
- Because `LSP` is also an industry-standard protocol name, detect only tool usages such as
  「`LSP` ツール」 or 「`LSP` を使う」, and exclude mentions of the protocol name
  (「`LSP` 準拠」, 「`LSP` サポート」, `the language server (LSP)`, etc.)

Exclusion conditions:

- code blocks (inside `` ``` `` / `` ` ``)
- quote blocks (`> ` lines)
- words inside file paths (`scripts/test_*.py`, etc.) — a `/` suppresses the match only when
  surrounded by path characters (letters, digits, `.`, `-`, `_`); a `/` between two tool names
  (`Read/Write/Edit`) is treated as enumeration, not a path
- capitalized words in sentence-initial position (line start, right after a period, or right
  after a bullet marker `- ` / `* ` / `+ ` / `| `)
- words inside Markdown headings (`## Workflow`, etc. A heading starts with `#` at line start,
  so it also falls under the sentence-initial exclusion, but exclude it explicitly)
- words right after a numbered list marker (the `Write` in `3. Write ...`, etc. The period in
  `N. ` is not a sentence-final period, but treat it as sentence-initial and exclude it)
- words right after Markdown emphasis markers at a list/sentence start (the `Read` in
  `1. **Read** the file`, etc.)
- **domain-term whitelist**: `Agent Artifact Store`, `Agent Skills`, `Agent N` (numbered
  subagent), `<Name> Workflow` (e.g. `Wrap Workflow`, `Cycle Workflow`) — these are domain
  terms, not one runtime's tool API names

### SI-S006 detail: inlined contract

**What is compared**: a file (SKILL.md, or any `references/*.md` of the same skill) against
**only the vendored contracts that same file links to**. An unlinked contract is never
compared — a skill that happens to share vocabulary with a contract it does not reference is
not duplicating it. Whether a link is a contract link is decided by where the link resolves,
not by the file name it ends in.

**The signal is a verbatim run of 12 words**, over lowercased word tokens with code fences and
frontmatter stripped. Nothing else. Lexical similarity and heading-name matching were both
**measured and rejected** on 2026-07-27 over a 48-skill corpus:

| Candidate signal | Result |
|---|---|
| Contract-distinctive vocabulary rate | Continuous, no separation (median 0.117 / max 0.625). The top scorers were skills that legitimately *implement* the contract |
| Same, per section | Same outcome (median 0.058 / max 0.157) |
| Heading-name match | 6 hits, false positives. A heading like `Preventing rationalization` is shared because the authoring convention *recommends* that table — the rows underneath were entirely different |
| **Verbatim 12-word run** | **4 hits, 4 of 4 confirmed true positives by inspection** |

The 4 findings at introduction were a duplicated test-framework detection table, a comparison
table that had **already drifted** from the contract it copied (the contract said "Verification
level / When it runs", the copy said "Role / In the pipeline"), a secret-masking rule, and a
failed-state retention rule.

**Why there is no line-span gate.** The measured friction reduction pattern describes a long
inline section, so gating on "the matched region spans N lines" is tempting. Measured, it
removes real findings: at a 4-line gate, 2 of the 3 then-confirmed true positives disappeared,
because a duplicated **table** matches in fragments that do not form a contiguous line run. A
12-word verbatim run is itself the evidence that text was copied; the line count adds nothing
but false negatives.

**Why n = 12.** Sweeping the threshold: n=8 gives 16 pairs, n=10 gives 7, n=12 gives 4, n=16
gives 0. The pairs that appear only below 12 are short role-specific restatements sitting next
to a link, which is exactly what a referencing skill is *supposed* to write. 12 is the point
where the boundary between "restates its own role" and "copied the contract" falls.

**Why NEEDS\_JUDGMENT and not AUTO\_FIX.** Consolidating an inline duplicate pays off under
three conditions: the inline section is long, it is **not relevant to every scenario**, and the
contract covers it fully. The middle condition cannot be decided mechanically, and it is the
real gate — a measured case existed where the duplicate was load-bearing and removing it
changed nothing at run time. Which side to keep is a judgment, so the rule reports and never
rewrites.

**Recall is not claimed.** A duplication that has been fully paraphrased carries no verbatim
run and is invisible to this rule. SI-S006 finding zero results is not evidence that no
contract is inlined.

**ID note**: `SI-S005` is reserved below for "missing rationalization guard table", so this
rule takes `SI-S006`. The reservation predates it and was not renumbered — a catalog whose IDs
shift under later arrivals cannot be read against older findings.

## Phase 2: Contract Rules (LLM semantic judgment)

The fix action of every rule is **REPORT\_ONLY** (the ceiling is NEEDS\_JUDGMENT; AUTO\_FIX is
forbidden). A finding includes a patch candidate (`fix_draft`: a draft of the text that should
be added).

**"Not applicable" is a legitimate state**: given a skill's nature, a particular contract
element may be unnecessary. Read the skill's purpose and workflow and decide on "could an LLM
misunderstand this and cause an accident if the element is missing". If the element is
unnecessary, that is a PASS.

| ID | Severity | Canon | Content | Typical N/A case |
|---|---|---|---|---|
| SI-C001 | WARN | authoring-principles #2, #3 | **Undeclared side effects**: file creation, modification, or deletion, external communication, or state change is not stated. When missing, the LLM adds side effects "while it is at it" | A read-only skill that already states it changes nothing |
| SI-C002 | WARN | authoring-principles #3 | **Missing or unverifiable completion condition**: what counts as done is unclear, or is written in a form that cannot be verified | An interactive skill where the user decides when to stop |
| SI-C003 | WARN | authoring-principles #2 | **Undefined failure handling**: how to behave on an error or interruption is not written. The LLM swallows the failure and reports completion | A skill with no failure path, such as a pure thinking aid |
| SI-C004 | INFO | — | **Missing input/argument contract**: the list of arguments, their defaults, and the behavior with no argument are unclear | A skill that takes no arguments |
| SI-C005 | INFO | authoring-principles #2 | **Undefined output/artifact**: what it produces (a file, a report, a diff) is unclear | A skill that is complete within the dialogue |
| SI-C006 | INFO | — | **Undocumented delegation condition**: the boundary against similar skills and when to use which is not written | A skill with a single purpose that cannot be confused with another |

### The discipline behind these severities

Why SI-C001-C003 are WARN and SI-C004-C006 are INFO:

- **WARN (C001-C003)**: the LLM accident mode on omission — runaway side effects, misjudging
  completion, swallowing failures — has been observed in operational friction data and in
  execution-quality measurements, the evidence classes `ba0918-skill-improve` and
  `ba0918-empirical-prompt-tuning` produce. Promote or demote the severity as evidence
  accumulates
- **INFO (C004-C006)**: even when missing, the context tends to fill them in, and no measured
  data yet ties them directly to an accident. Promote to WARN once operational logs confirm a
  correlation with accidents

## v2 candidates (out of scope for v1)

- SI-C007: idempotency / re-entrancy — safety of re-running after an interruption
- SI-C008: non-interactive fallback — behavior under headless execution
- SI-C009: preconditions — requirements on the execution environment
- SI-S005: missing rationalization guard table — recommended for skills that modify files
- claim normalization hash + expiry for the baseline
- promotion of stable SI-S\* rules into the target repository's own validation entry point
