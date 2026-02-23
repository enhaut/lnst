"""
Module implementing RSS Measurement.

Copyright 2025 Red Hat, Inc.
Licensed under the GNU General Public License, version 2 as
published by the Free Software Foundation; see COPYING for details.
"""

__author__ = """
sdobron@redhat.com (Samuel Dobron)
"""

import signal
from typing import Literal

from lnst.Tests.XDPBenchRedirectCpu import XDPBenchRedirectCpu
from lnst.RecipeCommon.Perf.Results import (
    PerfInterval,
    ParallelPerfResult,
    SequentialPerfResult,
)
from lnst.Devices.VlanDevice import VlanDevice
from lnst.Controller.RecipeResults import ResultType
from lnst.Tests.PktGen import PktgenController

from lnst.Tests.InterfaceStatsMonitor import InterfaceStatsMonitor
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
    This class implements RSS (Receive Side Scaling) measurement.

    It uses pktgen to generate packets from host1 to host2.
    On host2, depending on the mode:
    - xdp mode: xdp-bench redirect-cpu receives and redistributes packets
    - rps mode: InterfaceStatsMonitor tracks rx_packets

    :param mode: "xdp" or "rps" - which RSS distribution mechanism to use
    :param cpus: target CPUs for xdp-bench redirect-cpu
    :param xdp_program: -p flag for xdp-bench (default "l4-hash")
    :param xdp_remote_action: -r flag for xdp-bench (default "pass")
    :param ratep: pktgen rate limit (default -1, unlimited)
    :param burst: pktgen burst (default 1)
    """

    def __init__(
        self,
        flows,
        mode: Literal["xdp", "rps"] = "xdp",
        cpus: list[int] = None,
        xdp_program: str = "l4-hash",
        xdp_remote_action: str = "pass",
        ratep=-1,
        burst=1,
        recipe_conf=None,
    ):
        super().__init__(recipe_conf=recipe_conf)
        self._flows = flows
        self._mode = mode
        self._cpus = cpus or []
        self._xdp_program = xdp_program
        self._xdp_remote_action = xdp_remote_action
        self._ratep = ratep
        self._burst = burst

        self._generator_job = None  # pktgen
        self._receiver_job = None  # xdp-bench redirect-cpu or InterfaceStatsMonitor

        self._finished_generator_job = None
        self._finished_receiver_job = None

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

        self._receiver_job.start(bg=True)
        self._generator_job.start(bg=True)

    def _prepare_jobs(self):
        self._generator_job = self._prepare_client()

        if self._mode == "xdp":
            self._receiver_job = self._prepare_server_xdp()
        else:
            self._receiver_job = self._prepare_server_rps()

        for flow in self.flows:
            net_flow = NetworkFlowTest(flow, self._receiver_job, self._generator_job)
            self._net_flows.append(net_flow)

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

    def _prepare_server_xdp(self):
        """
        Prepares xdp-bench redirect-cpu at the receiver.
        """
        sample_flow = self.flows[0]
        receiver_nic = self._real_dev(sample_flow.receiver_nic)

        bench = XDPBenchRedirectCpu(
            interface=receiver_nic,
            cpus=self._cpus,
            program=self._xdp_program,
            remote_action=self._xdp_remote_action,
            duration=sample_flow.duration + sample_flow.warmup_duration * 2,
        )
        job = sample_flow.receiver.prepare_job(bench)

        return job

    def _prepare_server_rps(self):
        """
        Prepares InterfaceStatsMonitor at the receiver for RPS mode.
        """
        sample_flow = self.flows[0]
        receiver_nic = self._real_dev(sample_flow.receiver_nic)

        monitor = InterfaceStatsMonitor(
            device=receiver_nic,
            stats=["rx_packets"],
        )
        job = sample_flow.receiver.prepare_job(monitor)

        return job

    def finish(self):
        try:
            self._generator_job.wait(
                timeout=self._generator_job.what.runtime_estimate()
            )
            if self._mode == "rps":
                self._receiver_job.kill(signal.SIGINT)
                self._receiver_job.wait()
            else:
                self._receiver_job.wait(
                    timeout=self._receiver_job.what.runtime_estimate()
                )
        finally:
            self._generator_job.kill()
            self._receiver_job.kill()

        self._finished_generator_job = self._generator_job
        self._finished_receiver_job = self._receiver_job

        self._generator_job = None
        self._receiver_job = None

    def collect_results(self):
        generator_results = self._parse_generator_results()

        if self._mode == "xdp":
            receiver_results, forwarded_results = self._parse_receiver_results_xdp()
        else:
            receiver_results = self._parse_receiver_results_rps()
            forwarded_results = ParallelPerfResult(
                [
                    SequentialPerfResult(
                        PerfInterval(
                            0, interval.duration, "packets", interval.timestamp
                        )
                        for interval in receiver_results
                    )
                ]
            )

        flows = [net_flow.flow for net_flow in self._net_flows]
        warmup_duration = flows[0].warmup_duration if flows else 0

        result = RSSMeasurementResults(
            measurement=self,
            measurement_success=bool(receiver_results) and bool(generator_results),
            flows=flows,
            warmup_duration=warmup_duration,
        )
        result.generator_results = generator_results
        result.receiver_results = receiver_results
        result.forwarded_results = forwarded_results
        breakpoint()
        self._net_flows = []
        return [result]

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

    def _parse_receiver_results_xdp(self):
        """
        Parse xdp-bench redirect-cpu results.

        - receiver_results: SequentialPerfResult of total received pkt/s
        - forwarded_results: ParallelPerfResult with one SequentialPerfResult
          per CPU (each CPU is a separate flow due to l4-hash)
        """
        receiver_results = SequentialPerfResult()

        if not self._finished_receiver_job.passed:
            return receiver_results, ParallelPerfResult()

        forwarded_results = ParallelPerfResult()
        for _ in self._cpus:
            forwarded_results.append(SequentialPerfResult())

        for sample in self._finished_receiver_job.result:
            receiver_results.append(
                PerfInterval(
                    sample["received"],
                    sample["duration"],
                    "packets",
                    sample["timestamp"],
                )
            )

            for cpu, pkts in sample["forwarded_per_cpu"].items():
                forwarded_results[
                    self._cpus.index(cpu)
                ].append(  # TODO: more inteligent mapping of cpu to flow instead of round-robin
                    PerfInterval(
                        pkts,
                        sample["duration"],
                        "packets",
                        sample["timestamp"],
                    )
                )

        # breakpoint()
        return receiver_results, forwarded_results

    def _parse_receiver_results_rps(self):
        """
        Parse InterfaceStatsMonitor results (rx_packets only).
        """
        result = SequentialPerfResult()
        if not self._finished_receiver_job.passed:
            return result

        raw_samples = self._finished_receiver_job.result
        previous_timestamp = raw_samples[0]["timestamp"]
        previous_value = raw_samples[0]["rx_packets"]

        for raw_sample in raw_samples[1:]:
            sample = PerfInterval(
                raw_sample["rx_packets"] - previous_value,
                raw_sample["timestamp"] - previous_timestamp,
                "packets",
                raw_sample["timestamp"],
            )
            result.append(sample)

            previous_timestamp = raw_sample["timestamp"]
            previous_value = raw_sample["rx_packets"]

        return result

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

        desc = []
        desc.append(result.describe())

        metrics_result = ResultType.PASS
        metrics = {
            "Generator": generator,
            "Receiver": receiver,
        }
        data = {
            "generator_results": generator,
            "receiver_results": receiver,
            "forwarded_results": forwarded,
        }

        if forwarded:
            metrics["Forwarded"] = forwarded

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
