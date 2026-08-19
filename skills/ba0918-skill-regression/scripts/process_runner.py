#!/usr/bin/env python3
"""Process delegation runner — drain a work queue through separate agent-CLI processes.

Contract of record: `references/process-queue.md` beside this skill. This module is the
mechanical enforcement of that contract; the prose there is authoritative for *why*.

Two properties shape the whole design:

1. **The verdict comes from the artifact, never the exit code.** A process reporting its own
   success is the same evidence class as an implementer saying "it passed" — not evidence.
   `classify_outcome` therefore takes an artifact state and treats the exit code as metadata.
2. **This file carries no vendor name.** Every executable, flag, and permission decision lives
   in an operator-authored `backends.json`. A work-queue entry can never contribute an argv
   element, which is the entire permission boundary (contract §5).

Design (design-principles §4/§5): every decision rule is a pure function over strings. The
process layer (`Runner`) only performs I/O and calls them.
"""

import argparse
import errno
import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

SCHEMA_VERSION = 1

ID_RE = re.compile(r"[A-Za-z0-9._-]+")
OUTPUT_FORMATS = ("text", "json")
PROMPT_DELIVERIES = ("stdin", "argv")

_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")
ALLOWED_PLACEHOLDERS = ("id", "prompt_file", "output_file", "cwd")

ARTIFACT_STATES = ("ok", "missing", "empty", "malformed")

# error_kind -> failure_class. `permanent` means re-running the identical queue cannot help;
# the registry or the producer has to change first (contract §6).
FAILURE_CLASS = {
    "missing_prompt": "permanent",
    "spawn_failed": "permanent",
    "timeout": "transient",
    "missing_artifact": "transient",
    "empty_artifact": "transient",
    "malformed_artifact": "transient",
}

# Highest precedence first (contract §8).
HALT_PRECEDENCE = ("stop.hard", "stop.graceful", "failed_streak", "max_wallclock")

DEFAULT_MAX_PARALLEL = 4
DEFAULT_TIMEOUT = 900
DEFAULT_MAX_WALLCLOCK = 3600
DEFAULT_FAILED_STREAK_LIMIT = 3
DEFAULT_GRACE = 5.0
DEFAULT_POLL_INTERVAL = 0.05

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_FAILURES = 10
EXIT_HALTED = 11

_POSIX = os.name == "posix"


class ParseError(Exception):
    """Malformed registry or work queue. Detected before any dispatch."""


class ContainmentError(Exception):
    """A producer-supplied path escapes --root or is a symlink."""


@dataclass
class Backend:
    name: str
    argv: tuple
    prompt_delivery: str = "stdin"


@dataclass
class WorkUnit:
    id: str
    prompt_file: str
    output_file: str
    output_format: str = "text"
    cwd: str = ""
    # Absolute, containment-checked forms; filled by resolve_paths().
    prompt_abs: str = ""
    output_abs: str = ""
    cwd_abs: str = ""


@dataclass
class UnitResult:
    id: str
    status: str  # done | failed | skipped
    error_kind: str = ""
    failure_class: str = ""
    exit_code: object = None
    duration_ms: int = 0
    started_at: str = ""

    def as_record(self):
        """JSONL report record. Enums and numbers only — no free text (contract §9)."""
        return {
            "id": self.id,
            "status": self.status,
            "error_kind": self.error_kind or None,
            "failure_class": self.failure_class or None,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "started_at": self.started_at,
        }


# ==========================================================================
# Registry parsing (pure)
# ==========================================================================
def placeholders(template_item):
    """Placeholder names used in one argv element, in order of appearance."""
    return _PLACEHOLDER_RE.findall(template_item)


def parse_backends(text):
    """Parse a backends.json document into {name: Backend}. Raises ParseError."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParseError(f"backends registry is not valid JSON: {exc}")
    if not isinstance(data, dict):
        raise ParseError("backends registry must be a JSON object")
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ParseError(
            f"unsupported schema_version {version!r} (expected {SCHEMA_VERSION})"
        )
    raw = data.get("backends")
    if not isinstance(raw, dict) or not raw:
        raise ParseError("backends registry has no 'backends' object")

    out = {}
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            raise ParseError(f"backend {name!r} is not an object")
        argv = spec.get("argv")
        if not isinstance(argv, list) or not argv:
            raise ParseError(f"backend {name!r} has no non-empty 'argv' list")
        if not all(isinstance(a, str) for a in argv):
            raise ParseError(f"backend {name!r} argv must be a list of strings")
        for item in argv:
            for ph in placeholders(item):
                if ph not in ALLOWED_PLACEHOLDERS:
                    raise ParseError(
                        f"backend {name!r} uses unknown placeholder {{{ph}}} "
                        f"(allowed: {', '.join(ALLOWED_PLACEHOLDERS)})"
                    )
        delivery = spec.get("prompt_delivery", "stdin")
        if delivery not in PROMPT_DELIVERIES:
            raise ParseError(
                f"backend {name!r} has unknown prompt_delivery {delivery!r} "
                f"(allowed: {', '.join(PROMPT_DELIVERIES)})"
            )
        if delivery == "argv" and not any(
            "prompt_file" in placeholders(item) for item in argv
        ):
            raise ParseError(
                f"backend {name!r} declares prompt_delivery 'argv' but argv has no "
                f"{{prompt_file}} placeholder"
            )
        out[name] = Backend(name=name, argv=tuple(argv), prompt_delivery=delivery)
    return out


def resolve_argv(template, fields):
    """Substitute placeholders in an argv template. Raises ParseError on unknown names."""
    resolved = []
    for item in template:
        def _sub(match):
            key = match.group(1)
            if key not in fields:
                raise ParseError(f"unknown placeholder {{{key}}} in argv template")
            return fields[key]
        resolved.append(_PLACEHOLDER_RE.sub(_sub, item))
    return resolved


# ==========================================================================
# Work queue parsing (pure)
# ==========================================================================
def parse_work(text):
    """Parse work.jsonl into a list of WorkUnit. Raises ParseError.

    Rejects duplicate ids and duplicate output_file values. Artifact uniqueness is what
    makes parallel execution safe: two units can never race for the same file, so the
    runner needs no write arbitration at all (contract §3).
    """
    units = []
    seen_ids = set()
    seen_outputs = set()
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ParseError(f"work line {lineno} is not valid JSON: {exc}")
        if not isinstance(obj, dict):
            raise ParseError(f"work line {lineno} is not a JSON object")

        unknown = set(obj) - {
            "id", "prompt_file", "output_file", "output_format", "cwd",
        }
        if unknown:
            raise ParseError(
                f"work line {lineno} has unknown field(s): {', '.join(sorted(unknown))}"
            )

        uid = obj.get("id")
        if not isinstance(uid, str) or not ID_RE.fullmatch(uid):
            raise ParseError(
                f"work line {lineno} has invalid id {uid!r} (allowed: [A-Za-z0-9._-]+)"
            )
        if uid in seen_ids:
            raise ParseError(f"work line {lineno} repeats id {uid!r}")
        seen_ids.add(uid)

        for key in ("prompt_file", "output_file"):
            value = obj.get(key)
            if not isinstance(value, str) or not value:
                raise ParseError(f"work line {lineno} ({uid}) has no {key}")

        output_file = obj["output_file"]
        normalized = os.path.normpath(output_file)
        if normalized in seen_outputs:
            raise ParseError(
                f"work line {lineno} ({uid}) reuses output_file {output_file!r}; "
                f"artifacts must be unique per unit"
            )
        seen_outputs.add(normalized)

        output_format = obj.get("output_format", "text")
        if output_format not in OUTPUT_FORMATS:
            raise ParseError(
                f"work line {lineno} ({uid}) has unknown output_format "
                f"{output_format!r} (allowed: {', '.join(OUTPUT_FORMATS)})"
            )

        cwd = obj.get("cwd", "")
        if not isinstance(cwd, str):
            raise ParseError(f"work line {lineno} ({uid}) has non-string cwd")

        units.append(WorkUnit(
            id=uid,
            prompt_file=obj["prompt_file"],
            output_file=output_file,
            output_format=output_format,
            cwd=cwd,
        ))
    if not units:
        raise ParseError("work queue is empty")
    return units


# ==========================================================================
# Outcome classification (pure)
# ==========================================================================
def artifact_state(content, output_format):
    """Classify an artifact. `content is None` means the file is absent.

    A JSON artifact that parses is `ok` whatever it parses to; deciding whether the
    *value* is acceptable is the harness's job, not the runner's.
    """
    if output_format not in OUTPUT_FORMATS:
        raise ParseError(f"unknown output_format {output_format!r}")
    if content is None:
        return "missing"
    if not content.strip():
        return "empty"
    if output_format == "json":
        try:
            json.loads(content)
        except json.JSONDecodeError:
            return "malformed"
    return "ok"


def classify_outcome(state, *, timed_out=False, spawn_failed=False,
                     missing_prompt=False):
    """Map an artifact state plus process facts onto (status, error_kind).

    Precedence is fixed: missing_prompt > spawn_failed > timeout > artifact state. A
    timed-out unit stays a failure even when a partial artifact happens to validate — the
    process was killed, so nothing attests that the artifact is complete.
    """
    if missing_prompt:
        return "failed", "missing_prompt"
    if spawn_failed:
        return "failed", "spawn_failed"
    if timed_out:
        return "failed", "timeout"
    if state == "ok":
        return "done", ""
    if state not in ARTIFACT_STATES:
        raise ParseError(f"unknown artifact state {state!r}")
    return "failed", f"{state}_artifact"


def failure_class(error_kind):
    """transient / permanent split for an error_kind (contract §6)."""
    if not error_kind:
        return ""
    try:
        return FAILURE_CLASS[error_kind]
    except KeyError:
        raise ParseError(f"unknown error_kind {error_kind!r}")


def next_failed_streak(streak, status):
    """Consecutive-failure counter. `skipped` leaves it untouched — a skip is not a run,
    and letting a queue of already-satisfied units reset the counter would defuse the
    brake exactly when a resumed batch needs it."""
    if status == "failed":
        return streak + 1
    if status == "done":
        return 0
    return streak


def strongest_halt(*reasons):
    """Pick the highest-precedence halt reason among the arguments (contract §8)."""
    present = [r for r in reasons if r]
    for reason in HALT_PRECEDENCE:
        if reason in present:
            return reason
    return present[0] if present else None


def summarize(total, results, halt_reason, *, run_id, started_at, duration_ms):
    """Build the single stdout object. total == skipped + done + failed + pending."""
    counts = {"skipped": 0, "done": 0, "failed": 0}
    for result in results:
        if result.status not in counts:
            raise ParseError(f"unknown unit status {result.status!r}")
        counts[result.status] += 1
    pending = total - sum(counts.values())
    if pending < 0:
        raise ParseError("more results than units")
    return {
        "run_id": run_id,
        "started_at": started_at,
        "duration_ms": duration_ms,
        "total": total,
        "skipped": counts["skipped"],
        "done": counts["done"],
        "failed": counts["failed"],
        "pending": pending,
        "halt_reason": halt_reason,
    }


def summary_exit_code(summary):
    """Halt outranks failures: a brake tells the operator *why* the batch stopped, which
    a bare failure count would hide."""
    halt = summary.get("halt_reason")
    if halt and halt != "dry_run":
        return EXIT_HALTED
    if summary.get("failed"):
        return EXIT_FAILURES
    return EXIT_OK


# ==========================================================================
# Path containment (filesystem probe)
# ==========================================================================
def resolve_contained(path, root):
    """Resolve a producer-supplied path against root, rejecting escapes and symlinks.

    Only queue-supplied paths go through this. Operator-supplied CLI paths deliberately
    do not — that asymmetry is the trust boundary (contract §10).
    """
    root_real = os.path.realpath(root)
    candidate = path if os.path.isabs(path) else os.path.join(root_real, path)
    if os.path.islink(candidate):
        raise ContainmentError(f"symlink rejected: {path}")
    real = os.path.realpath(candidate)
    if real != root_real and not real.startswith(root_real + os.sep):
        raise ContainmentError(f"path escapes --root: {path}")
    return real


def resolve_paths(units, root):
    """Fill the absolute path fields of every unit. Raises ContainmentError."""
    root_real = os.path.realpath(root)
    for unit in units:
        unit.prompt_abs = resolve_contained(unit.prompt_file, root_real)
        unit.output_abs = resolve_contained(unit.output_file, root_real)
        unit.cwd_abs = (
            resolve_contained(unit.cwd, root_real) if unit.cwd else root_real
        )
    return units


def read_text(path):
    """File content, or None when absent/unreadable."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ==========================================================================
# Process layer
# ==========================================================================
@dataclass
class _Job:
    unit: WorkUnit
    proc: object
    started_at: str
    t0: float
    handles: list = field(default_factory=list)

    def close(self):
        for handle in self.handles:
            try:
                handle.close()
            except OSError:
                pass
        self.handles = []


class Runner:
    """Drains a queue of WorkUnits through a backend. All I/O lives here."""

    def __init__(self, units, backend, root, runtime_root, *,
                 max_parallel=DEFAULT_MAX_PARALLEL,
                 timeout=DEFAULT_TIMEOUT,
                 max_wallclock=DEFAULT_MAX_WALLCLOCK,
                 failed_streak_limit=DEFAULT_FAILED_STREAK_LIMIT,
                 grace=DEFAULT_GRACE,
                 poll_interval=DEFAULT_POLL_INTERVAL,
                 dry_run=False,
                 report_path=None):
        self.units = units
        self.backend = backend
        self.root = os.path.realpath(root)
        self.runtime_root = os.path.abspath(runtime_root)
        self.max_parallel = max(1, int(max_parallel))
        self.timeout = float(timeout)
        self.max_wallclock = float(max_wallclock)
        self.failed_streak_limit = int(failed_streak_limit)
        self.grace = float(grace)
        self.poll_interval = float(poll_interval)
        self.dry_run = dry_run
        self.report_path = report_path
        # Absolute resolution is mandatory: a cwd-relative kill file is a brake that
        # silently stops braking the moment someone runs the command from elsewhere.
        self.stop_hard = os.path.join(self.runtime_root, ".STOP.hard")
        self.stop = os.path.join(self.runtime_root, ".STOP")
        self.logs_dir = os.path.join(self.runtime_root, "logs")
        self._signalled = False
        self.results = []
        self.peak_parallel = 0

    # -- safety brakes -----------------------------------------------------
    def _kill_file_halt(self):
        if self._signalled or os.path.exists(self.stop_hard):
            return "stop.hard"
        if os.path.exists(self.stop):
            return "stop.graceful"
        return None

    def install_signal_handlers(self):
        def _handler(_signum, _frame):
            self._signalled = True
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _handler)
            except (ValueError, OSError):
                pass  # not on the main thread; the kill files still apply

    # -- process control ---------------------------------------------------
    def _spawn(self, unit):
        """Start one unit. Returns a _Job, or a UnitResult when the spawn failed."""
        started_at = utc_now()
        t0 = time.monotonic()
        if not os.path.isfile(unit.prompt_abs):
            status, kind = classify_outcome("missing", missing_prompt=True)
            return UnitResult(unit.id, status, kind, failure_class(kind),
                              None, 0, started_at)

        fields = {
            "id": unit.id,
            "prompt_file": unit.prompt_abs,
            "output_file": unit.output_abs,
            "cwd": unit.cwd_abs,
        }
        argv = resolve_argv(self.backend.argv, fields)

        os.makedirs(os.path.dirname(unit.output_abs) or self.root, exist_ok=True)
        os.makedirs(self.logs_dir, exist_ok=True)

        handles = []
        try:
            log = open(os.path.join(self.logs_dir, f"{unit.id}.log"), "wb")
            handles.append(log)
            if self.backend.prompt_delivery == "stdin":
                stdin = open(unit.prompt_abs, "rb")
                handles.append(stdin)
            else:
                stdin = subprocess.DEVNULL
            proc = subprocess.Popen(
                argv,
                cwd=unit.cwd_abs,
                stdin=stdin,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=_POSIX,
            )
        except OSError:
            for handle in handles:
                try:
                    handle.close()
                except OSError:
                    pass
            status, kind = classify_outcome("missing", spawn_failed=True)
            return UnitResult(unit.id, status, kind, failure_class(kind),
                              None, int((time.monotonic() - t0) * 1000), started_at)
        return _Job(unit=unit, proc=proc, started_at=started_at, t0=t0,
                    handles=handles)

    def _signal_group(self, proc, sig):
        if _POSIX and hasattr(os, "killpg"):
            try:
                os.killpg(os.getpgid(proc.pid), sig)
                return
            except OSError as exc:
                if exc.errno not in (errno.ESRCH, errno.EPERM):
                    raise
        try:
            proc.send_signal(sig)
        except OSError:
            pass

    def _terminate(self, job):
        """SIGTERM the child's process group, escalating to SIGKILL after the grace
        period. Group-wide because an agent CLI spawns its own children; signalling only
        the direct child leaves them running."""
        self._signal_group(job.proc, signal.SIGTERM)
        try:
            job.proc.wait(timeout=self.grace)
        except subprocess.TimeoutExpired:
            self._signal_group(job.proc, signal.SIGKILL)
            try:
                job.proc.wait(timeout=self.grace)
            except subprocess.TimeoutExpired:
                pass
        job.close()

    def _finish(self, job, exit_code, timed_out):
        job.close()
        state = artifact_state(read_text(job.unit.output_abs),
                               job.unit.output_format)
        status, kind = classify_outcome(state, timed_out=timed_out)
        return UnitResult(job.unit.id, status, kind, failure_class(kind), exit_code,
                          int((time.monotonic() - job.t0) * 1000), job.started_at)

    def _streak_tripped(self, failed_streak):
        return (self.failed_streak_limit > 0
                and failed_streak >= self.failed_streak_limit)

    def _already_satisfied(self, unit):
        return artifact_state(read_text(unit.output_abs),
                              unit.output_format) == "ok"

    # -- main loop ---------------------------------------------------------
    def run(self):
        run_id = str(uuid.uuid4())
        started_at = utc_now()
        t0 = time.monotonic()

        if self.dry_run:
            for unit in self.units:
                if self._already_satisfied(unit):
                    self.results.append(
                        UnitResult(unit.id, "skipped", started_at=started_at))
            return self._finalize(run_id, started_at, t0, "dry_run")

        queue = list(self.units)
        inflight = {}
        failed_streak = 0
        halt = None

        while True:
            halt = strongest_halt(halt, self._kill_file_halt())
            if halt == "stop.hard":
                for job in inflight.values():
                    self._terminate(job)
                inflight = {}
                break

            # Reap before testing the brakes. The other order lets one more unit
            # dispatch in the same pass that a completed failure pushed the streak over
            # the limit — the brake would always fire one unit late.
            for uid, job in list(inflight.items()):
                exit_code = job.proc.poll()
                timed_out = False
                if exit_code is None:
                    if time.monotonic() - job.t0 <= self.timeout:
                        continue
                    self._terminate(job)
                    exit_code = job.proc.poll()
                    timed_out = True
                del inflight[uid]
                result = self._finish(job, exit_code, timed_out)
                self.results.append(result)
                failed_streak = next_failed_streak(failed_streak, result.status)

            if halt is None:
                if self._streak_tripped(failed_streak):
                    halt = "failed_streak"
                elif time.monotonic() - t0 > self.max_wallclock:
                    halt = "max_wallclock"

            while halt is None and queue and len(inflight) < self.max_parallel:
                # Re-checked per dispatch, not once per pass: a kill file dropped
                # mid-batch must stop the very next unit, not the next scheduling pass.
                halt = self._kill_file_halt()
                if halt:
                    break
                unit = queue.pop(0)
                if self._already_satisfied(unit):
                    self.results.append(
                        UnitResult(unit.id, "skipped", started_at=utc_now()))
                    continue
                spawned = self._spawn(unit)
                if isinstance(spawned, UnitResult):
                    # A unit that fails at spawn time never enters flight, so the
                    # dispatch loop would otherwise keep going and drain the whole
                    # queue before the brake is next consulted. A missing executable
                    # fails every unit this way; check the streak here too.
                    self.results.append(spawned)
                    failed_streak = next_failed_streak(failed_streak, spawned.status)
                    if self._streak_tripped(failed_streak):
                        halt = "failed_streak"
                        break
                    continue
                inflight[unit.id] = spawned
                self.peak_parallel = max(self.peak_parallel, len(inflight))

            if not inflight and (halt is not None or not queue):
                break
            time.sleep(self.poll_interval)

        return self._finalize(run_id, started_at, t0, halt)

    def _finalize(self, run_id, started_at, t0, halt):
        summary = summarize(
            len(self.units), self.results, halt,
            run_id=run_id, started_at=started_at,
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        if self.report_path:
            self._write_report()
        return summary

    def _write_report(self):
        directory = os.path.dirname(os.path.abspath(self.report_path))
        os.makedirs(directory, exist_ok=True)
        with open(self.report_path, "w", encoding="utf-8") as handle:
            for result in self.results:
                handle.write(json.dumps(result.as_record(), sort_keys=True) + "\n")


# ==========================================================================
# CLI layer
# ==========================================================================
def _load(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _prepare(args):
    """Parse + resolve everything that can fail before a single process starts."""
    backends = parse_backends(_load(args.backends))
    if args.backend not in backends:
        raise ParseError(
            f"unknown backend {args.backend!r} "
            f"(registry defines: {', '.join(sorted(backends))})"
        )
    units = resolve_paths(parse_work(_load(args.work)), args.root)
    return backends[args.backend], units


def _cli_validate(args):
    backend, units = _prepare(args)
    fields = {"id": "", "prompt_file": "", "output_file": "", "cwd": ""}
    resolve_argv(backend.argv, fields)
    missing = [u.id for u in units if not os.path.isfile(u.prompt_abs)]
    print(json.dumps({
        "backend": backend.name,
        "units": len(units),
        "missing_prompts": missing,
    }, sort_keys=True))
    return EXIT_CONFIG if missing else EXIT_OK


def _cli_run(args):
    backend, units = _prepare(args)
    runner = Runner(
        units, backend, args.root, args.runtime_root,
        max_parallel=args.max_parallel,
        timeout=args.timeout,
        max_wallclock=args.max_wallclock,
        failed_streak_limit=args.failed_streak_limit,
        dry_run=args.dry_run,
        report_path=args.report,
    )
    runner.install_signal_handlers()
    summary = runner.run()
    print(json.dumps(summary, sort_keys=True))
    return summary_exit_code(summary)


def _add_common(parser):
    parser.add_argument("--work", required=True, help="work queue JSONL")
    parser.add_argument("--backends", required=True, help="backend registry JSON")
    parser.add_argument("--backend", required=True, help="backend name to use")
    parser.add_argument("--root", default=".",
                        help="containment root for queue-supplied paths")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run a work queue through separate agent-CLI processes.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    validate = sub.add_parser(
        "validate", help="parse and containment-check a queue without dispatching")
    _add_common(validate)
    validate.set_defaults(func=_cli_validate)

    run = sub.add_parser("run", help="drain the queue")
    _add_common(run)
    run.add_argument("--runtime-root", required=True,
                     help="machine-local control area (kill files, logs)")
    run.add_argument("--max-parallel", type=int, default=DEFAULT_MAX_PARALLEL)
    run.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                     help="per-unit seconds")
    run.add_argument("--max-wallclock", type=float, default=DEFAULT_MAX_WALLCLOCK)
    run.add_argument("--failed-streak-limit", type=int,
                     default=DEFAULT_FAILED_STREAK_LIMIT,
                     help="0 disables the consecutive-failure brake")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--report", default=None, help="per-unit JSONL report path")
    run.set_defaults(func=_cli_run)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ParseError, ContainmentError, OSError) as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}),
              file=sys.stderr)
        return EXIT_CONFIG


if __name__ == "__main__":
    raise SystemExit(main())
