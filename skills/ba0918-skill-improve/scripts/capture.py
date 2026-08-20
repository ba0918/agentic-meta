#!/usr/bin/env python3
"""Harvests what the operator actually typed, masked, as one line per utterance.

This is the only route by which message bodies leave a session store. Everything
else this skill produces is counts and classifications; here the words themselves
are written to a file, and every guard below exists because of that difference.

The record shape is fixed by its reader. The skill that measures whether skills
fire when they should names these five fields and these two signal names in its own
body, so a change here is a change to something already promised elsewhere. The
fields are `ts`, `project`, `user_text_masked`, `fired_skill` and `signals`; the
signals are `slash_fired`, for an utterance that fired a skill by slash command,
and `correction_after_skill`, for one made after a skill had fired.

**The masking is a blocklist and is therefore not complete.** It replaces what it
recognises — keys, tokens, private keys, addresses, home paths — and a credential
shaped like none of those survives it. A harvested file is sensitive material even
after masking, and whoever reads one is told to treat it that way and delete it.

Four guards stand between a run and a written body, and all four fail closed:

The output must resolve to a path inside `.agents/tmp` under the working directory.
Containment is decided on the resolved parent, not on the spelling of the path: a
neighbour directory whose name merely extends the allowed one shares its prefix,
and a link inside the allowed directory can lead anywhere.

The output must be ignored by the repository it sits in, and that is asked of git
itself. `git check-ignore --quiet` answers 0 for ignored and 1 for not ignored, and
anything above that means git could not answer at all — an unreadable configuration
inside a sandbox, or no repository there. Every non-zero answer refuses the write,
including the ones that only mean "unknown", and an unknown answer also prints what
to do about it. The repository's ignore file is never read as text: anchoring,
negation and the directory a pattern is relative to all make a hand-rolled reading
wrong in the permissive direction.

The write lands on a neighbouring name and replaces the file in one step, so a
reader never sees a partly written harvest and a failed run never destroys a
previous one. That neighbour is created new or the run refuses: containment is
decided on the name the harvest is finally given, and a link left waiting under the
neighbour's name would otherwise carry the bodies wherever it points.
"""

import argparse
import datetime
import json
import os
import pathlib
import subprocess
import sys
import typing

import stores
from events import SessionIdentity, SkillInvocation, StoreUnreadable, UserText
from secret_detect import mask_secrets
from store_shared import slash_skill_in

EXIT_OK = 0
EXIT_REFUSED = 2

DEFAULT_DAYS = 30

# The fields of one harvested line, in the order they are written. Named by the
# skill that reads this file, and not ours alone to change.
RECORD_FIELDS = ("ts", "project", "user_text_masked", "fired_skill", "signals")

# The utterance fired a skill by slash command.
SLASH_FIRED = "slash_fired"

# The utterance was made after a skill had fired, so it may be the operator
# correcting what the skill did.
CORRECTION_AFTER_SKILL = "correction_after_skill"

# The only directory a harvest may be written into, under the working directory.
ALLOWED_OUTPUT_DIRECTORY = (".agents", "tmp")

NO_PROJECT = ""

# The path to nothing is taken from the runtime rather than written: the
# self-containment lint reads a rooted path in any file as a reference outside the
# skill directory.
UNDECIDABLE_HINT = (
    "git could not decide whether the path is ignored (exit {code}). A sandbox that"
    " cannot read the global git configuration is the usual cause: re-run with"
    " GIT_CONFIG_GLOBAL=" + os.devnull + ", or from inside the repository the output"
    " belongs to."
)


def allowed_base() -> pathlib.Path:
    """The one directory a harvest may be written into, under the working directory."""
    return pathlib.Path.cwd().joinpath(*ALLOWED_OUTPUT_DIRECTORY)


def capture_records(stream: typing.Iterable) -> list[dict[str, typing.Any]]:
    """One record per utterance, in the order the utterances were made.

    The skill an utterance fires is read out of the utterance itself rather than
    taken from the firing event an adapter yields next to it. The two agree — that
    firing is derived from the same text — but deriving it here keeps a record
    independent of the order events arrive in, which is what a file promised to
    another skill should be.

    A session announcement clears the skill last fired, so an utterance opening one
    session is never read as a correction of what a previous session did.
    """
    records: list[dict[str, typing.Any]] = []
    project = NO_PROJECT
    last_skill: str | None = None
    for event in stream:
        if isinstance(event, SessionIdentity):
            project = event.project
            last_skill = None
        elif isinstance(event, SkillInvocation):
            last_skill = event.skill
        elif isinstance(event, UserText):
            fired = slash_skill_in(event.text)
            signals: list[str] = []
            if fired is not None:
                signals.append(SLASH_FIRED)
                last_skill = fired
            elif last_skill is not None:
                signals.append(CORRECTION_AFTER_SKILL)
            records.append({
                "ts": event.at.isoformat(),
                "project": project,
                "user_text_masked": mask_secrets(event.text),
                "fired_skill": fired,
                "signals": signals,
            })
    return records


def validate_output_path(output: str, base: pathlib.Path) -> pathlib.Path | None:
    """The resolved output path, or None where it does not stay inside base.

    The file itself need not exist yet, so it is the parent directory that is
    resolved, and resolving it is what makes a link inside the allowed directory
    unable to lead out of it. Containment is then decided by path components rather
    than by string prefix, because a neighbour whose name extends the allowed one
    shares its prefix.

    This decides a name and nothing else. The neighbouring name the atomic write
    lands on first is never resolved here, so whatever may already sit at that name
    is decided where it is opened rather than here.

    A name that would resolve to a directory rather than to a new file is refused:
    the containment decision is lexical and would otherwise accept the allowed
    directory itself as a place to write a file.
    """
    try:
        resolved_base = base.resolve()
    except (OSError, ValueError):
        return None
    candidate = pathlib.Path(output)
    if candidate.name in ("", ".", ".."):
        return None
    try:
        resolved_parent = candidate.parent.resolve(strict=True)
    except (OSError, ValueError):
        return None
    final = resolved_parent / candidate.name
    if not final.is_relative_to(resolved_base) or final.is_dir():
        return None
    return final


def output_is_git_ignored(path: pathlib.Path) -> bool:
    """Whether git itself says the path is ignored, refusing every other answer.

    Exit 0 is ignored and allows the write. Exit 1 is a decided "not ignored". Any
    higher exit means git could not decide — no repository, or a configuration it
    could not read — and an undecided answer is refused like a negative one, since
    the whole point of the gate is that bodies are never written where they could
    be committed. The undecided case also says what to do about it, because a
    silent refusal there reads exactly like a correctly refused tracked path.
    """
    try:
        answered = subprocess.run(
            ["git", "check-ignore", "--quiet", str(path)],
            cwd=str(path.parent),
            capture_output=True,
        )
    except (OSError, ValueError):
        return False
    if answered.returncode == 0:
        return True
    if answered.returncode == 1:
        return False
    print(
        "[capture] " + UNDECIDABLE_HINT.format(code=answered.returncode),
        file=sys.stderr,
    )
    return False


def write_records(records: list[dict[str, typing.Any]], path: pathlib.Path) -> None:
    """Write the harvest as one line per record, replacing the file in one step.

    The neighbour the write lands on before the replacement is created new or not at
    all. Refusing to follow a link stops one planted under that name from carrying
    the bodies wherever it points, and refusing an existing file stops one planted
    there from being written through — neither is covered by the containment
    decision, which is made on the name the harvest is finally given.

    Anything already at the neighbour's name is refused rather than unlinked first.
    Removing it would let a planted link be replaced and the run go on looking
    ordinary, and a gate over message bodies must not end in an ordinary-looking
    run. A leftover from a killed run is refused for the same reason, and the
    refusal says what to remove.
    """
    partial = str(path) + ".tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    opened = os.open(partial, flags, 0o600)
    try:
        with os.fdopen(opened, "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        os.replace(partial, str(path))
    except BaseException:
        try:
            os.unlink(partial)
        except FileNotFoundError:
            pass
        raise


def parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    """The command line this entry point accepts.

    The output is declared optional and required afterwards, so a run without one
    is refused the same way a run pointed outside the allowed directory is, rather
    than by a different exit path.
    """
    parser = argparse.ArgumentParser(
        description="Harvest masked operator utterances from the session stores",
    )
    parser.add_argument(
        "--store", default=stores.EVERY_STORE,
        help="which store to read: one of " + ", ".join(stores.SELECTABLE),
    )
    for kind in stores.REGISTRY:
        parser.add_argument(
            kind.location_flag, default=None,
            help=f"where to read the {kind.name} store (default: its own location)",
        )
    parser.add_argument(
        "--days", type=int, default=DEFAULT_DAYS,
        help=f"how many days back to read (default: {DEFAULT_DAYS})",
    )
    parser.add_argument(
        "--project", default=None,
        help="which project to read, written as --project=KEY because a project key"
             " begins with a hyphen (default: the working directory)",
    )
    parser.add_argument(
        "--all-projects", action="store_true", default=False,
        help="read every project rather than one",
    )
    parser.add_argument(
        "--output", default=None,
        help="where to write the harvest: a git-ignored path under "
             + os.path.join(*ALLOWED_OUTPUT_DIRECTORY),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Harvest the selected stores into one file, refusing any unsafe output."""
    arguments = parse_arguments(argv)
    base = allowed_base()
    if not arguments.output:
        print(f"error: an --output under {base} is required", file=sys.stderr)
        return EXIT_REFUSED
    try:
        stores.selected_names(arguments.store)
    except ValueError as refusal:
        print(f"error: {refusal}", file=sys.stderr)
        return EXIT_REFUSED

    resolved = validate_output_path(arguments.output, base)
    if resolved is None:
        print(f"error: --output must be a new file under {base}", file=sys.stderr)
        return EXIT_REFUSED
    if not output_is_git_ignored(resolved):
        print(
            f"error: refusing to write message bodies to {resolved}, which the"
            " repository does not ignore",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    now = datetime.datetime.now(datetime.timezone.utc)
    readings = stores.build_stores(
        arguments.store,
        stores.given_locations(arguments),
        since=now - datetime.timedelta(days=arguments.days),
        project=stores.chosen_project(arguments.project, arguments.all_projects),
    )
    harvested: list[dict[str, typing.Any]] = []
    for reading in readings:
        if not reading.present:
            print(
                f"[capture] the {reading.name} store was not found at"
                f" {reading.location} — it was read as empty and the run went on",
                file=sys.stderr,
            )
        try:
            harvested.extend(capture_records(reading.store.events()))
        except StoreUnreadable as refusal:
            print(
                f"[capture] the {reading.name} store at {reading.location} could not"
                f" be read ({refusal}) — nothing was harvested from it and the run"
                " went on",
                file=sys.stderr,
            )

    try:
        write_records(harvested, resolved)
    except OSError as refusal:
        print(
            f"error: refusing to write message bodies to {resolved}: the neighbouring"
            f" name it is written through could not be created ({refusal.strerror})."
            " Whatever is already at that name is not written through — remove it and"
            " run again.",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    print(
        f"[capture] wrote {len(harvested)} masked records to {resolved}."
        " The masking is a blocklist and is not complete: treat the file as"
        " sensitive and delete it when done.",
        file=sys.stderr,
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
