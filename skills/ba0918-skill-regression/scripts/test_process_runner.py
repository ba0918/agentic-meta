#!/usr/bin/env python3
"""Tests for process_runner.py.

The end-to-end tests drive the runner through a **generic** backend: a throwaway Python
program declared in a `backends.json` fixture, exactly like a real agent CLI would be.
That is deliberate — it exercises the vendor-neutrality claim (the runner never names an
executable) while keeping the suite hermetic and offline.

Coverage targets the failure paths the design flagged as unverified: timeout, a kill file
appearing mid-run, a corrupt artifact, a backend that cannot start, and parallel dispatch.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import process_runner as pr  # noqa: E402


# A stand-in agent CLI. argv: <output_file> <mode> [extra]. Reads the prompt from stdin
# so the tests also prove stdin delivery.
# NOTE: this program text is itself an argv element, so it must contain no braces —
# the runner reserves `{...}` for placeholders and rejects unknown ones at parse time.
FAKE_CLI = r"""
import json, sys, time
out, mode = sys.argv[1], sys.argv[2]
extra = sys.argv[3] if len(sys.argv) > 3 else ""
prompt = sys.stdin.read()
if mode == "echo":
    open(out, "w").write(prompt)
elif mode == "json":
    open(out, "w").write(json.dumps(dict(prompt=prompt)))
elif mode == "silent":
    pass
elif mode == "empty":
    open(out, "w").write("   \n")
elif mode == "badjson":
    open(out, "w").write("{not json")
elif mode == "dirty-exit":
    open(out, "w").write(prompt)
    sys.exit(3)
elif mode == "sleep":
    time.sleep(60)
elif mode == "trip-and-sleep":
    open(extra, "w").write("")
    time.sleep(60)
elif mode == "slow":
    time.sleep(float(extra))
    open(out, "w").write(prompt)
sys.exit(0)
"""

# A backend that takes the prompt as an argv path instead of on stdin.
FAKE_CLI_ARGV = r"""
import sys
out, prompt_file = sys.argv[1], sys.argv[2]
open(out, "w").write(open(prompt_file).read())
"""


class _Harness(unittest.TestCase):
    """Temp-dir scaffolding: a containment root, a runtime root, and a registry."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "root")
        self.runtime = os.path.join(self.tmp, "runtime")
        os.makedirs(os.path.join(self.root, "prompts"))
        os.makedirs(os.path.join(self.root, "results"))
        os.makedirs(self.runtime)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_prompt(self, uid, text="do the thing"):
        path = os.path.join(self.root, "prompts", f"{uid}.md")
        with open(path, "w") as handle:
            handle.write(text)
        return f"prompts/{uid}.md"

    def backend(self, mode, extra=None, *, program=FAKE_CLI, delivery="stdin"):
        argv = [sys.executable, "-c", program, "{output_file}"]
        if program is FAKE_CLI:
            argv.append(mode)
            argv.append(extra if extra is not None else "")
        else:
            argv.append("{prompt_file}")
        return pr.Backend(name="test", argv=tuple(argv), prompt_delivery=delivery)

    def units(self, ids, *, output_format="text", ext="txt", make_prompt=True):
        lines = []
        for uid in ids:
            if make_prompt:
                self.write_prompt(uid)
            lines.append(json.dumps({
                "id": uid,
                "prompt_file": f"prompts/{uid}.md",
                "output_file": f"results/{uid}.{ext}",
                "output_format": output_format,
            }))
        return pr.resolve_paths(pr.parse_work("\n".join(lines)), self.root)

    def runner(self, units, backend, **kwargs):
        kwargs.setdefault("poll_interval", 0.02)
        kwargs.setdefault("grace", 1.0)
        return pr.Runner(units, backend, self.root, self.runtime, **kwargs)

    def result_by_id(self, runner):
        return {r.id: r for r in runner.results}


# ==========================================================================
# Registry parsing
# ==========================================================================
class TestParseBackends(unittest.TestCase):
    def _doc(self, **spec):
        return json.dumps({"schema_version": 1, "backends": {"b": spec}})

    def test_minimal_backend(self):
        backends = pr.parse_backends(self._doc(argv=["tool", "-p"]))
        self.assertEqual(backends["b"].argv, ("tool", "-p"))
        self.assertEqual(backends["b"].prompt_delivery, "stdin")

    def test_allowed_placeholders_pass(self):
        doc = self._doc(argv=["tool", "{id}", "{prompt_file}", "{output_file}", "{cwd}"])
        self.assertIn("b", pr.parse_backends(doc))

    def test_not_json(self):
        with self.assertRaises(pr.ParseError):
            pr.parse_backends("{nope")

    def test_not_an_object(self):
        with self.assertRaises(pr.ParseError):
            pr.parse_backends("[]")

    def test_wrong_schema_version(self):
        doc = json.dumps({"schema_version": 2, "backends": {"b": {"argv": ["x"]}}})
        with self.assertRaises(pr.ParseError):
            pr.parse_backends(doc)

    def test_no_backends(self):
        with self.assertRaises(pr.ParseError):
            pr.parse_backends(json.dumps({"schema_version": 1, "backends": {}}))

    def test_backend_not_object(self):
        doc = json.dumps({"schema_version": 1, "backends": {"b": "tool"}})
        with self.assertRaises(pr.ParseError):
            pr.parse_backends(doc)

    def test_empty_argv(self):
        with self.assertRaises(pr.ParseError):
            pr.parse_backends(self._doc(argv=[]))

    def test_non_string_argv_element(self):
        with self.assertRaises(pr.ParseError):
            pr.parse_backends(self._doc(argv=["tool", 7]))

    def test_unknown_placeholder_rejected(self):
        with self.assertRaises(pr.ParseError) as ctx:
            pr.parse_backends(self._doc(argv=["tool", "{secret}"]))
        self.assertIn("secret", str(ctx.exception))

    def test_unknown_prompt_delivery(self):
        with self.assertRaises(pr.ParseError):
            pr.parse_backends(self._doc(argv=["tool"], prompt_delivery="pipe"))

    def test_argv_delivery_requires_prompt_placeholder(self):
        with self.assertRaises(pr.ParseError):
            pr.parse_backends(self._doc(argv=["tool"], prompt_delivery="argv"))

    def test_argv_delivery_with_placeholder_ok(self):
        doc = self._doc(argv=["tool", "{prompt_file}"], prompt_delivery="argv")
        self.assertEqual(pr.parse_backends(doc)["b"].prompt_delivery, "argv")


class TestResolveArgv(unittest.TestCase):
    def test_substitutes_all_fields(self):
        argv = pr.resolve_argv(
            ["tool", "--in={prompt_file}", "{output_file}"],
            {"prompt_file": "/p.md", "output_file": "/o.json"},
        )
        self.assertEqual(argv, ["tool", "--in=/p.md", "/o.json"])

    def test_unknown_placeholder_raises(self):
        with self.assertRaises(pr.ParseError):
            pr.resolve_argv(["tool", "{nope}"], {"id": "a"})

    def test_literal_text_untouched(self):
        self.assertEqual(pr.resolve_argv(["-p", "--yes"], {}), ["-p", "--yes"])


# ==========================================================================
# Work queue parsing
# ==========================================================================
class TestParseWork(unittest.TestCase):
    def _line(self, **kwargs):
        obj = {"id": "a", "prompt_file": "p.md", "output_file": "o.txt"}
        obj.update(kwargs)
        return json.dumps(obj)

    def test_defaults(self):
        unit = pr.parse_work(self._line())[0]
        self.assertEqual(unit.output_format, "text")
        self.assertEqual(unit.cwd, "")

    def test_blank_lines_ignored(self):
        text = self._line() + "\n\n  \n" + self._line(id="b", output_file="o2.txt")
        self.assertEqual(len(pr.parse_work(text)), 2)

    def test_empty_queue_rejected(self):
        with self.assertRaises(pr.ParseError):
            pr.parse_work("\n\n")

    def test_line_not_json(self):
        with self.assertRaises(pr.ParseError):
            pr.parse_work("{oops")

    def test_line_not_object(self):
        with self.assertRaises(pr.ParseError):
            pr.parse_work("[1]")

    def test_duplicate_id(self):
        with self.assertRaises(pr.ParseError):
            pr.parse_work(self._line() + "\n" + self._line(output_file="o2.txt"))

    def test_duplicate_output_file(self):
        with self.assertRaises(pr.ParseError) as ctx:
            pr.parse_work(self._line() + "\n" + self._line(id="b"))
        self.assertIn("unique", str(ctx.exception))

    def test_duplicate_output_file_after_normalization(self):
        with self.assertRaises(pr.ParseError):
            pr.parse_work(
                self._line() + "\n" + self._line(id="b", output_file="./o.txt"))

    def test_bad_id_characters(self):
        with self.assertRaises(pr.ParseError):
            pr.parse_work(self._line(id="a/b"))

    def test_missing_prompt_field(self):
        with self.assertRaises(pr.ParseError):
            pr.parse_work(json.dumps({"id": "a", "output_file": "o.txt"}))

    def test_unknown_field(self):
        with self.assertRaises(pr.ParseError) as ctx:
            pr.parse_work(self._line(argv_extra=["--dangerous"]))
        self.assertIn("argv_extra", str(ctx.exception))

    def test_unknown_output_format(self):
        with self.assertRaises(pr.ParseError):
            pr.parse_work(self._line(output_format="yaml"))

    def test_non_string_cwd(self):
        with self.assertRaises(pr.ParseError):
            pr.parse_work(self._line(cwd=5))


# ==========================================================================
# Outcome classification
# ==========================================================================
class TestArtifactState(unittest.TestCase):
    def test_missing(self):
        self.assertEqual(pr.artifact_state(None, "text"), "missing")

    def test_empty(self):
        self.assertEqual(pr.artifact_state("", "text"), "empty")

    def test_whitespace_only_is_empty(self):
        self.assertEqual(pr.artifact_state("  \n\t ", "json"), "empty")

    def test_text_ok(self):
        self.assertEqual(pr.artifact_state("anything", "text"), "ok")

    def test_text_never_malformed(self):
        self.assertEqual(pr.artifact_state("{not json", "text"), "ok")

    def test_json_ok(self):
        self.assertEqual(pr.artifact_state('{"a": 1}', "json"), "ok")

    def test_json_malformed(self):
        self.assertEqual(pr.artifact_state("{not json", "json"), "malformed")

    def test_json_scalar_is_valid(self):
        self.assertEqual(pr.artifact_state("null", "json"), "ok")

    def test_unknown_format_raises(self):
        with self.assertRaises(pr.ParseError):
            pr.artifact_state("x", "yaml")


class TestClassifyOutcome(unittest.TestCase):
    def test_valid_artifact_is_done(self):
        self.assertEqual(pr.classify_outcome("ok"), ("done", ""))

    def test_missing_artifact(self):
        self.assertEqual(pr.classify_outcome("missing"),
                         ("failed", "missing_artifact"))

    def test_empty_artifact(self):
        self.assertEqual(pr.classify_outcome("empty"), ("failed", "empty_artifact"))

    def test_malformed_artifact(self):
        self.assertEqual(pr.classify_outcome("malformed"),
                         ("failed", "malformed_artifact"))

    def test_timeout_outranks_a_valid_artifact(self):
        self.assertEqual(pr.classify_outcome("ok", timed_out=True),
                         ("failed", "timeout"))

    def test_spawn_failure_outranks_timeout(self):
        self.assertEqual(
            pr.classify_outcome("ok", timed_out=True, spawn_failed=True),
            ("failed", "spawn_failed"))

    def test_missing_prompt_outranks_everything(self):
        self.assertEqual(
            pr.classify_outcome("ok", timed_out=True, spawn_failed=True,
                                missing_prompt=True),
            ("failed", "missing_prompt"))

    def test_unknown_state_raises(self):
        with self.assertRaises(pr.ParseError):
            pr.classify_outcome("weird")


class TestFailureClass(unittest.TestCase):
    def test_permanent_kinds(self):
        for kind in ("spawn_failed", "missing_prompt"):
            self.assertEqual(pr.failure_class(kind), "permanent")

    def test_transient_kinds(self):
        for kind in ("timeout", "missing_artifact", "empty_artifact",
                     "malformed_artifact"):
            self.assertEqual(pr.failure_class(kind), "transient")

    def test_no_error_kind(self):
        self.assertEqual(pr.failure_class(""), "")

    def test_unknown_kind_raises(self):
        with self.assertRaises(pr.ParseError):
            pr.failure_class("weird")

    def test_every_error_kind_has_a_class(self):
        for state in ("missing", "empty", "malformed"):
            _, kind = pr.classify_outcome(state)
            self.assertIn(kind, pr.FAILURE_CLASS)


class TestStreakAndHalt(unittest.TestCase):
    def test_failure_increments(self):
        self.assertEqual(pr.next_failed_streak(2, "failed"), 3)

    def test_success_resets(self):
        self.assertEqual(pr.next_failed_streak(2, "done"), 0)

    def test_skip_leaves_streak_untouched(self):
        self.assertEqual(pr.next_failed_streak(2, "skipped"), 2)

    def test_hard_stop_wins(self):
        self.assertEqual(
            pr.strongest_halt("max_wallclock", "stop.graceful", "stop.hard"),
            "stop.hard")

    def test_graceful_beats_brakes(self):
        self.assertEqual(pr.strongest_halt("failed_streak", "stop.graceful"),
                         "stop.graceful")

    def test_streak_beats_wallclock(self):
        self.assertEqual(pr.strongest_halt("max_wallclock", "failed_streak"),
                         "failed_streak")

    def test_none_when_empty(self):
        self.assertIsNone(pr.strongest_halt(None, None))

    def test_unranked_reason_passes_through(self):
        self.assertEqual(pr.strongest_halt("dry_run"), "dry_run")


class TestSummarize(unittest.TestCase):
    def _results(self, *statuses):
        return [pr.UnitResult(f"u{i}", s) for i, s in enumerate(statuses)]

    def test_counts_and_pending(self):
        summary = pr.summarize(
            5, self._results("done", "failed", "skipped"), "stop.graceful",
            run_id="r", started_at="t", duration_ms=1)
        self.assertEqual(
            (summary["done"], summary["failed"], summary["skipped"],
             summary["pending"]), (1, 1, 1, 2))

    def test_total_invariant_holds(self):
        summary = pr.summarize(
            4, self._results("done", "done"), None,
            run_id="r", started_at="t", duration_ms=1)
        self.assertEqual(
            summary["total"],
            summary["skipped"] + summary["done"] + summary["failed"]
            + summary["pending"])

    def test_unknown_status_raises(self):
        with self.assertRaises(pr.ParseError):
            pr.summarize(1, self._results("weird"), None,
                         run_id="r", started_at="t", duration_ms=0)

    def test_more_results_than_units_raises(self):
        with self.assertRaises(pr.ParseError):
            pr.summarize(1, self._results("done", "done"), None,
                         run_id="r", started_at="t", duration_ms=0)


class TestSummaryExitCode(unittest.TestCase):
    def _summary(self, **kwargs):
        base = {"failed": 0, "halt_reason": None}
        base.update(kwargs)
        return base

    def test_clean(self):
        self.assertEqual(pr.summary_exit_code(self._summary()), pr.EXIT_OK)

    def test_failures(self):
        self.assertEqual(pr.summary_exit_code(self._summary(failed=2)),
                         pr.EXIT_FAILURES)

    def test_halt_outranks_failures(self):
        self.assertEqual(
            pr.summary_exit_code(self._summary(failed=2, halt_reason="failed_streak")),
            pr.EXIT_HALTED)

    def test_dry_run_is_clean(self):
        self.assertEqual(pr.summary_exit_code(self._summary(halt_reason="dry_run")),
                         pr.EXIT_OK)


# ==========================================================================
# Path containment
# ==========================================================================
class TestContainment(_Harness):
    def test_relative_inside_root(self):
        resolved = pr.resolve_contained("results/a.txt", self.root)
        self.assertEqual(resolved,
                         os.path.join(os.path.realpath(self.root), "results", "a.txt"))

    def test_nonexistent_target_is_allowed(self):
        pr.resolve_contained("results/not-yet.json", self.root)

    def test_dotdot_escape_rejected(self):
        with self.assertRaises(pr.ContainmentError):
            pr.resolve_contained("../outside.txt", self.root)

    def test_absolute_outside_rejected(self):
        with self.assertRaises(pr.ContainmentError):
            pr.resolve_contained(os.path.join(self.tmp, "outside.txt"), self.root)

    def test_symlink_rejected(self):
        target = os.path.join(self.tmp, "outside.txt")
        with open(target, "w") as handle:
            handle.write("x")
        link = os.path.join(self.root, "link.txt")
        os.symlink(target, link)
        with self.assertRaises(pr.ContainmentError):
            pr.resolve_contained("link.txt", self.root)

    def test_symlinked_parent_directory_rejected(self):
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        os.symlink(outside, os.path.join(self.root, "escape"))
        with self.assertRaises(pr.ContainmentError):
            pr.resolve_contained("escape/a.txt", self.root)

    def test_resolve_paths_defaults_cwd_to_root(self):
        units = self.units(["a"])
        self.assertEqual(units[0].cwd_abs, os.path.realpath(self.root))


# ==========================================================================
# End-to-end: the happy path and delivery modes
# ==========================================================================
class TestRunHappyPath(_Harness):
    def test_three_units_succeed_and_receive_the_prompt_on_stdin(self):
        units = self.units(["a", "b", "c"])
        runner = self.runner(units, self.backend("echo"))
        summary = runner.run()
        self.assertEqual((summary["done"], summary["failed"], summary["pending"]),
                         (3, 0, 0))
        self.assertIsNone(summary["halt_reason"])
        with open(os.path.join(self.root, "results", "a.txt")) as handle:
            self.assertEqual(handle.read(), "do the thing")

    def test_json_output_format_accepts_valid_json(self):
        units = self.units(["a"], output_format="json", ext="json")
        summary = self.runner(units, self.backend("json")).run()
        self.assertEqual(summary["done"], 1)

    def test_argv_prompt_delivery(self):
        units = self.units(["a"])
        backend = self.backend("", program=FAKE_CLI_ARGV, delivery="argv")
        summary = self.runner(units, backend).run()
        self.assertEqual(summary["done"], 1)
        with open(os.path.join(self.root, "results", "a.txt")) as handle:
            self.assertEqual(handle.read(), "do the thing")

    def test_summary_carries_a_run_id_and_duration(self):
        summary = self.runner(self.units(["a"]), self.backend("echo")).run()
        self.assertTrue(summary["run_id"])
        self.assertGreaterEqual(summary["duration_ms"], 0)

    def test_child_output_is_logged_to_the_runtime_area(self):
        self.runner(self.units(["a"]), self.backend("echo")).run()
        self.assertTrue(os.path.isfile(os.path.join(self.runtime, "logs", "a.log")))


# ==========================================================================
# End-to-end: the artifact is the verdict
# ==========================================================================
class TestArtifactIsTheVerdict(_Harness):
    def test_exit_zero_without_an_artifact_is_a_failure(self):
        units = self.units(["a"])
        runner = self.runner(units, self.backend("silent"))
        summary = runner.run()
        self.assertEqual(summary["failed"], 1)
        result = self.result_by_id(runner)["a"]
        self.assertEqual((result.error_kind, result.exit_code),
                         ("missing_artifact", 0))

    def test_nonzero_exit_with_a_valid_artifact_is_a_success(self):
        units = self.units(["a"])
        runner = self.runner(units, self.backend("dirty-exit"))
        summary = runner.run()
        self.assertEqual(summary["done"], 1)
        self.assertEqual(self.result_by_id(runner)["a"].exit_code, 3)

    def test_blank_artifact_is_a_failure(self):
        units = self.units(["a"])
        runner = self.runner(units, self.backend("empty"))
        runner.run()
        self.assertEqual(self.result_by_id(runner)["a"].error_kind, "empty_artifact")

    def test_unparsable_json_artifact_is_a_failure(self):
        units = self.units(["a"], output_format="json", ext="json")
        runner = self.runner(units, self.backend("badjson"))
        runner.run()
        self.assertEqual(self.result_by_id(runner)["a"].error_kind,
                         "malformed_artifact")

    def test_the_same_bytes_pass_as_text(self):
        units = self.units(["a"])
        summary = self.runner(units, self.backend("badjson")).run()
        self.assertEqual(summary["done"], 1)


# ==========================================================================
# End-to-end: failure paths that had never been exercised
# ==========================================================================
class TestFailurePaths(_Harness):
    def test_missing_prompt_file(self):
        units = self.units(["a"], make_prompt=False)
        runner = self.runner(units, self.backend("echo"))
        summary = runner.run()
        self.assertEqual(summary["failed"], 1)
        result = self.result_by_id(runner)["a"]
        self.assertEqual((result.error_kind, result.failure_class),
                         ("missing_prompt", "permanent"))

    def test_backend_executable_does_not_exist(self):
        units = self.units(["a"])
        backend = pr.Backend(name="broken",
                             argv=("./definitely-not-a-real-binary", "{output_file}"))
        runner = self.runner(units, backend)
        summary = runner.run()
        self.assertEqual(summary["failed"], 1)
        result = self.result_by_id(runner)["a"]
        self.assertEqual((result.error_kind, result.failure_class),
                         ("spawn_failed", "permanent"))

    def test_a_broken_backend_trips_the_streak_instead_of_draining_the_queue(self):
        # Spawn failures never enter flight, so nothing throttles the dispatch loop;
        # without a streak check at dispatch time the whole queue burns in one pass.
        units = self.units([f"u{i}" for i in range(6)])
        backend = pr.Backend(name="broken",
                             argv=("./definitely-not-a-real-binary", "{output_file}"))
        summary = self.runner(units, backend, failed_streak_limit=3).run()
        self.assertEqual(summary["halt_reason"], "failed_streak")
        self.assertEqual((summary["failed"], summary["pending"]), (3, 3))

    def test_missing_prompts_also_trip_the_streak(self):
        units = self.units([f"u{i}" for i in range(6)], make_prompt=False)
        summary = self.runner(units, self.backend("echo"),
                              failed_streak_limit=3).run()
        self.assertEqual(summary["halt_reason"], "failed_streak")
        self.assertEqual((summary["failed"], summary["pending"]), (3, 3))

    def test_unit_timeout_kills_the_process(self):
        units = self.units(["a"])
        runner = self.runner(units, self.backend("sleep"), timeout=0.3)
        summary = runner.run()
        self.assertEqual(summary["failed"], 1)
        result = self.result_by_id(runner)["a"]
        self.assertEqual((result.error_kind, result.failure_class),
                         ("timeout", "transient"))

    def test_failed_streak_halts_before_draining_the_queue(self):
        # The shape of a backend that cannot authenticate: every unit fails at once.
        units = self.units(["a", "b", "c", "d", "e"])
        runner = self.runner(units, self.backend("silent"), max_parallel=1,
                             failed_streak_limit=3)
        summary = runner.run()
        self.assertEqual(summary["halt_reason"], "failed_streak")
        self.assertEqual(summary["failed"], 3)
        self.assertEqual(summary["pending"], 2)

    def test_failed_streak_limit_zero_disables_the_brake(self):
        units = self.units(["a", "b", "c", "d"])
        summary = self.runner(units, self.backend("silent"), max_parallel=1,
                              failed_streak_limit=0).run()
        self.assertIsNone(summary["halt_reason"])
        self.assertEqual(summary["failed"], 4)

    def test_max_wallclock_halts_the_run(self):
        units = self.units(["a", "b", "c"])
        runner = self.runner(units, self.backend("slow", extra="0.4"),
                             max_parallel=1, max_wallclock=0.2)
        summary = runner.run()
        self.assertEqual(summary["halt_reason"], "max_wallclock")
        self.assertEqual(summary["done"], 1)
        self.assertEqual(summary["pending"], 2)


# ==========================================================================
# End-to-end: idempotency, dry run, safety brakes
# ==========================================================================
class TestResumeAndBrakes(_Harness):
    def test_existing_valid_artifact_is_skipped(self):
        units = self.units(["a", "b"])
        with open(os.path.join(self.root, "results", "a.txt"), "w") as handle:
            handle.write("already done")
        runner = self.runner(units, self.backend("echo"))
        summary = runner.run()
        self.assertEqual((summary["skipped"], summary["done"]), (1, 1))
        # The skipped unit's artifact was not rewritten.
        with open(os.path.join(self.root, "results", "a.txt")) as handle:
            self.assertEqual(handle.read(), "already done")

    def test_rerunning_a_finished_queue_skips_everything(self):
        units = self.units(["a", "b"])
        self.runner(units, self.backend("echo")).run()
        summary = self.runner(units, self.backend("echo")).run()
        self.assertEqual((summary["skipped"], summary["done"]), (2, 0))

    def test_a_corrupt_artifact_is_redone_on_rerun(self):
        units = self.units(["a"], output_format="json", ext="json")
        self.runner(units, self.backend("badjson")).run()
        summary = self.runner(units, self.backend("json")).run()
        self.assertEqual((summary["skipped"], summary["done"]), (0, 1))

    def test_dry_run_dispatches_nothing_but_reports_skips(self):
        units = self.units(["a", "b"])
        with open(os.path.join(self.root, "results", "a.txt"), "w") as handle:
            handle.write("already done")
        summary = self.runner(units, self.backend("echo"), dry_run=True).run()
        self.assertEqual(summary["halt_reason"], "dry_run")
        self.assertEqual((summary["skipped"], summary["pending"]), (1, 1))
        self.assertFalse(os.path.exists(os.path.join(self.root, "results", "b.txt")))

    def test_graceful_kill_file_blocks_all_dispatch(self):
        open(os.path.join(self.runtime, ".STOP"), "w").close()
        units = self.units(["a", "b"])
        summary = self.runner(units, self.backend("echo")).run()
        self.assertEqual(summary["halt_reason"], "stop.graceful")
        self.assertEqual(summary["pending"], 2)
        self.assertFalse(os.path.exists(os.path.join(self.root, "results", "a.txt")))

    def test_hard_kill_file_terminates_units_in_flight(self):
        # Unit "a" drops the hard kill file and then hangs; both units are in flight
        # when the runner notices, so this exercises termination, not just gating.
        stop_hard = os.path.join(self.runtime, ".STOP.hard")
        units = self.units(["a", "b"])
        runner = self.runner(units, self.backend("trip-and-sleep", extra=stop_hard),
                             max_parallel=2, timeout=30)
        summary = runner.run()
        self.assertEqual(summary["halt_reason"], "stop.hard")
        # Terminated units produced no artifact, so they are pending, not failed:
        # a re-run picks them up unchanged.
        self.assertEqual(summary["pending"], 2)
        self.assertEqual(summary["failed"], 0)

    def test_hard_kill_file_outranks_graceful(self):
        open(os.path.join(self.runtime, ".STOP"), "w").close()
        open(os.path.join(self.runtime, ".STOP.hard"), "w").close()
        summary = self.runner(self.units(["a"]), self.backend("echo")).run()
        self.assertEqual(summary["halt_reason"], "stop.hard")

    def test_kill_file_paths_are_absolute(self):
        runner = self.runner(self.units(["a"]), self.backend("echo"))
        self.assertTrue(os.path.isabs(runner.stop))
        self.assertTrue(os.path.isabs(runner.stop_hard))

    def test_signal_flag_is_treated_as_a_hard_stop(self):
        runner = self.runner(self.units(["a"]), self.backend("echo"))
        runner._signalled = True
        summary = runner.run()
        self.assertEqual(summary["halt_reason"], "stop.hard")
        self.assertEqual(summary["pending"], 1)


# ==========================================================================
# End-to-end: parallelism and reporting
# ==========================================================================
class TestParallelAndReport(_Harness):
    def test_dispatch_never_exceeds_max_parallel(self):
        units = self.units([f"u{i}" for i in range(6)])
        runner = self.runner(units, self.backend("slow", extra="0.2"), max_parallel=2)
        summary = runner.run()
        self.assertEqual(summary["done"], 6)
        self.assertLessEqual(runner.peak_parallel, 2)

    def test_parallel_units_do_not_collide(self):
        units = self.units([f"u{i}" for i in range(6)])
        self.runner(units, self.backend("echo"), max_parallel=4).run()
        for unit in units:
            with open(unit.output_abs) as handle:
                self.assertEqual(handle.read(), "do the thing")

    def test_report_records_are_structured_only(self):
        report = os.path.join(self.tmp, "report.jsonl")
        units = self.units(["a", "b"])
        with open(os.path.join(self.root, "results", "b.txt"), "w") as handle:
            handle.write("already done")
        self.runner(units, self.backend("silent"), report_path=report).run()
        with open(report) as handle:
            records = [json.loads(line) for line in handle if line.strip()]
        self.assertEqual(len(records), 2)
        by_id = {r["id"]: r for r in records}
        self.assertEqual(by_id["a"]["status"], "failed")
        self.assertEqual(by_id["a"]["error_kind"], "missing_artifact")
        self.assertEqual(by_id["b"]["status"], "skipped")
        allowed = {"id", "status", "error_kind", "failure_class", "exit_code",
                   "duration_ms", "started_at"}
        for record in records:
            self.assertEqual(set(record), allowed)


# ==========================================================================
# CLI layer
# ==========================================================================
class TestCli(_Harness):
    def _registry(self, mode="echo", extra=""):
        path = os.path.join(self.tmp, "backends.json")
        argv = [sys.executable, "-c", FAKE_CLI, "{output_file}", mode, extra]
        with open(path, "w") as handle:
            json.dump({"schema_version": 1,
                       "backends": {"t": {"argv": argv,
                                          "prompt_delivery": "stdin"}}}, handle)
        return path

    def _queue(self, ids, **kwargs):
        path = os.path.join(self.tmp, "work.jsonl")
        with open(path, "w") as handle:
            for uid in ids:
                if kwargs.get("make_prompt", True):
                    self.write_prompt(uid)
                handle.write(json.dumps({
                    "id": uid,
                    "prompt_file": f"prompts/{uid}.md",
                    "output_file": f"results/{uid}.txt",
                }) + "\n")
        return path

    def _run_argv(self, *extra):
        return ["run", "--work", self._queue(["a", "b"]),
                "--backends", self._registry(), "--backend", "t",
                "--root", self.root, "--runtime-root", self.runtime, *extra]

    @staticmethod
    def _main(argv):
        """Invoke the CLI with its summary/error output captured, so a passing suite
        stays readable."""
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            return pr.main(argv)

    def test_run_returns_zero_when_clean(self):
        self.assertEqual(self._main(self._run_argv()), pr.EXIT_OK)

    def test_run_returns_failure_code(self):
        argv = ["run", "--work", self._queue(["a"]),
                "--backends", self._registry("silent"), "--backend", "t",
                "--root", self.root, "--runtime-root", self.runtime]
        self.assertEqual(self._main(argv), pr.EXIT_FAILURES)

    def test_run_returns_halt_code(self):
        open(os.path.join(self.runtime, ".STOP"), "w").close()
        self.assertEqual(self._main(self._run_argv()), pr.EXIT_HALTED)

    def test_dry_run_returns_zero(self):
        self.assertEqual(self._main(self._run_argv("--dry-run")), pr.EXIT_OK)

    def test_unknown_backend_is_a_config_error(self):
        argv = ["run", "--work", self._queue(["a"]),
                "--backends", self._registry(), "--backend", "nope",
                "--root", self.root, "--runtime-root", self.runtime]
        self.assertEqual(self._main(argv), pr.EXIT_CONFIG)

    def test_containment_violation_is_a_config_error(self):
        path = os.path.join(self.tmp, "work.jsonl")
        with open(path, "w") as handle:
            handle.write(json.dumps({"id": "a", "prompt_file": "../escape.md",
                                     "output_file": "results/a.txt"}) + "\n")
        argv = ["run", "--work", path, "--backends", self._registry(),
                "--backend", "t", "--root", self.root,
                "--runtime-root", self.runtime]
        self.assertEqual(self._main(argv), pr.EXIT_CONFIG)

    def test_validate_accepts_a_good_queue(self):
        argv = ["validate", "--work", self._queue(["a", "b"]),
                "--backends", self._registry(), "--backend", "t",
                "--root", self.root]
        self.assertEqual(self._main(argv), pr.EXIT_OK)

    def test_validate_reports_missing_prompts(self):
        argv = ["validate", "--work", self._queue(["a"], make_prompt=False),
                "--backends", self._registry(), "--backend", "t",
                "--root", self.root]
        self.assertEqual(self._main(argv), pr.EXIT_CONFIG)

    def test_stdout_is_exactly_one_json_object(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          "process_runner.py"), *self._run_argv()],
            capture_output=True, text=True, timeout=120)
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        summary = json.loads(lines[0])
        self.assertEqual(summary["total"], 2)


# ==========================================================================
# The runner stays vendor neutral
# ==========================================================================
class TestVendorNeutrality(unittest.TestCase):
    def test_runner_source_names_no_agent_cli(self):
        """Every vendor-specific token belongs in an operator-authored registry. If a
        product name lands in the runner, the abstraction has already leaked."""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "process_runner.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read().lower()
        for token in ("claude", "codex", "anthropic", "openai", "gemini", "cursor",
                      "copilot"):
            self.assertNotIn(token, source, f"vendor token {token!r} leaked into runner")


if __name__ == "__main__":
    unittest.main()
