#!/usr/bin/env python3
"""Unit tests for cost.py.

What this protects is that nobody starts a batch without knowing its size. A run
whose cost only becomes visible while it is spending is the failure this module
exists to prevent, so an estimate that is missing must say so rather than read as
a small number.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cost

ROUTE = "queue:small-model"
OTHER_ROUTE = "subagent:default"


def _write(root, rel, content=""):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _scenario(sid="ac-001", prompt="do the thing", files=None):
    return {
        "skill": "acme",
        "id": sid,
        "prompt": prompt,
        "files": files or [],
        "expectations": [{"text": "it did the thing", "critical": True}],
    }


def _repo(root):
    _write(root, "skills/acme/SKILL.md", "body\n" * 50)
    _write(root, "inputs/project/a.md", "input\n" * 20)
    return os.path.join(root, "inputs")


class TestInputSize(unittest.TestCase):
    def test_counts_the_prompt_the_inputs_and_the_skill_text(self):
        with tempfile.TemporaryDirectory() as root:
            inputs = _repo(root)
            small = cost.input_bytes(root, inputs, "acme", _scenario())
            large = cost.input_bytes(root, inputs, "acme",
                                     _scenario(files=["project/a.md"]))
            self.assertGreater(large, small)
            self.assertGreater(small, 0)

    def test_a_missing_input_file_does_not_stop_the_estimate(self):
        # An estimate is advisory; refusing to produce one would leave the batch
        # unsized for a reason the run itself will report anyway.
        with tempfile.TemporaryDirectory() as root:
            inputs = _repo(root)
            self.assertGreater(
                cost.input_bytes(root, inputs, "acme", _scenario(files=["nope.md"])), 0)

    def test_approximate_tokens_scale_with_bytes(self):
        self.assertEqual(cost.approx_tokens(400), 100)
        self.assertEqual(cost.approx_tokens(1), 1)


class TestHistory(unittest.TestCase):
    def test_a_missing_history_reads_as_empty(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(cost.load_history(os.path.join(root, "none.json")), {})

    def test_an_observation_round_trips(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "state", "cost-history.json")
            history = cost.load_history(path)
            cost.record(history, "acme", "ac-001", ROUTE, input_bytes=1000,
                        input_tokens=250, output_tokens=4000, wall_seconds=120.0,
                        observed="2026-08-19")
            cost.save_history(path, history)
            again = cost.load_history(path)
            self.assertEqual(again["acme/ac-001"][ROUTE]["output_tokens"], 4000)

    def test_the_history_is_written_outside_the_target_tree(self):
        with tempfile.TemporaryDirectory() as root:
            _repo(root)
            path = os.path.join(root, "elsewhere", "cost-history.json")
            history = {}
            cost.record(history, "acme", "ac-001", ROUTE, input_bytes=10,
                        input_tokens=3, output_tokens=5, wall_seconds=1.0,
                        observed="2026-08-19")
            cost.save_history(path, history)
            self.assertEqual(os.listdir(os.path.join(root, "skills", "acme")),
                             ["SKILL.md"])


class TestEstimate(unittest.TestCase):
    def _history(self, input_bytes=1000, output_tokens=4000):
        history = {}
        cost.record(history, "acme", "ac-001", ROUTE, input_bytes=input_bytes,
                    input_tokens=cost.approx_tokens(input_bytes),
                    output_tokens=output_tokens, wall_seconds=120.0,
                    observed="2026-08-19")
        return history

    def test_a_scenario_never_run_is_unmeasured(self):
        estimate = cost.estimate({}, "acme", "ac-001", ROUTE, current_bytes=1000)
        self.assertFalse(estimate["measured"])
        self.assertIsNone(estimate["output_tokens"])

    def test_a_scenario_run_before_reports_what_it_cost(self):
        estimate = cost.estimate(self._history(), "acme", "ac-001", ROUTE,
                                 current_bytes=1000)
        self.assertTrue(estimate["measured"])
        self.assertEqual(estimate["output_tokens"], 4000)

    def test_the_estimate_scales_with_the_change_in_input_size(self):
        estimate = cost.estimate(self._history(), "acme", "ac-001", ROUTE,
                                 current_bytes=2000)
        self.assertEqual(estimate["input_tokens"], 500)

    def test_history_from_another_route_does_not_count(self):
        # Cost is a fact about the route it was observed on.
        estimate = cost.estimate(self._history(), "acme", "ac-001", OTHER_ROUTE,
                                 current_bytes=1000)
        self.assertFalse(estimate["measured"])


class TestDryRun(unittest.TestCase):
    def _dry_run(self, root, inputs, scenarios, history):
        return cost.dry_run(root, inputs, "acme", scenarios, ROUTE, history)

    def test_an_unmeasured_scenario_makes_the_batch_stop_after_the_first(self):
        with tempfile.TemporaryDirectory() as root:
            inputs = _repo(root)
            report = self._dry_run(root, inputs, [_scenario(), _scenario("ac-002")], {})
            self.assertTrue(report["stop_after_first"])
            self.assertEqual(report["unmeasured"], ["ac-001", "ac-002"])

    def test_a_fully_measured_batch_runs_straight_through(self):
        with tempfile.TemporaryDirectory() as root:
            inputs = _repo(root)
            scenarios = [_scenario(), _scenario("ac-002")]
            history = {}
            for scenario in scenarios:
                cost.record(history, "acme", scenario["id"], ROUTE,
                            input_bytes=cost.input_bytes(root, inputs, "acme", scenario),
                            input_tokens=10, output_tokens=100, wall_seconds=5.0,
                            observed="2026-08-19")
            report = self._dry_run(root, inputs, scenarios, history)
            self.assertFalse(report["stop_after_first"])
            self.assertEqual(report["unmeasured"], [])
            self.assertEqual(report["total"]["output_tokens"], 200)

    def test_the_total_leaves_out_what_it_cannot_measure(self):
        # Folding an unmeasured scenario in as zero would read as a small batch.
        with tempfile.TemporaryDirectory() as root:
            inputs = _repo(root)
            history = {}
            measured = _scenario()
            cost.record(history, "acme", "ac-001", ROUTE,
                        input_bytes=cost.input_bytes(root, inputs, "acme", measured),
                        input_tokens=10, output_tokens=100, wall_seconds=5.0,
                        observed="2026-08-19")
            report = self._dry_run(root, inputs, [measured, _scenario("ac-002")], history)
            self.assertEqual(report["total"]["output_tokens"], 100)
            self.assertEqual(report["unmeasured"], ["ac-002"])

    def test_the_dry_run_executes_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            inputs = _repo(root)
            before = json.dumps(sorted(os.listdir(root)))
            self._dry_run(root, inputs, [_scenario()], {})
            self.assertEqual(json.dumps(sorted(os.listdir(root))), before)


class TestCeiling(unittest.TestCase):
    def test_below_the_ceiling_the_batch_continues(self):
        self.assertIsNone(cost.ceiling_reached({"output_tokens": 100}, {"tokens": 1000}))

    def test_at_the_ceiling_the_batch_stops(self):
        self.assertIsNotNone(
            cost.ceiling_reached({"output_tokens": 1000}, {"tokens": 1000}))

    def test_a_seconds_ceiling_stops_a_runaway(self):
        self.assertIsNotNone(
            cost.ceiling_reached({"wall_seconds": 900.0}, {"seconds": 600}))

    def test_no_ceiling_never_stops(self):
        self.assertIsNone(cost.ceiling_reached({"output_tokens": 10 ** 9}, {}))


if __name__ == "__main__":
    unittest.main()


class TestApproximationIsAlwaysAvailable(unittest.TestCase):
    """Even with no history, the input side of a scenario is knowable.

    Reporting only "unmeasured" would read as "nothing is known about this
    batch", when in fact how much the executor has to read is already on disk.
    The approximation and the measurement are reported side by side and never
    folded together: one is derived from bytes, the other was observed.
    """

    def test_an_unmeasured_scenario_still_reports_an_input_approximation(self):
        estimate = cost.estimate({}, "acme", "ac-001", ROUTE, current_bytes=4000)
        self.assertFalse(estimate["measured"])
        self.assertEqual(estimate["approx_input_tokens"], 1000)
        self.assertIsNone(estimate["output_tokens"])

    def test_a_measured_scenario_reports_both_figures(self):
        history = {}
        cost.record(history, "acme", "ac-001", ROUTE, input_bytes=1000,
                    input_tokens=250, output_tokens=4000, wall_seconds=120.0,
                    observed="2026-08-19")
        estimate = cost.estimate(history, "acme", "ac-001", ROUTE, current_bytes=4000)
        self.assertEqual(estimate["approx_input_tokens"], 1000)
        self.assertEqual(estimate["output_tokens"], 4000)

    def test_the_report_totals_the_approximation_over_every_scenario(self):
        with tempfile.TemporaryDirectory() as root:
            inputs = _repo(root)
            report = cost.dry_run(root, inputs, "acme",
                               [_scenario(), _scenario("ac-002")], ROUTE, {})
            per_scenario = [s["approx_input_tokens"] for s in report["scenarios"]]
            self.assertEqual(report["approx_input_total"], sum(per_scenario))
            self.assertGreater(report["approx_input_total"], 0)
            self.assertEqual(report["total"]["output_tokens"], 0)


class TestCommandLine(unittest.TestCase):
    def test_recording_needs_no_inputs_directory(self):
        """`record` reads nothing from the inputs directory, so demanding one turns
        the documented invocation into an error."""
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "history.json")
            code = cost.main(["record", "--skill", "acme", "--scenario", "ac-001",
                              "--route", ROUTE, "--history", path,
                              "--input-bytes", "1000", "--input-tokens", "250",
                              "--output-tokens", "4000", "--wall-seconds", "120",
                              "--observed", "2026-08-19"])
            self.assertEqual(code, 0)
            self.assertEqual(cost.load_history(path)["acme/ac-001"][ROUTE]["output_tokens"],
                             4000)
