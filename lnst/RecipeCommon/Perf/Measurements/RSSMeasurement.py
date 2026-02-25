"""
Module implementing base RSS Measurement.

Copyright 2025 Red Hat, Inc.
Licensed under the GNU General Public License, version 2 as
published by the Free Software Foundation; see COPYING for details.
"""

__author__ = """
sdobron@redhat.com (Samuel Dobron)
"""

import json
import os
import signal
import logging
import time

from lnst.Tests.TCIngDropMonitor import TCIngDropMonitor
from lnst.RecipeCommon.Perf.Results import (
    PerfInterval,
    ParallelPerfResult,
    SequentialPerfResult,
)
from lnst.Devices.VlanDevice import VlanDevice
from lnst.Controller.RecipeResults import ResultType
from lnst.Tests.PktGen import PktgenController

from lnst.RecipeCommon.Perf.Measurements.BaseFlowMeasurement import NetworkFlowTest
from lnst.RecipeCommon.Perf.Measurements.MeasurementError import MeasurementError
from lnst.RecipeCommon.Perf.Measurements.BaseFlowMeasurement import BaseFlowMeasurement
from lnst.RecipeCommon.Perf.Measurements.Results.RSSMeasurementResults import (
    RSSMeasurementResults,
)
from lnst.RecipeCommon.Perf.Measurements.Results.AggregatedRSSMeasurementResults import (
    AggregatedRSSMeasurementResults,
)
from lnst.Controller.RecipeResults import MeasurementResult


class RSSMeasurement(BaseFlowMeasurement):
    """
    Base class for RSS/RPS measurements.

    It uses pktgen to generate packets from host1 to host2.
    TCIngDropMonitor counts per-CPU drops at TC ingress on host2.

    Subclasses add mode-specific receiver jobs (xdp-bench, etc).

    :param cpus: target CPUs for packet distribution
    :param ratep: pktgen rate limit (default -1, unlimited)
    :param burst: pktgen burst (default 1)
    """

    def __init__(
        self,
        flows,
        cpus: list[int] = None,
        ratep=-1,
        burst=1,
        recipe_conf=None,
        results_dir=None,
    ):
        super().__init__(recipe_conf=recipe_conf)
        self._flows = flows
        self._cpus = cpus or []
        self._ratep = ratep
        self._burst = burst
        self._results_dir = results_dir

        self._generator_job = None  # pktgen
        self._receiver_job = None  # mode-specific (xdp-bench, etc.)
        self._drop_monitor_job = None  # TCIngDropMonitor

        self._finished_generator_job = None
        self._finished_receiver_job = None
        self._finished_drop_monitor_job = None

        self._net_flows = []

    @property
    def flows(self):
        return self._flows

    def start(self):
        if not all(
            flow.receiver_nic == self.flows[0].receiver_nic for flow in self.flows
        ):
            raise MeasurementError("All flows must have the same receiver_nic")
        if not all(flow.generator == self.flows[0].generator for flow in self.flows):
            raise MeasurementError("Multiple generators are not supported")
        if not all(flow.duration == self.flows[0].duration for flow in self.flows):
            raise MeasurementError("All flows must have the same duration")
        if not all(
            flow.warmup_duration == self.flows[0].warmup_duration for flow in self.flows
        ):
            raise MeasurementError("All flows must have the same warmup duration")

        self._prepare_jobs()

        self._drop_monitor_job.start(bg=True)
        if self._receiver_job:
            self._receiver_job.start(bg=True)
        self._generator_job.start(bg=True)

    def _prepare_jobs(self):
        self._generator_job = self._prepare_client()
        self._drop_monitor_job = self._prepare_drop_monitor()
        self._prepare_receiver()

        for flow in self.flows:
            net_flow = NetworkFlowTest(flow, self._drop_monitor_job, self._generator_job)
            self._net_flows.append(net_flow)

    def _prepare_receiver(self):
        """Override in subclasses to set self._receiver_job."""
        pass

    def _prepare_client(self):
        config = []
        for flow in self.flows:
            config.append(
                {
                    "src_if": self._real_dev(flow.generator_nic),
                    "dst_mac": flow.receiver_nic.hwaddr,
                    "src_ip": flow.generator_bind,
                    "dst_ip": flow.receiver_bind,
                    "cpu": flow.generator_cpupin[
                        0
                    ],  # RSSMeasGen round-robins cpus, so this will be list with 1 cpu only
                    "pkt_size": flow.msg_size,
                    "duration": flow.duration + flow.warmup_duration * 2,
                    "src_port": flow.generator_port,
                    "dst_port": flow.receiver_port,
                    "ratep": int(
                        self._ratep / self._burst
                    ),  # pktgen internally does ratep * burst
                    "burst": self._burst,
                }
            )

        pktgen = PktgenController(config=config)

        job = self.flows[0].generator.prepare_job(pktgen)

        return job

    def _prepare_drop_monitor(self):
        """
        Prepares TCIngDropMonitor at the receiver to count per-CPU drops.
        """
        sample_flow = self.flows[0]
        receiver_nic = self._real_dev(sample_flow.receiver_nic)

        monitor = TCIngDropMonitor(
            device=receiver_nic,
            cpus=self._cpus,
        )
        job = sample_flow.receiver.prepare_job(monitor)

        return job

    def finish(self):
        try:
            self._generator_job.wait(
                timeout=self._generator_job.what.runtime_estimate()
            )
            if self._receiver_job:
                self._receiver_job.wait(
                    timeout=self._receiver_job.what.runtime_estimate()
                )
        finally:
            self._generator_job.kill()
            if self._receiver_job:
                self._receiver_job.kill()

        self._drop_monitor_job.kill(signal.SIGINT)
        self._drop_monitor_job.wait()

        self._finished_generator_job = self._generator_job
        self._finished_receiver_job = self._receiver_job
        self._finished_drop_monitor_job = self._drop_monitor_job

        self._generator_job = None
        self._receiver_job = None
        self._drop_monitor_job = None

    def collect_results(self):
        self._log_raw_results()

        generator_results = self._parse_generator_results()
        drop_results = self._parse_drop_monitor_results()
        receiver_results, forwarded_results = self._parse_receiver_results()

        flows = [net_flow.flow for net_flow in self._net_flows]
        warmup_duration = flows[0].warmup_duration if flows else 0

        result = RSSMeasurementResults(
            measurement=self,
            measurement_success=bool(drop_results) and bool(generator_results),
            flows=flows,
            warmup_duration=warmup_duration,
        )
        result.generator_results = generator_results
        result.receiver_results = receiver_results
        result.forwarded_results = forwarded_results
        result.drop_results = drop_results

        self._net_flows = []
        return [result]

    def _parse_receiver_results(self):
        """Override in subclasses. Returns (receiver_results, forwarded_results)."""
        return SequentialPerfResult(), ParallelPerfResult()

    def _log_raw_results(self):
        raw = {}

        if self._finished_generator_job and self._finished_generator_job.passed:
            raw["generator"] = self._finished_generator_job.result

        if self._finished_receiver_job and self._finished_receiver_job.passed:
            raw["receiver"] = self._finished_receiver_job.result

        if self._finished_drop_monitor_job and self._finished_drop_monitor_job.passed:
            raw["drop_monitor"] = self._finished_drop_monitor_job.result

        json_str = json.dumps(raw, indent=2, default=str)
        logging.info("RSSMeasurement raw results:\n%s", json_str)

        if self._results_dir:
            os.makedirs(self._results_dir, exist_ok=True)
            path = os.path.join(
                self._results_dir, f"rss_{int(time.time())}.json"
            )
            with open(path, "w") as f:
                f.write(json_str)
            logging.info("RSSMeasurement results saved to %s", path)

    def _parse_generator_results(self) -> ParallelPerfResult:
        """
        pktgen results parser
        """
        nic_results = {}
        if not self._finished_generator_job.passed:
            return ParallelPerfResult()

        for nic, raw_results in self._finished_generator_job.result.items():
            instance_results = SequentialPerfResult()

            for raw_result in raw_results:
                sample = PerfInterval(
                    raw_result["packets"],
                    raw_result["duration"],
                    "packets",
                    raw_result["timestamp"],
                )
                instance_results.append(sample)

            nic_results[nic] = instance_results

        return ParallelPerfResult(nic_results.values())

    def _map_cpu_to_flow_id(self, cpu):
        """
        Map a CPU id to a flow index. Currently a dumb 1:1 mapping
        based on position in self._cpus.
        """
        return self._cpus.index(cpu)

    def _parse_drop_monitor_results(self) -> ParallelPerfResult:
        """
        Parse TCIngDropMonitor results into a ParallelPerfResult with
        one SequentialPerfResult per CPU.
        """
        if not self._finished_drop_monitor_job:
            return ParallelPerfResult()

        if not self._finished_drop_monitor_job.passed:
            return ParallelPerfResult()

        results = ParallelPerfResult()
        for _ in self._cpus:
            results.append(SequentialPerfResult())

        for sample in self._finished_drop_monitor_job.result:
            for cpu, drops in sample["drops_per_cpu"].items():
                cpu = int(cpu)
                results[self._map_cpu_to_flow_id(cpu)].append(
                    PerfInterval(
                        drops,
                        sample["duration"],
                        "packets",
                        sample["timestamp"],
                    )
                )

        return results

    def _real_dev(self, device):
        if isinstance(device, VlanDevice):
            return device.realdev

        return device

    def _aggregate_flows(self, old_flow, new_flow):
        if old_flow is None:
            return new_flow

        if isinstance(old_flow, AggregatedRSSMeasurementResults):
            old_flow.add_results(new_flow)
            return old_flow
        else:
            new_result = AggregatedRSSMeasurementResults(
                measurement=self, flows=new_flow.flows
            )
            new_result.add_results(old_flow)
            new_result.add_results(new_flow)
            return new_result

    @classmethod
    def _report_flow_results(cls, recipe, result):
        generator = result.generator_results
        receiver = result.receiver_results
        forwarded = result.forwarded_results
        drop = result.drop_results

        desc = []
        desc.append(result.describe())

        metrics_result = ResultType.PASS
        metrics = {
            "Generator": generator,
        }
        data = {
            "generator_results": generator,
            "receiver_results": receiver,
            "forwarded_results": forwarded,
            "drop_results": drop,
        }

        if receiver:
            metrics["Receiver"] = receiver

        if forwarded:
            metrics["Forwarded"] = forwarded

        if drop:
            metrics["TC Drops"] = drop

        for name, metric_result in metrics.items():
            if cls._invalid_flow_duration(metric_result):
                metrics_result = ResultType.FAIL
                desc.append("{} has invalid duration!".format(name))

        recipe_result = MeasurementResult(
            "rss",
            result=(
                ResultType.PASS
                if result.measurement_success and metrics_result
                else ResultType.FAIL
            ),
            description="\n".join(desc),
            data=data,
        )
        recipe.add_custom_result(recipe_result)

    @staticmethod
    def aggregate_multi_flow_results(results):
        """
        With the new structure, results are already aggregated per measurement.
        This method just returns the results as-is.
        """
        if len(results) == 1:
            return results
        raise MeasurementError(
            "RSSMeasurement.aggregate_multi_flow_results called with multiple "
            "results! RSSMeasurement should produce single result per measurement "
            "(already aggregated)."
        )
