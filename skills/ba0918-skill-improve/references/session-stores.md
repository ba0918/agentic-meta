# The three session stores, and what each can be read for

Three agent runtimes keep their session history three different ways. This document is
the evidence home: what each store holds, which of the two detection routes it can
actually be read along, and — where a route is missing — the measurement that decides
why the gap is reported instead of filled in.

The reading is separated from the counting for exactly this reason. One adapter per
store turns that store's storage into the same small vocabulary of normalized events,
and every friction signal is computed over the vocabulary alone. An adapter that cannot
observe something declares the gap in its capabilities rather than manufacturing a
substitute.

> Store locations below are written relative to the operator's home directory rather
> than as rooted paths. The self-containment lint reads a rooted home path in any file,
> markdown included, as a reference outside the skill directory, which is also why the
> scripts assemble their default locations at call time instead of writing them whole.

## The two detection routes

| Route | What it reads | Why it exists |
|---|---|---|
| text | The body of what the operator typed. A slash command in it names the skill it fired | The only route that survives in a runtime with no skill tool at all |
| structural | The runtime's own record of a tool call, carrying the skill name as an argument | The only route that sees a skill fired by the agent rather than typed by the operator |

A store reading only one of the two does not find fewer firings — it cannot find one
whole class of them. That is a different measurement, not a smaller number, so the
route travels with every invocation and the store's declaration travels into the
report.

Where a store reads both, the two routes can name the same firing. A slash command the
operator typed is seen along the text route, and the tool call that command produced is
seen along the structural route moments later — one firing observed twice, not two
firings. The pair is folded into one firing, keeping the runtime's own record as the
surviving route, and the count of foldings is reported per skill. The folding is done
in the aggregation and never in an adapter: an adapter is only an ordered source of
events, and deciding that two detections are one firing is a judgement about the order
they arrived in. What that folding is worth, measured, is in
[friction-schema.md](friction-schema.md).

## What each store supports

| Store | Layout | text | structural | Session abandonment | Tool errors |
|---|---|---|---|---|---|
| Claude Code | One directory per project, one JSONL file per session | yes | yes (`Skill` tool, `input.skill`) | inferred | fully readable |
| OpenCode | One SQLite database holding every session | yes | yes (`skill` tool, `state.input.name`) | inferred | fully readable |
| Codex CLI | Rollout JSONL under a date hierarchy | yes | **no — no such tool exists** | recorded by the store itself | **newer logs only** |

Two of those columns disagree in direction, and that is deliberate. Codex is the only
store that writes down a session having been broken off, so the other two have that
inferred for them. Codex is also the only store with no structural route and with a
generation of logs whose errors cannot be read. A store is not uniformly better or
worse than another; each is read for what it actually recorded.

## Claude Code — a directory of session logs

Default location: `.claude/projects` under the operator's home directory. Read by
`scripts/store_claude.py`.

- One directory per project. Its name is the working directory with every character
  outside the key alphabet — ASCII letters, digits, hyphen — replaced by a hyphen. An
  absolute path keeps the leading hyphen its leading separator produced, which is why a
  project key normally begins with one.
- Inside it, one JSONL file per session; one record per line. A record carries its own
  `timestamp`, the session's `sessionId`, and a `message` holding a `role` and a
  `content` that is either a plain string or a list of typed blocks.
- **Structural route**: a `tool_use` block naming the `Skill` tool, whose `input.skill`
  holds the skill name. A name written `plugin:skill` has the prefix stripped, so every
  store meets on the bare name. A value fitting no naming pattern is kept as written
  rather than dropped — the call was observed, and dropping it would undercount a
  firing that happened.
- **Text route**: a slash command inside what the operator typed.
- **Tool errors**: a `tool_result` block with `is_error` set, or a `toolUseResult`
  recorded beside the message with the same flag. The runtime writes the same failure
  in both places, so one record contributes at most one failure; reading each place
  separately would double the count the error rate divides by. A failure names its call
  by identifier, so the tool's name is resolved from the call recorded earlier in the
  session — a failure answering no recorded call stays counted but unnamed.
- **Period filter**: files last written before the period are dropped without being
  opened. A file whose write time cannot be read is kept, since the per-record filter
  still applies and dropping it would silently lose a session.
- **Containment**: every path is resolved and required to stay inside the root it was
  read from, decided by path components rather than by string prefix. A link leading
  out of the root is refused.
- **Abandonment**: not recorded. Inferred from the share of the session's turns that
  failed.

## OpenCode — one database

Default location: `.local/share/opencode/opencode.db` under the operator's home
directory. Read by `scripts/store_opencode.py`.

This runtime keeps no session files at all. One database holds every session, its
messages, and the parts a message is built from, with each body stored as JSON text in
a column. Reading it is a query, not a scan, which is why it cannot share a reader with
the two runtimes that write log files.

Two properties are structural rather than advisory:

- **The connection is opened read-only**, through a URI rather than a promise not to
  issue writes. A stray write fails instead of altering the operator's own history, and
  the database can be read while the runtime is writing to it.
- **The set of tables read is fixed and named in the module**: `project`, `session`,
  `message`, `part`. The same database holds the operator's credentials in tables
  beside these; no statement the module can issue mentions one. That is a structural
  guarantee, not a note asking a later reader to be careful.

Reading details:

- **Times are integer milliseconds.** Read as seconds they would land tens of thousands
  of years in the future, which no period filter would ever exclude, so the unit is
  absorbed in the adapter and the aggregation sees ordinary zoned times.
- **Structural route**: a part with `type == "tool"` and `tool == "skill"`, whose
  `state.input.name` holds the skill name. Names are stored without a plugin prefix
  here, so nothing is stripped.
- **Text route**: a slash command inside the text parts of a message in the operator's
  role.
- **Tool errors**: a tool part whose `state.status` is `error`.
- **Project**: `session.directory` holds a real path, converted to the same slug key
  the other stores meet on.
- **Abandonment**: not recorded. Inferred from the share of the session's turns that
  failed.

## Codex CLI — rollout logs, and three things not inferred

Default location: `.codex/sessions` under the operator's home directory. Read by
`scripts/store_codex.py`.

Each line is a record of three fields — a `timestamp`, a channel `type`, and a
`payload` whose own `type` says what the record is. The session's working directory
comes from the opening `session_meta` record's `cwd`, converted to the slug key.

This store is the reason the capability declaration exists, so its three limits are
recorded here with the measurement behind each. All three are cases where an inference
was available and refused.

### It has no structural route, and a shell command is not a firing

Across the whole of one operator's history — **114,117 records** — the tool names
appearing are 16 kinds such as `exec`, and **not one of them corresponds to a skill
call**. This runtime has no skill tool. The structural route is therefore declared
unavailable rather than reconstructed.

The available inference would be to read a skill firing out of the command string of an
`exec`. It is refused. Of **13,274 exec records, 4,390 — 33% — mention a skill
directory**, and that is a command that read or wrote a skill's files, not one that
fired the skill. The share is high enough to make the inference obviously wrong on its
face, and the consequence is worse than a gap: a friction score built on invented
firings drives an improvement action at a skill nobody ran.

### Error detection reaches only the newer generation of logs

A failure is read from `exec_command_end`, the record that ends a command and carries
its `exit_code`. Older logs have no such record: the failure is written into the body
of a call's output, with no status beside it. Across the same history there are
**1,074 `exec_command_end` records against roughly 17,000 call-output records**, so the
great majority of the history predates the record that makes a failure readable.

That body is not parsed for failure, for the same reason the commands are not parsed
for firings. A reading of older logs under-reports errors and says so.

### The same utterance is written twice, and only one recording is read

The runtime writes the same conversation to two channels: one mirrors the model's own
items, the other mirrors what the interface displayed. A single utterance therefore
appears in both.

Only one recording is read per file, and the one holding what the operator **typed**
wins. A file holding any typed record is read from that recording alone; only a file
holding none falls back to the mirrored one.

The order is settled by measurement, not preference. Across **1,212 files**, the typed
recording holds **1,753 utterances** and the mirrored one **5,083**, and **1,708 of the
typed utterances — 97% — appear verbatim in both**. **1,005 files hold both recordings,
and 991 of those really do duplicate.**

The mirrored recording is thus a superset, not a second source. Its surplus is tool
output and text a harness injected, filed under the operator's role — exactly as
another runtime files its tool answers. Reading both would double nearly every
utterance, fire slash-command detection twice for one command, and manufacture retries
out of nothing. Preferring the mirrored recording is not a way of losing less: it
substitutes the superset for the utterances, putting tool output into the correction
count and into the prompt harvest.

A file that had to fall back says so. Its session identity declares its utterances a
superset, the collector counts those sessions per store, and the report qualifies the
correction counts drawn from that store rather than presenting them as exact.

### It is the one store that records abandonment

`turn_aborted` is this runtime's own record of a turn having been broken off, and no
other store keeps one. It is emitted as abandonment and never as a tool failure: a
failure would inflate exactly the count the other two stores' abandonment is inferred
from, and the two would stop meaning the same thing under the same name.

## Counting turns the same way in all three

A turn is **one thing said by the operator or the agent**. Attachments, system records,
generated titles and the runtime's own bookkeeping are not turns, whatever role they
wear.

This is a deliberate change from the collector being replaced, which counted every line
of a session file as a turn. The reason is that each runtime files its working records
under the same two roles it files speech under, and it does so in different amounts.
In one runtime's history, of **369 records wearing the operator's role, 318 — 86% —
hold nothing but a tool answer**; counting by role alone would put the denominator at
**over seven times** the real conversation. Another runtime keeps its tool calls in a
table of their own and does not swell at all.

Every friction rate divides by turns or by firings. A denominator that is a property of
the store rather than of the conversation makes the three stores' numbers
incomparable, which would defeat the point of reading three stores into one analysis.

Which of a store's records count as speech is that store's adapter's business — a text
block for one, a text part for another, the chosen channel for the third. That a turn
is speech is settled once, in the shared event vocabulary.

## One identity key across three stores

Claude Code keeps only the slug of the working directory and the original path cannot
be recovered from it, so the two stores holding a real path convert theirs the same
way: every character outside the key alphabet becomes a hyphen, nothing is stripped
afterwards, and letter case is carried through. The conversion lives in the shared
vocabulary rather than in each adapter, because two spellings of it would not fail
loudly — they would make one project read as two.

Keys are compared whole, never by substring: one project's key is a substring of every
key that extends it, so a substring comparison makes one project match many.

Because a converted absolute path begins with a hyphen, a project key does too. On the
command line it must therefore be written `--project=KEY`; separated by a space, the
key is read as another option.

## Footnote — a signal recorded but not used

Claude Code's current logs carry two top-level fields the reading does not consume:
`attributionSkill` and `attributionPlugin`, seen **678 and 660 times** respectively in
the measured history. They name a skill directly as the cause of a record, which would
be the most direct attribution signal available anywhere in the three stores.

They are not carried into the normalized events. No other store has anything
corresponding, and a vocabulary kind exists only where at least one store records the
thing and the signals actually consume it — a kind only one store can fill would have
to be faked or left empty by the other two, which is the asymmetry the capability
declaration exists to avoid. Recorded here as a candidate for the day a second store
grows an equivalent, or a signal is designed that consumes a single-store attribution
honestly.
