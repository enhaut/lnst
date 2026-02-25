"""
Module implementing XDP redirect-cpu measurement.

Copyright 2025 Red Hat, Inc.
Licensed under the GNU General Public License, version 2 as
published by the Free Software Foundation; see COPYING for details.
"""

__author__ = """
sdobron@redhat.com (Samuel Dobron)
"""

from lnst.Tests.XDPBenchRedirectCpu import XDPBenchRedirectCpu
from lnst.RecipeCommon.Perf.Results import (
    PerfInterval,
    ParallelPerfResult,
    SequentialPerfResult,
)
from lnst.RecipeCommon.Perf.Measurements.RSSMeasurement import RSSMeasurement


class XDPRedirectCPUMeasurement(RSSMeasurement):
    """
    XDP redirect-cpu measurement.

    Runs xdp-bench redirect-cpu on the receiver to redistribute packets
    across CPUs, plus TCIngDropMonitor from the base class.

    :param xdp_program: -p flag for xdp-bench (default "l4-hash")
    :param xdp_remote_action: -r flag for xdp-bench (default "pass")
    """

    def __init__(
        self,
        flows,
        cpus: list[int] = None,
        xdp_program: str = "l4-hash",
        xdp_remote_action: str = "pass",
        backlog_size: int = 512,
        ratep=-1,
        burst=1,
        recipe_conf=None,
        results_dir=None,
    ):
        super().__init__(
            flows,
            cpus=cpus,
            ratep=ratep,
            burst=burst,
            recipe_conf=recipe_conf,
            results_dir=results_dir,
        )
        self._xdp_program = xdp_program
        self._xdp_remote_action = xdp_remote_action
        self._backlog_size = backlog_size

    def _prepare_receiver(self):
        sample_flow = self.flows[0]
        receiver_nic = self._real_dev(sample_flow.receiver_nic)

        bench = XDPBenchRedirectCpu(
            interface=receiver_nic,
            cpus=self._cpus,
            program=self._xdp_program,
            remote_action=self._xdp_remote_action,
            queue_size=self._backlog_size,
            duration=sample_flow.duration + sample_flow.warmup_duration * 2,
        )
        self._receiver_job = sample_flow.receiver.prepare_job(bench)

    def _parse_receiver_results(self):
        """
        Parse xdp-bench redirect-cpu results.

        - receiver_results: SequentialPerfResult of total received pkt/s
        - forwarded_results: ParallelPerfResult with one SequentialPerfResult
          per CPU (each CPU is a separate flow due to l4-hash)
        """
        receiver_results = SequentialPerfResult()

        if not self._finished_receiver_job or not self._finished_receiver_job.passed:
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
                    self._map_cpu_to_flow_id(cpu)
                ].append(
                    PerfInterval(
                        pkts,
                        sample["duration"],
                        "packets",
                        sample["timestamp"],
                    )
                )

        return receiver_results, forwarded_results
