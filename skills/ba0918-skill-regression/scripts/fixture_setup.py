#!/usr/bin/env python3
"""Validation of a scenario declaration and its deterministic materialization.

A scenario used to carry only the contents of the files it needed, and setting up
a run was left to whoever performed it. The premises that were not written down —
the order files were touched in, how many there were, what state git was in —
were then filled in at each runner's discretion, and scenarios passed without
ever reaching the branch they were written to exercise.

This module takes those premises as declarations and reproduces them the same way
every time. Input files are real files under an inputs directory rather than
strings inside the declaration, so a scenario stays readable and its inputs stay
diffable.

CLI:
  python3 fixture_setup.py --validate PATH...
      read scenario files and report every violation (exit 1 if any)
  python3 fixture_setup.py --materialize SCENARIO INPUTS DEST
      set DEST up from the scenario and print the baseline hashes and env as JSON
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yaml_subset  # noqa: E402

TIERS = ("standard", "high", "economy")
ISOLATIONS = ("worktree", "none")
SCENARIO_KEYS = (
    "skill", "id", "title", "source", "executor_tier", "isolation", "prompt",
    "expected_output", "expectations", "exercises", "files", "mtimes", "env",
    "git", "notes",
)
REQUIRED_KEYS = ("skill", "id", "prompt", "expectations")
# Keys left out of the scenario content hash. `exercises` declares which surface
# files a scenario touches; it changes what a change reaches, never what the
# scenario measures. Hashing it would make adding a declaration cost a rerun.
SHA_EXCLUDED_KEYS = ("exercises",)
EXPECTATION_KEYS = ("text", "critical", "assert")
FILE_ENTRY_KEYS = ("from", "to")
GIT_KEYS = ("init", "commit", "remote", "branch", "message", "commits")
COMMIT_KEYS = ("files", "message")

# A scenario that starts from a later phase needs an implementation commit after
# the baseline, with its own text naming that baseline. A sha is only known once
# the tree exists, so declarations write a placeholder and substitution fills it
# in. The loose pattern catches misspellings: left in place, the literal text
# would send the run down a "cannot resolve the sha" path instead of the one
# under test.
_SHA_TOKEN = re.compile(r"\{\{fixture:sha:[^}]*\}\}")
_SHA_TOKEN_STRICT = re.compile(r"\{\{fixture:sha:(?:baseline|commits\[(\d+)\])\}\}")

DEFAULT_BRANCH = "master"
DEFAULT_MESSAGE = "fixture baseline"

# A sentinel for the baseline: a declared path that is not there as an ordinary
# file, which happens when the runtime shadows a sensitive-looking name.
NOT_A_REGULAR_FILE = "NOT-A-REGULAR-FILE"

# Committing needs an identity, and the surrounding machine's configuration would
# otherwise decide the branch name, the signing setting and the hook path — all
# of which would make the same declaration materialize differently elsewhere.
_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "fixture",
    "GIT_AUTHOR_EMAIL": "fixture@invalid",
    "GIT_COMMITTER_NAME": "fixture",
    "GIT_COMMITTER_EMAIL": "fixture@invalid",
    "GIT_TERMINAL_PROMPT": "0",
}


class MaterializeError(Exception):
    """The declaration could not be turned into the environment it describes."""


def _err(where, message):
    return f"{where}: {message}"


def _unsafe_path(path, allow_git_metadata=False):
    """Why a declared path cannot be used, or None when it is fine.

    Allowing `.git/` would let materialization alone reach outside the isolated
    area through a hook. Declaration and materialization consult this one rule so
    they cannot disagree.
    """
    if not isinstance(path, str) or not path.strip():
        return "is not a non-empty string"
    segments = path.split("/")
    if os.path.isabs(path) or ".." in segments:
        return "points outside the isolated area"
    if not allow_git_metadata and any(s.lower() == ".git" for s in segments):
        # A case-insensitive filesystem lands `.Git/hooks/` in `.git/hooks/` too,
        # so an exact match would miss the block on exactly those machines.
        return "points into the git metadata area (.git/)"
    return None


def file_entries(files):
    """Normalize the `files` declaration into a list of (source, destination)."""
    entries = []
    for item in files or []:
        if isinstance(item, str):
            entries.append((item, item))
        elif isinstance(item, dict):
            entries.append((item.get("from"), item.get("to")))
        else:
            entries.append((None, None))
    return entries


def _validate_files(where, files, label="files"):
    errors = []
    if not isinstance(files, list):
        return [_err(where, f"{label} must be a list")], []
    destinations = []
    for index, item in enumerate(files):
        at = f"{label}[{index}]"
        if isinstance(item, dict):
            for key in item:
                if key not in FILE_ENTRY_KEYS:
                    errors.append(_err(where, f"{at}: unknown key {key!r}"))
            source, destination = item.get("from"), item.get("to")
            if source is None or destination is None:
                errors.append(_err(where, f"{at}: needs both 'from' and 'to'"))
                continue
        elif isinstance(item, str):
            source = destination = item
        else:
            errors.append(_err(where, f"{at}: must be a path or a from/to mapping"))
            continue
        unsafe = _unsafe_path(source)
        if unsafe:
            errors.append(_err(where, f"{at}: the source path {unsafe}"))
        unsafe = _unsafe_path(destination)
        if unsafe:
            errors.append(_err(where, f"{at}: the destination path {unsafe}"))
        destinations.append(destination)
    for destination in sorted({d for d in destinations if destinations.count(d) > 1}):
        errors.append(_err(where, f"{label}: {destination!r} is declared more than once"))
    return errors, destinations


def _validate_expectations(where, expectations):
    if not isinstance(expectations, list) or not expectations:
        return [_err(where, "expectations must be a non-empty list")]
    errors = []
    critical_seen = False
    for index, item in enumerate(expectations):
        at = f"expectations[{index}]"
        if not isinstance(item, dict):
            errors.append(_err(where, f"{at}: must be a mapping"))
            continue
        for key in item:
            if key not in EXPECTATION_KEYS:
                errors.append(_err(where, f"{at}: unknown key {key!r}"))
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            errors.append(_err(where, f"{at}: needs a non-empty 'text'"))
        critical = item.get("critical")
        if critical is not None and not isinstance(critical, bool):
            errors.append(_err(where, f"{at}: 'critical' must be true or false"))
        critical_seen = critical_seen or critical is True
    if not critical_seen:
        # Passing means every critical expectation holds. With none declared a
        # scenario passes while asserting nothing.
        errors.append(_err(where, "at least one expectation must be critical"))
    return errors


def _validate_git(where, git, destinations):
    errors = []
    if not isinstance(git, dict):
        return [_err(where, "git must be a mapping")]
    for key in git:
        if key not in GIT_KEYS:
            errors.append(_err(where, f"unknown git key {key!r}"))
    if not git.get("init"):
        for dependent in ("commit", "remote", "branch", "message", "commits"):
            if git.get(dependent):
                errors.append(_err(where, f"git.{dependent} needs init: true"))
    remote = git.get("remote")
    if remote is not None and not isinstance(remote, str):
        errors.append(_err(where, "git.remote must be a string"))
    branch = git.get("branch")
    if branch is not None and (not isinstance(branch, str) or not branch.strip()):
        errors.append(_err(where, "git.branch must be a non-empty string"))

    commit = git.get("commit")
    if isinstance(commit, list):
        if not commit:
            errors.append(_err(
                where, "an empty git.commit is ambiguous — use true for everything, "
                       "or drop the key to create no baseline commit"))
        for path in commit:
            if not isinstance(path, str):
                errors.append(_err(where, "each git.commit entry must be a string"))
            elif path not in destinations:
                errors.append(_err(where, f"git.commit[{path!r}] names no declared file"))
    elif commit is not None and not isinstance(commit, bool):
        errors.append(_err(where, "git.commit must be true or a list of paths"))

    message = git.get("message")
    if message is not None:
        if not isinstance(message, str) or not message.strip():
            errors.append(_err(where, "git.message must be a non-empty string"))
        if not commit:
            errors.append(_err(where, "git.message needs commit"))

    commits = git.get("commits")
    if commits is not None:
        if not isinstance(commits, list) or not commits:
            errors.append(_err(where, "git.commits must be a non-empty list"))
        else:
            for index, entry in enumerate(commits):
                at = f"git.commits[{index}]"
                if not isinstance(entry, dict):
                    errors.append(_err(where, f"{at}: must be a mapping"))
                    continue
                for key in entry:
                    if key not in COMMIT_KEYS:
                        errors.append(_err(where, f"{at}: unknown key {key!r}"))
                entry_errors, _ = _validate_files(where, entry.get("files"), f"{at}.files")
                errors += entry_errors
                if not isinstance(entry.get("message"), str) or not entry["message"].strip():
                    errors.append(_err(where, f"{at}: needs a non-empty 'message'"))
    return errors


def _validate_exercises(where, exercises):
    """Check the shape of `exercises` only.

    Whether a declared path is on the current behaviour surface belongs to
    whatever computes that surface. Deciding it here would make validating one
    scenario depend on the state of the whole repository.
    """
    if not isinstance(exercises, list) or not all(isinstance(p, str) for p in exercises):
        return [_err(where, "exercises must be a list of strings")]
    errors = []
    for path in exercises:
        if os.path.isabs(path) or ".." in path.split("/"):
            errors.append(_err(where, f"exercises path {path!r} must be repository-relative"))
        elif not path.startswith("skills/"):
            errors.append(_err(where, f"exercises path {path!r} must be under skills/"))
    return errors


def validate(scenario, source="scenario"):
    """Every violation in a scenario declaration. An empty list means it is accepted."""
    if not isinstance(scenario, dict):
        return [_err(source, "a scenario declaration is a mapping")]
    errors = []
    # A key silently ignored is the most dangerous failure shape: a premise the
    # author meant to pin is filled in at run time instead. Typos included.
    for key in scenario:
        if key not in SCENARIO_KEYS:
            errors.append(_err(
                source, f"unknown key {key!r} (accepted: {', '.join(SCENARIO_KEYS)})"))
    for key in REQUIRED_KEYS:
        value = scenario.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(_err(source, f"{key} is missing"))

    tier = scenario.get("executor_tier")
    if tier is not None and tier not in TIERS:
        errors.append(_err(source, f"executor_tier must be one of {', '.join(TIERS)}"))
    isolation = scenario.get("isolation")
    if isolation is not None and isolation not in ISOLATIONS:
        errors.append(_err(source, f"isolation must be one of {', '.join(ISOLATIONS)}"))

    file_errors, destinations = _validate_files(source, scenario.get("files") or [])
    errors += file_errors

    if scenario.get("expectations") is not None:
        errors += _validate_expectations(source, scenario["expectations"])

    mtimes = scenario.get("mtimes") or {}
    if not isinstance(mtimes, dict):
        errors.append(_err(source, "mtimes must be a mapping"))
    else:
        for path, offset in mtimes.items():
            if path not in destinations:
                errors.append(_err(source, f"mtimes[{path!r}] names no declared file"))
            if not isinstance(offset, int) or isinstance(offset, bool):
                errors.append(_err(
                    source, f"mtimes[{path!r}] must be whole seconds from the base time"))

    env = scenario.get("env") or {}
    if not isinstance(env, dict):
        errors.append(_err(source, "env must be a mapping"))
    else:
        for name, value in env.items():
            if not isinstance(value, str):
                errors.append(_err(source, f"env[{name!r}] must be a string"))

    if scenario.get("git") is not None:
        errors += _validate_git(source, scenario["git"], destinations)
    if scenario.get("exercises") is not None:
        errors += _validate_exercises(source, scenario["exercises"])
    return errors


def scenario_sha256(scenario):
    """The canonical content hash of a scenario, excluding SHA_EXCLUDED_KEYS.

    The rerun guard and the lock's carry-over both use this one function. Two
    implementations would drift into disagreeing about whether a declaration-only
    edit needs a rerun.
    """
    payload = {k: v for k, v in scenario.items() if k not in SHA_EXCLUDED_KEYS}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def load_scenario(path):
    """Read one scenario file. Raises MaterializeError when it cannot be read."""
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise MaterializeError(f"{path}: cannot be read ({exc})") from exc
    try:
        return yaml_subset.load(text)
    except yaml_subset.YamlSubsetError as exc:
        raise MaterializeError(f"{path}: {exc}") from exc


def _run_git(args, cwd):
    env = dict(os.environ)
    env.update(_GIT_ENV)
    return subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True,
                          text=True, env=env)


def _head_sha(dest):
    return _run_git(["rev-parse", "HEAD"], dest).stdout.strip()


def _read_input(inputs_root, source, at):
    root = os.path.abspath(inputs_root)
    unsafe = _unsafe_path(source)
    if unsafe:
        raise MaterializeError(f"{at}: the source path {unsafe}")
    resolved = os.path.normpath(os.path.join(root, source))
    if os.path.commonpath([root, resolved]) != root:
        raise MaterializeError(f"{at}: the source path leaves the inputs directory")
    if not os.path.isfile(resolved):
        raise MaterializeError(f"{at}: no input file at {source!r}")
    with open(resolved, encoding="utf-8") as handle:
        return handle.read()


def _write(dest, path, content):
    unsafe = _unsafe_path(path)
    if unsafe:
        raise MaterializeError(f"the destination path {path!r} {unsafe}")
    full = os.path.join(dest, path)
    os.makedirs(os.path.dirname(full) or dest, exist_ok=True)
    with open(full, "w", encoding="utf-8") as handle:
        handle.write(content)


def _substitute_sha(content, path, baseline_sha, commit_shas):
    def replace(match):
        strict = _SHA_TOKEN_STRICT.fullmatch(match.group(0))
        if strict is None:
            raise MaterializeError(
                f"{path}: {match.group(0)} is not a placeholder this reader knows")
        index = strict.group(1)
        if index is None:
            if not baseline_sha:
                raise MaterializeError(f"{path}: no baseline commit to resolve against")
            return baseline_sha
        position = int(index)
        if position >= len(commit_shas):
            raise MaterializeError(f"{path}: there is no commits[{position}]")
        return commit_shas[position]

    return _SHA_TOKEN.sub(replace, content)


def materialize(scenario, dest, inputs_root, base_time=None):
    """Set `dest` up from the scenario and return {dir, baseline, env, git, unmaterialized}.

    `baseline` maps each declared destination to the sha256 of what actually
    landed, which is what corroborates that a run edited nothing. Times are
    stamped relative to `base_time` so a declaration does not go stale.
    """
    if base_time is None:
        base_time = time.time()
    git = scenario.get("git") or {}
    env = scenario.get("env") or {}
    mtimes = scenario.get("mtimes") or {}

    # Read every input before writing anything: failing part way would leave the
    # isolated area in a state that matches none of the declarations.
    staged = [(destination, _read_input(inputs_root, source, f"files[{index}]"))
              for index, (source, destination) in enumerate(file_entries(scenario.get("files")))]
    commit_stages = []
    for c_index, entry in enumerate(git.get("commits") or []):
        stage = [(destination, _read_input(inputs_root, source,
                                           f"git.commits[{c_index}].files[{f_index}]"))
                 for f_index, (source, destination) in enumerate(file_entries(entry.get("files")))]
        commit_stages.append((stage, entry.get("message") or DEFAULT_MESSAGE))

    # The same destination can be written by several declarations in turn; the
    # expected content is whatever the last writer left.
    expected = {}
    os.makedirs(dest, exist_ok=True)
    for path, content in staged:
        _write(dest, path, content)
        expected[path] = content

    git_state = {}
    baseline_sha, commit_shas = None, []
    if git.get("init"):
        branch = git.get("branch") or DEFAULT_BRANCH
        _run_git(["init", "-q", "-b", branch], dest)
        git_state["init"] = True
        git_state["branch"] = branch
        if git.get("remote"):
            _run_git(["remote", "add", "origin", git["remote"]], dest)
            git_state["remote"] = git["remote"]
        commit = git.get("commit")
        if commit:
            # A list names what belongs in the baseline; the rest stays untracked,
            # which is how "there is uncommitted work" becomes a declarable premise.
            # The list form is separated by `--` so a leading-dash filename cannot
            # be read as an option.
            args = ["add", "-A"] if commit is True else ["add", "--"] + list(commit)
            added = _run_git(args, dest)
            if added.returncode != 0:
                # Left unchecked, the --allow-empty baseline below would still be
                # made and the run would proceed with nothing actually tracked.
                raise MaterializeError(
                    f"git.commit was refused by add: "
                    f"{(added.stderr or added.stdout).strip()[:200]}")
            # --allow-empty so that a scenario declaring no files still gets the
            # baseline its "the tree is clean" premise rests on.
            result = _run_git(
                ["commit", "-q", "-m", git.get("message") or DEFAULT_MESSAGE,
                 "--allow-empty"], dest)
            git_state["commit"] = result.returncode == 0
            baseline_sha = _head_sha(dest)
            git_state["baseline"] = baseline_sha
        for index, (stage, message) in enumerate(commit_stages):
            for path, content in stage:
                _write(dest, path, content)
                expected[path] = content
            added = _run_git(["add", "--"] + [p for p, _ in stage], dest)
            if added.returncode != 0:
                raise MaterializeError(
                    f"git.commits[{index}] was refused by add: "
                    f"{(added.stderr or added.stdout).strip()[:200]}")
            # No --allow-empty here: an empty commit means the implementation the
            # scenario meant to seed is not in the history, which must not pass.
            result = _run_git(["commit", "-q", "-m", message], dest)
            if result.returncode != 0:
                raise MaterializeError(
                    f"git.commits[{index}] could not be committed: "
                    f"{(result.stderr or result.stdout).strip()[:200]}")
            commit_shas.append(_head_sha(dest))
        if commit_shas:
            git_state["commits"] = commit_shas

    # Placeholders resolve once every commit exists. Validation has already kept
    # these files out of the commits, so rewriting them leaves the tree clean.
    for path, content in list(expected.items()):
        if not _SHA_TOKEN.search(content):
            continue
        resolved = _substitute_sha(content, path, baseline_sha, commit_shas)
        _write(dest, path, resolved)
        expected[path] = resolved

    # Baseline hashes come from what is on disk, not from the declaration. A
    # runtime can shadow a sensitive-looking name and drop the write silently;
    # hashing the declaration would then judge "nothing was edited" against a
    # file that never existed.
    baseline = {}
    unmaterialized = []
    for path, content in expected.items():
        full = os.path.join(dest, path)
        wanted = content.encode("utf-8")
        actual = None
        if os.path.isfile(full):
            with open(full, "rb") as handle:
                actual = handle.read()
        if actual == wanted:
            baseline[path] = hashlib.sha256(wanted).hexdigest()
        else:
            unmaterialized.append(path)
            baseline[path] = (hashlib.sha256(actual).hexdigest()
                              if actual is not None else NOT_A_REGULAR_FILE)

    # Times are stamped last: applying them earlier would let the writes above
    # roll the order back.
    for path, offset in mtimes.items():
        full = os.path.join(dest, path)
        if os.path.isfile(full):
            stamp = base_time + offset
            os.utime(full, (stamp, stamp))

    return {
        "dir": os.path.abspath(dest),
        "baseline": baseline,
        "env": dict(env),
        "git": git_state,
        "unmaterialized": unmaterialized,
    }


def main(argv):
    args = list(argv)
    if args[:1] == ["--validate"]:
        failed = False
        for path in args[1:]:
            try:
                scenario = load_scenario(path)
            except MaterializeError as exc:
                print(exc, file=sys.stderr)
                failed = True
                continue
            for message in validate(scenario, path):
                print(message, file=sys.stderr)
                failed = True
        return 1 if failed else 0
    if args[:1] == ["--materialize"] and len(args) == 4:
        scenario = load_scenario(args[1])
        errors = validate(scenario, args[1])
        if errors:
            for message in errors:
                print(message, file=sys.stderr)
            return 1
        result = materialize(scenario, args[3], args[2])
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except MaterializeError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
