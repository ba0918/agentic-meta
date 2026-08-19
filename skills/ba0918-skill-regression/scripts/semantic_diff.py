#!/usr/bin/env python3
"""Building the input a semantic judge reads, and the file it fills in.

A judge is shown a before and an after, so the content the lock recorded has to be
brought back, and that is the one thing only git history can supply. The lock
itself is deliberately free of any reading of history — its answers come from
comparing content against content — so the dependency is confined here and does
not leak into it.

Restoration is by **content hash, never by commit position**. The lock records a
verification by content and is not tied to any commit, so working backwards from
"the commit around when it was verified" would grab the wrong base whenever the
history moved on by another route afterwards.

A file whose earlier content cannot be restored pre-fills `unclear` for the
scenarios it reaches. Left as a blank for the judge to fill, it would be filled
in — and the judge's reach would grow to declaring safe something it never saw.

CLI:
  python3 semantic_diff.py SKILL [--skeleton FILE] [root]
      print the judging input — the canonical diff hash, the unified diff, and the
      skeleton of the judgment file. --skeleton also writes the skeleton to a file.
"""
import difflib
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lock  # noqa: E402

# How far back to look for one file. Walking an unbounded history would make
# assembling the input the slow part for a much-cited contract. Reaching the
# limit without a match falls to "not restorable", which is the safe side.
MAX_REVISIONS = 200

UNRESTORABLE_RATIONALE = (
    "the earlier content could not be restored from history, "
    "so the difference was never seen"
)


def _git(root, args):
    """Call git with an argument list, never through a shell. None on failure."""
    try:
        proc = subprocess.run(["git", "-C", root] + list(args),
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              check=False)
    except OSError:
        return None
    return proc.stdout if proc.returncode == 0 else None


def _revisions(root, rel, limit):
    """Commits touching `rel`, newest first. Empty when there is no history."""
    out = _git(root, ["rev-list", f"--max-count={limit}", "HEAD", "--", rel])
    return [] if out is None else out.decode("utf-8", "replace").split()


def restore_base(root, rel, recorded_sha, max_revisions=MAX_REVISIONS):
    """The version whose content matches what the lock recorded, or None.

    A version that is not valid UTF-8 also answers None: the judge reads a text
    difference, and content that cannot be read is, mechanically, the same
    situation as content that could not be restored.
    """
    if recorded_sha == lock.MISSING:
        return None
    for revision in _revisions(root, rel, max_revisions):
        blob = _git(root, ["show", f"{revision}:{rel}"])
        if blob is None or hashlib.sha256(blob).hexdigest() != recorded_sha:
            continue
        try:
            return blob.decode("utf-8")
        except UnicodeDecodeError:
            return None
    return None


def current_text(root, rel, current_hashes):
    """The after side: empty for a file no longer on the surface, None if unreadable.

    Membership of the current surface decides this, not presence on disk. An edit
    that unlinks a reference leaves the file where it is while it drops off the
    surface; judged by presence, that change would be named among the changed
    files and then show an empty body, which a judge reads as unaffected. A file
    off the surface no longer contributes to the skill's behaviour, so drawing it
    as a full deletion is also the accurate picture.
    """
    if current_hashes.get(rel, lock.MISSING) == lock.MISSING:
        return ""
    try:
        with open(os.path.join(root, rel), encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError):
        return None


def unified_diff(rel, base, current):
    """One file's unified diff, always closed with a newline."""
    body = "".join(difflib.unified_diff(
        base.splitlines(keepends=True), current.splitlines(keepends=True),
        fromfile=f"a/{rel}", tofile=f"b/{rel}"))
    if body and not body.endswith("\n"):
        body += "\n"
    return body


def build_skeleton(skill, diff_sha256, scenario_ids, unclear_ids):
    """The judgment file to fill in. A blank verdict is refused when it is read back."""
    return {
        "skill": skill,
        "diff_sha256": diff_sha256,
        "model": "",
        "scenarios": {
            scenario_id: (
                {"verdict": lock.VERDICT_UNCLEAR, "rationale": UNRESTORABLE_RATIONALE}
                if scenario_id in unclear_ids
                else {"verdict": "", "rationale": ""}
            )
            for scenario_id in scenario_ids
        },
    }


def build_input(root, skill, entry):
    """Assemble everything the judge needs.

    Which files changed and which scenarios they reach are both answered by the
    lock's own rules. A judging input that saw a different set from the one the
    check reports would put "what needs rerunning" and "what was judged" out of
    step with each other.
    """
    surface = lock.skill_surface(root, skill)
    current = lock.file_hashes(root, surface)
    recorded = entry.get("file_sha256") or {}
    severity, changed = lock.stale_severity(
        recorded, current, entry.get("structural_sha256") or {},
        lock.structural_hashes(root, surface), own_prefix=f"skills/{skill}/")
    blocks, unrestorable = [], []
    for rel in changed:
        recorded_sha = recorded.get(rel, lock.MISSING)
        # A file that was not on the previous surface is not "unrestorable":
        # there is no earlier content for it to have.
        base = "" if recorded_sha == lock.MISSING else restore_base(root, rel, recorded_sha)
        after = current_text(root, rel, current)
        if base is None or after is None:
            unrestorable.append(rel)
            blocks.append(f"--- {rel}\n({UNRESTORABLE_RATIONALE})\n")
            continue
        blocks.append(unified_diff(rel, base, after))
    scenarios = lock.load_scenarios(root, skill)
    recorded_scenarios = entry.get("scenarios")
    impacted = lock.impacted_scenarios(skill, surface, scenarios, changed,
                                       recorded_scenarios)
    unclear = set(lock.impacted_scenarios(skill, surface, scenarios, unrestorable,
                                          recorded_scenarios))
    diff_sha256 = lock.semantic_diff_sha256(recorded, current)
    return {
        "severity": severity,
        "changed": changed,
        "diff": "".join(blocks),
        "unrestorable": unrestorable,
        "diff_sha256": diff_sha256,
        "scenarios": impacted,
        "total": len(scenarios),
        "skeleton": build_skeleton(skill, diff_sha256, impacted, unclear),
    }


def main(argv):
    args = list(argv)
    skeleton_path = None
    if "--skeleton" in args:
        index = args.index("--skeleton")
        skeleton_path = args[index + 1]
        del args[index:index + 2]
    if not args:
        print(__doc__, file=sys.stderr)
        return 2
    skill = args.pop(0)
    root = args[0] if args else os.getcwd()
    state = lock.load(root)
    entry = (state.get("skills") or {}).get(skill)
    if entry is None:
        print(f"{skill}: no verification record to compare against", file=sys.stderr)
        return 1
    built = build_input(root, skill, entry)
    if skeleton_path:
        with open(skeleton_path, "w", encoding="utf-8") as handle:
            json.dump(built["skeleton"], handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    print(json.dumps(built, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
