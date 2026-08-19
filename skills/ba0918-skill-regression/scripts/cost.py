#!/usr/bin/env python3
"""What a batch will cost, shown before it is started.

Running a scenario means driving an agent through a whole task, which is the
expensive part of this instrument by a wide margin. A batch whose size only
becomes visible while it is already spending is how a single run ends up
consuming a fifth of a week's allowance, so nothing here is optional decoration:
the estimate, the stop after the first unmeasured scenario, and the ceiling are
the three things that keep that from happening again.

**The estimate is a lookup, not a prediction.** How much an agent produces cannot
be read off its input — a short skill can drive dozens of turns. So a scenario
that has been run before is estimated from what it actually cost, scaled by how
much its input has changed since, and a scenario that has not been run before is
reported as unmeasured rather than guessed at. An unmeasured scenario is left out
of the total: folding it in as zero would make the batch read as small.

**The stop is what actually protects the first run.** History cannot help the
first time a scenario runs, which is exactly when the surprise hurts. A batch
holding any unmeasured scenario runs one and reports what it cost before asking
whether to go on, so an unknown cost is bounded by a single scenario.

**The ceiling bounds everything else.** Estimates are wrong; a hard stop is not.

**Where the history lives.** Not in the lock, and not in the target repository at
all. What a scenario cost is a fact about the route and the model that ran it,
and the lock travels to every environment that clones the repository. The history
belongs to the environment that produced it, at a path the invocation names.
"""
import argparse
import datetime
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lock  # noqa: E402

# A rough figure for turning bytes into tokens. It is only ever used to scale one
# measurement against another and to size an unmeasured input, so its absolute
# accuracy matters less than its being stated: every report shows bytes as well.
BYTES_PER_TOKEN = 4

DEFAULT_HISTORY_DIRS = (".local", "state", "ba0918-skill-regression")
DEFAULT_HISTORY_NAME = "cost-history.json"
HISTORY_ENV_VAR = "SKILL_REGRESSION_COST_HISTORY"


def default_history_path():
    """Where the cost history lives when the invocation names no path."""
    from_env = os.environ.get(HISTORY_ENV_VAR)
    if from_env:
        return from_env
    return os.path.join(os.path.expanduser("~"), *DEFAULT_HISTORY_DIRS,
                        DEFAULT_HISTORY_NAME)


def approx_tokens(byte_count):
    """Approximate tokens for a byte count, rounded up so nothing reads as free."""
    return max(1, math.ceil(byte_count / BYTES_PER_TOKEN))


def _text_bytes(value):
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    if isinstance(value, list):
        return sum(_text_bytes(item) for item in value)
    if isinstance(value, dict):
        return sum(_text_bytes(item) for item in value.values())
    return 0


def input_bytes(root, inputs_root, skill, scenario):
    """How much text the executor has to read for one scenario.

    That is the scenario's own prose, the input files it declares, and the text of
    the skill under test — which the executor reads in full. A declared input that
    is not there is simply not counted; the estimate is advisory and the run
    itself reports the missing file.
    """
    total = _text_bytes(scenario.get("prompt")) + \
        _text_bytes(scenario.get("expected_output")) + \
        _text_bytes(scenario.get("expectations"))
    for entry in scenario.get("files") or []:
        source = entry.get("from") if isinstance(entry, dict) else entry
        if not isinstance(source, str):
            continue
        path = os.path.join(inputs_root, source)
        if os.path.isfile(path):
            total += os.path.getsize(path)
    skill_dir = os.path.join(root, "skills", skill)
    for dirpath, _, filenames in os.walk(skill_dir):
        for name in filenames:
            if name.endswith(".md"):
                total += os.path.getsize(os.path.join(dirpath, name))
    return total


def load_history(path):
    """Read the cost history, or an empty one when there is none yet."""
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}


def save_history(path, history):
    """Write the cost history, creating its directory if needed."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(history, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def record(history, skill, scenario_id, route, input_bytes, input_tokens,
           output_tokens, wall_seconds, observed):
    """Keep what one run of one scenario on one route actually cost."""
    history.setdefault(f"{skill}/{scenario_id}", {})[route] = {
        "input_bytes": input_bytes,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "wall_seconds": wall_seconds,
        "observed": observed,
    }
    return history


def estimate(history, skill, scenario_id, route, current_bytes):
    """What this scenario is expected to cost on this route.

    `approx_input_tokens` is always there: how much the executor has to read is
    on disk whether or not the scenario has ever run. `measured` is false when
    there is nothing to look up, and then the observed figures are None. The two
    are never folded together — one is derived from bytes, the other was seen.
    Cost is a fact about the route it was seen on, so a record from a different
    route does not answer for this one.
    """
    base = {
        "scenario": scenario_id,
        "route": route,
        "input_bytes": current_bytes,
        "approx_input_tokens": approx_tokens(current_bytes),
    }
    previous = (history.get(f"{skill}/{scenario_id}") or {}).get(route)
    if not previous:
        return dict(base, measured=False, input_tokens=None, output_tokens=None,
                    wall_seconds=None)
    recorded_bytes = previous.get("input_bytes") or current_bytes or 1
    scale = (current_bytes / recorded_bytes) if recorded_bytes else 1.0
    return dict(
        base,
        measured=True,
        input_tokens=max(1, round((previous.get("input_tokens") or 0) * scale)),
        output_tokens=previous.get("output_tokens"),
        wall_seconds=previous.get("wall_seconds"),
    )


def dry_run(root, inputs_root, skill, scenarios, route, history):
    """Size a batch without running any part of it.

    `total` covers the scenarios there is a measurement for; the ones there is not
    are named separately, and their presence is what sets `stop_after_first`.
    `approx_input_total` covers every scenario, measured or not, so that a batch
    with no history reads as a known amount of reading rather than as nothing
    known at all.
    """
    estimates = []
    unmeasured = []
    approx_total = 0
    totals = {"input_tokens": 0, "output_tokens": 0, "wall_seconds": 0.0}
    for scenario in scenarios:
        current = input_bytes(root, inputs_root, skill, scenario)
        item = estimate(history, skill, scenario["id"], route, current)
        estimates.append(item)
        approx_total += item["approx_input_tokens"]
        if not item["measured"]:
            unmeasured.append(scenario["id"])
            continue
        totals["input_tokens"] += item["input_tokens"] or 0
        totals["output_tokens"] += item["output_tokens"] or 0
        totals["wall_seconds"] += item["wall_seconds"] or 0.0
    return {
        "skill": skill,
        "route": route,
        "scenarios": estimates,
        "unmeasured": unmeasured,
        "measured_count": len(estimates) - len(unmeasured),
        "approx_input_total": approx_total,
        "total": totals,
        "stop_after_first": bool(unmeasured),
    }


def ceiling_reached(spent, ceiling):
    """Why the batch must stop now, or None while it may continue.

    An estimate can be wrong; this cannot. A ceiling that names nothing never
    stops anything, which is the state a caller that set no budget is in.
    """
    tokens = (ceiling or {}).get("tokens")
    seconds = (ceiling or {}).get("seconds")
    if tokens is not None and (spent.get("output_tokens") or 0) >= tokens:
        return f"the token ceiling of {tokens} was reached"
    if seconds is not None and (spent.get("wall_seconds") or 0) >= seconds:
        return f"the time ceiling of {seconds}s was reached"
    return None


def main(argv):
    parser = argparse.ArgumentParser(add_help=True, description="Size a batch before running it.")
    parser.add_argument("mode", choices=("dry-run", "record"))
    parser.add_argument("--root", default=os.getcwd())
    parser.add_argument("--inputs", required=True)
    parser.add_argument("--skill", required=True)
    parser.add_argument("--route", required=True)
    parser.add_argument("--history", default=None)
    parser.add_argument("--scenario", action="append", default=[])
    parser.add_argument("--input-bytes", type=int)
    parser.add_argument("--input-tokens", type=int)
    parser.add_argument("--output-tokens", type=int)
    parser.add_argument("--wall-seconds", type=float)
    parser.add_argument("--observed")
    args = parser.parse_args(argv)

    history_path = args.history or default_history_path()
    history = load_history(history_path)

    if args.mode == "record":
        if len(args.scenario) != 1:
            print("record needs exactly one --scenario", file=sys.stderr)
            return 2
        record(history, args.skill, args.scenario[0], args.route,
               input_bytes=args.input_bytes or 0,
               input_tokens=args.input_tokens or 0,
               output_tokens=args.output_tokens or 0,
               wall_seconds=args.wall_seconds or 0.0,
               observed=args.observed or datetime.date.today().isoformat())
        save_history(history_path, history)
        print(f"recorded {args.skill}/{args.scenario[0]} on {args.route} in {history_path}")
        return 0

    scenarios = lock.load_scenarios(args.root, args.skill)
    if args.scenario:
        wanted = set(args.scenario)
        scenarios = [s for s in scenarios if s["id"] in wanted]
    report = dry_run(args.root, args.inputs, args.skill, scenarios, args.route, history)
    report["history"] = history_path
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
