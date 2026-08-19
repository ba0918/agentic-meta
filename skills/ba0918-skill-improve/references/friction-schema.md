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
    "project_filter": "string (project key) | null when every project was read",
    "all_projects": "boolean",
    "projects_scanned": ["string — project key"],
    "stores": {
      "{store_name}": {
        "location": "string — where it was read, the operator's home masked",
        "present": "boolean — whether that location was there at all",
        "text_route": "boolean — can slash-command firings be read here",
        "structural_route": "boolean — can tool-recorded firings be read here",
        "abandonment": "string — recorded | inferred",
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
      "project": "string — project key",
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
      "retry_count": "integer — the length of a run of firings of the same skill",
      "correction_turns": "integer — utterances made after the skill fired",
      "session_abandoned_count": "integer — sessions holding this skill that ended broken off",
      "tool_error_count": "integer — failed tool runs in those sessions",
      "total_turns_to_completion": "integer — turns of those sessions",
      "sessions": "integer — sessions this skill was seen in",
      "stores": ["string — the stores it was seen through"],
      "routes": ["string — text | structural, the routes it was seen along"],
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
  "notes": ["string — one per store that was asked for and not found"]
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

`present: false` and a matching line in `notes` mean the run asked for a store and did
not find it. That is reported and stepped over, never dropped in silence: an operator
who mistyped a location and an operator who does not run that runtime would otherwise
read the same clean result.

`analysis.proceed` is false when the reading found no firing at all. Every friction
rate divides by the number of firings, so an analysis of nothing produces scores out of
nothing. Stop at the measurement and say so.

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
through the same masker every harvested body passes through.

## `capture.py` — the prompt harvest

**This shape is frozen.** `ba0918-trigger-eval` names these five fields and these two
signal names in its own body, and it is that skill's only source of real-data seeds.
Changing a name here changes something already promised elsewhere.

One JSONL file, one line per utterance, in the order the utterances were made:

```json
{"ts": "ISO 8601 string, zoned", "project": "string — project key", "user_text_masked": "string — the body with mask_secrets applied", "fired_skill": "string — bare skill name | null", "signals": ["string"]}
```

| Signal | Meaning |
|---|---|
| `slash_fired` | The utterance fired a skill by slash command. `fired_skill` names it |
| `correction_after_skill` | The utterance was made after a skill had fired, so it may be the operator correcting what that skill did |

An utterance carries at most one of the two: one that fires a skill is that firing, not
a correction of whatever ran before it.

`ts` is always present and always zoned. The event vocabulary refuses an utterance
whose time carries no zone, so the harvest has no null case; the source schema's `|
null` described a collector that took its time from a neighbouring record.

### The harvest is the one route by which bodies leave a store

Everything else this skill produces is counts and classifications. Here the words
themselves are written to a file, and three guards stand between a run and a written
body. All three fail closed:

1. The output must resolve to a path inside `.agents/tmp` under the working directory.
   Containment is decided on the resolved parent, not on the spelling of the path.
2. The output must be ignored by the repository it sits in, and git itself is asked —
   `git check-ignore --quiet`. Exit 0 is ignored; exit 1 is a decided "not ignored";
   anything higher means git could not decide, and an undecided answer refuses the
   write exactly like a negative one. The repository's ignore file is never read as
   text: anchoring, negation and the directory a pattern is relative to all make a
   hand-rolled reading wrong in the permissive direction.
3. The write replaces the file in one step, so a reader never sees a partly written
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
| Store | Present | text | structural | Abandonment | Notes |
|---|---|---|---|---|---|

## Skill Rankings (by friction score)
| Rank | Skill | Friction Score | Invocations | Confidence | Top Issue | Recommendation |
|---|---|---|---|---|---|---|

## Detailed Findings

### {skill_name}
- **Friction Score:** {0 to 10}
- **Invocations:** {count}
- **Confidence:** High / Medium / Low {and every downgrade applied, with its reason}
- **Retry Rate:** {retry_count / invocation_count}
- **Correction Rate:** {correction_turns / invocation_count}
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
