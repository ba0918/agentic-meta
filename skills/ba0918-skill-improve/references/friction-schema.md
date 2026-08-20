# Friction schema

The three shapes this skill produces: the measurement `collect.py` writes, the prompt
harvest `capture.py` writes, and the friction report an analysis composes from the
first.

Each has a different audience, and the differences matter. The measurement is read by
the analysing agents. The harvest is read by another skill whose body names its fields.
The report is read by a person, and is the one artifact whose forbidden content is
enumerated below.

## `collect.py` — the measurement

```json
{
  "summary": {
    "collection_timestamp": "ISO 8601 string, zoned",
    "days": "integer — the period asked for",
    "project_filter": "string (project key, the operator's home masked) | null when every project was read",
    "all_projects": "boolean",
    "projects_scanned": ["string — project key, the operator's home masked"],
    "stores": {
      "{store_name}": {
        "location": "string — where it was read, the operator's home masked",
        "present": "boolean — whether that location was there at all",
        "text_route": "boolean — can slash-command firings be read here",
        "structural_route": "boolean — can tool-recorded firings be read here",
        "abandonment": "string — recorded | inferred",
        "error_detection": "string — full | partial",
        "superset_utterance_sessions": "integer — sessions whose utterances could only be read as a superset"
      }
    },
    "sessions_found": "integer",
    "total_turns": "integer",
    "total_tool_errors": "integer",
    "total_skill_invocations": "integer",
    "unique_skills_used": ["string — bare skill name"]
  },
  "analysis": {
    "proceed": "boolean — whether there is anything to score",
    "reason": "string | null — why not, when proceed is false"
  },
  "sessions": [
    {
      "store": "string",
      "project": "string — project key, the operator's home masked",
      "turns": "integer",
      "tool_errors": "integer",
      "abandoned": "boolean",
      "skill_count": "integer — distinct skills fired in this session",
      "utterances_are_superset": "boolean"
    }
  ],
  "friction_signals": {
    "{skill_name}": {
      "invocation_count": "integer — firings",
      "retry_count": "integer — one more than the repeats inside the retry window (scoring-guide.md)",
      "correction_turns": "integer — utterances made after the skill fired",
      "session_abandoned_count": "integer — sessions holding this skill that ended broken off",
      "tool_error_count": "integer — failed tool runs in those sessions",
      "total_turns_to_completion": "integer — turns of those sessions",
      "sessions": "integer — sessions this skill was seen in",
      "stores": ["string — the stores it was seen through"],
      "routes": ["string — text | structural, the routes it was seen along"],
      "merged_route_pairs": "integer — firings both routes showed, folded into one",
      "stores_without_structural": ["string — of those stores, the ones with no structural route"],
      "confidence_downgraded": "boolean — true when that list is not empty",
      "stores_with_inferred_abandonment": ["string — of those stores, the ones whose abandonment was inferred"]
    }
  },
  "secret_warnings": [
    {
      "type": "string — aws_key | private_key | jwt | prefix_token | email | home_path | generic_secret | generic_long_key",
      "masked": "string — always the whole mask [REDACTED:{type}]"
    }
  ],
  "notes": ["string — one per store not found, and one per store found and not read to the end"]
}
```

### The declaration of capability is part of the measurement

`summary.stores` is not decoration. A count drawn through a route a store cannot read
is a different measurement from the same count drawn where both routes work, and an
analysis that cannot tell the two apart will recommend fixing a skill nobody ran.
The per-skill fields carry the same fact down to where it is used:
`stores_without_structural` names which store forced the downgrade, and
`confidence_downgraded` is the flag the scoring guide reads. What each store can be
read for, and why, is in [session-stores.md](session-stores.md).

`error_detection` is `partial` where a store's failures can be read out of only part of
its history, so `tool_error_count` from that store is an under-count and `error_rate`
built on it is a floor. It is declared as a field rather than left to the prose for the
same reason the two routes are: a limit an analysis has to notice cannot depend on a
reader having opened this document.

`present: false` and a matching line in `notes` mean the run asked for a store and did
not find it. That is reported and stepped over, never dropped in silence: an operator
who mistyped a location and an operator who does not run that runtime would otherwise
read the same clean result.

A store that was found and could not be read to the end writes its own line in `notes`
and keeps `present: true`, so the two facts stay apart. They differ in what they say
about the numbers: an absent store contributed nothing and was never going to, while one
that broke off part way may have contributed some of what it holds, which makes its
counts a floor rather than a total. Reading either as a clean measurement of no friction
is what both lines exist to stop.

`analysis.proceed` is false when the reading found no firing at all. Every friction
rate divides by the number of firings, so an analysis of nothing produces scores out of
nothing. Stop at the measurement and say so.

### A firing both routes showed is counted once

Where a store reads both routes, one firing can be detected twice: the operator types a
slash command, and the runtime then records the tool call that command produced. The
measurement folds that pair into a single firing and keeps the runtime's own record as
its route, so `routes` reads `structural` for it. `merged_route_pairs` counts the
firings folded that way, which is what lets a report say that an invocation count drawn
from a store reading both routes is a count of firings rather than of detections.

Counting both detections is not extra coverage. Measured on one synthetic session
holding exactly one such firing, counting them separately reported `invocation_count` 2
and `retry_count` 2 — the second detection lands inside the retry window of the first —
so `retry_rate` came out at 1.0, the heaviest weighted term of the score, for a firing
that succeeded in one attempt. Every skill fired by slash command therefore ranked as
maximally frictional.

Only a typed command followed by a tool call is folded, never the reverse. A tool call
the runtime recorded first, with the operator then typing the command, is the operator
firing the skill again after the agent had already fired it — a real repeat, and
exactly what the retry count exists to catch.

The pair must also be close. A tool call more than **three turns** after the typed
command is not folded, and the two are counted as two firings. That bound is the retry
window, defined with the counting it governs in
[scoring-guide.md](scoring-guide.md).

### Two things the collector this replaces emitted, and this one does not

**A per-invocation array.** The source emitted one entry per firing carrying a turn
index and a timestamp. The normalized events carry neither: a firing is observed inside
a record, and no adapter is asked to number the turns of its own store. That poverty is
the price of a vocabulary three storage formats can all fill, and reconstructing the
array would mean inventing the two fields that made it useful.

**Identifiers and file paths on the session rows.** The source named each session by
its file. The friction report forbids session identifiers outright, and a session
file's path sits under the operator's home directory — which is one of the kinds the
credential masking exists to remove. A row that cannot be named is still fully useful:
what each session showed is what the rows are for.

The `location` field survives that reasoning because it is masked on the way out,
through the same masker every harvested body passes through. Every project key in the
measurement is masked the same way. A key is a working directory with its separators
turned into hyphens, so the operator's home directory — whose name is the operator —
survives inside it, and survives the ordinary masking too, which looks for the
separators the conversion removed. Masking the locations and leaving the keys would put
the operator's name back on every session row of a file written to be pasted into a
report. Only a key beginning at the home root is masked: an unanchored match would
redact a hyphenated word sitting in the middle of a project's own name.

The harvest is deliberately not masked this way. Its keys are what another skill joins
its records to the measurement by, and a harvest is treated as sensitive material and
deleted after the run either way.

## `capture.py` — the prompt harvest

**This shape is frozen.** `ba0918-trigger-eval` is its reader, and this is that skill's
only source of real-data seeds. Three of these names are spelled out in that skill's own
body — the `slash_fired` and `correction_after_skill` signals and the `user_text_masked`
field — along with the file it expects to find them in. The record is frozen whole
rather than only the quoted half: what that skill reads is the record those three names
sit in, and one whose other fields have moved is not the record it was promised.

One JSONL file, one line per utterance, in the order the utterances were made:

```json
{"ts": "ISO 8601 string, zoned", "project": "string — project key", "user_text_masked": "string — the body with mask_secrets applied", "fired_skill": "string — bare skill name | null", "signals": ["string"]}
```

| Signal | Meaning |
|---|---|
| `slash_fired` | The utterance fired a skill by a slash command written `/<plugin>:<skill>`, the one form the text route reads ([session-stores.md](session-stores.md)). `fired_skill` names it |
| `correction_after_skill` | The utterance was made after a skill had fired, so it may be the operator correcting what that skill did |

An utterance carries at most one of the two: one that fires a skill is that firing, not
a correction of whatever ran before it.

`ts` is always present and always zoned. The event vocabulary refuses an utterance
whose time carries no zone, so the harvest has no null case; the source schema's `|
null` described a collector that took its time from a neighbouring record.

### The harvest is the one route by which bodies leave a store

Everything else this skill produces is counts and classifications. Here the words
themselves are written to a file, and four guards stand between a run and a written
body. All four fail closed:

1. The output must resolve to a path inside `.agents/tmp` under the working directory.
   Containment is decided on the resolved parent, not on the spelling of the path.
2. The output must be ignored by the repository it sits in, and git itself is asked —
   `git check-ignore --quiet`. Exit 0 is ignored; exit 1 is a decided "not ignored";
   anything higher means git could not decide, and an undecided answer refuses the
   write exactly like a negative one. The repository's ignore file is never read as
   text: anchoring, negation and the directory a pattern is relative to all make a
   hand-rolled reading wrong in the permissive direction.
3. The neighbouring name the write lands on before the replacement must be created
   new: refused if a link sits there, refused if a file does. Containment above decides
   the name the harvest is finally given and says nothing about that neighbour, so a
   link planted under it would carry the bodies wherever it points. Whatever is found
   there is refused rather than removed first — removing it would let a planted link be
   replaced and the run go on looking ordinary, and a gate over message bodies must not
   end in an ordinary-looking run. A leftover from a killed run is refused for the same
   reason, and the refusal names the file to remove.
4. The write replaces the file in one step, so a reader never sees a partly written
   harvest and a failed run never destroys a previous one.

**The masking is a blocklist and is therefore not complete.** It replaces what it
recognises — keys, tokens, private keys, addresses, home paths — and a credential
shaped like none of those survives it. A harvested file is sensitive material even
after masking. Treat it that way and delete it when the run that needed it is done.

## The friction report

A Markdown document. **It must never contain the original text of anything.** Only
figures, classifications and scores.

```markdown
# Friction Report: {project}

**Generated:** {ISO 8601 timestamp}
**Period:** {days} days
**Sessions:** {count}
**Stores read:** {store: routes available, abandonment recorded or inferred, present or absent}
**Analysis mode:** {parallel executors | sequential in-context}

## Executive Summary
{one to three lines, quantitative. No original text}

## Detection coverage
| Store | Present | text | structural | Abandonment | Error detection | Notes |
|---|---|---|---|---|---|---|

## Skill Rankings (by friction score)
| Rank | Skill | Friction Score | Invocations | Confidence | Top Issue | Recommendation |
|---|---|---|---|---|---|---|

## Detailed Findings

### {skill_name}
- **Friction Score:** {0 to 10}
- **Invocations:** {count}
- **Confidence:** High / Medium / Low {and every downgrade applied, with its reason.
  A qualification is named against the term it weakens, not here}
- **Retry Rate:** {retry_count / invocation_count}
- **Correction Rate:** {correction_turns / invocation_count} — the raw ratio, followed by
  the scored contribution in parentheses. The score divides the same count by five times
  the firings and saturates there, so the two numbers differ by construction; a report
  showing only the raw ratio reads as though the score disagreed with it
- **Abandonment Rate:** {session_abandoned_count / invocation_count}
- **Error Rate:** {tool_error_count / total_turns_to_completion}
- **Issues:**
  - {quantitative statements only}
- **Recommendations:**
  - {what to change, and where}

## Improvement Hypotheses

### Hypothesis {A/B/C}: {title}
- **Target:** {skill_name}
- **Change:** {what to change}
- **Expected Impact:** {quantified}
- **Size:** Small / Large
- **Confidence:** High / Medium / Low

## Coverage limits
{every route that could not be read, every count that rests on an inference, and
whether the analysis ran with independent executors or degraded to sequential}
```

The report ends at the hypotheses. Carrying one out is not this skill's work: see the
scope section of the SKILL.md.

### Forbidden in the report

- The original text of what the operator said.
- The original text of what an agent answered.
- Session identifiers.
- Personal information carried in a path beyond the operator's own username.
- Credentials — **including masked ones**. A mask says a credential was there, which is
  itself a thing the report has no reason to carry.

`secret_warnings` in the measurement exists so a run can tell an operator that harvested
material touched credentials. It is a signal to act on, not material to copy into a
document meant to be shared.
