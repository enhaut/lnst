"""
Module with generator class for RSS Recipe.

Copyright 2025 Red Hat, Inc.
Licensed under the GNU General Public License, version 2 as
published by the Free Software Foundation; see COPYING for details.
"""

__author__ = """
sdobron@redhat.com (Samuel Dobron)
"""

from lnst.Common.Parameters import (
    IntParam,
    ListParam,
    StrParam,
    ChoiceParam,
)

from lnst.Recipes.ENRT.MeasurementGenerators.BaseFlowMeasurementGenerator import (
    BaseFlowMeasurementGenerator,
)
from lnst.RecipeCommon.Perf.Measurements.RSSMeasurement import (
    RSSMeasurement,
)
from lnst.RecipeCommon.Perf.Measurements.BaseFlowMeasurement import BaseFlowMeasurement

from lnst.RecipeCommon.Perf.Measurements import Flow as PerfFlow
from lnst.RecipeCommon.endpoints import EndpointPair, IPEndpoint


class RSSMeasurementGenerator(BaseFlowMeasurementGenerator):
    perf_tool_cpu = ListParam(mandatory=True)
    ratep = IntParam(default=-1)
    burst = IntParam(default=1)
    rss_mode = ChoiceParam(type=StrParam, choices=["xdp", "rps"], default="xdp")
    xdp_redirect_program = StrParam(default="l4-hash")
    xdp_redirect_remote_action = StrParam(default="pass")

    @property
    def net_perf_tool_class(self):
        def RSSMeasurement_partial(*args, **kwargs):
            return RSSMeasurement(
                *args,
                mode=self.params.rss_mode,
                cpus=self.params.perf_tool_cpu,
                xdp_program=self.params.xdp_redirect_program,
                xdp_remote_action=self.params.xdp_redirect_remote_action,
                ratep=self.params.ratep,
                burst=self.params.burst,
                **kwargs,
            )

        return RSSMeasurement_partial

    def generator_cpupin(self, flow_id: int) -> list[int]:
        """
        Needs to be round-robin, pktgen doesn't support a generator
        to be pinned to multiple CPUs. If single cpu is not sufficient,
        just create more flows with same/different src/dst IPs/ports.
        """
        return self._cpupin_based_on_policy(
            flow_id, self.params.perf_tool_cpu, "round-robin"
        )

    def _create_perf_flows(
        self,
        endpoint_pairs: list[EndpointPair[IPEndpoint]],
        perf_test: str,
        msg_size,
    ) -> list[PerfFlow]:
        """
        :class:`RSSMeasurement` needs `Flow.receiver_nic` to be set
        for all flows.
        """
        flows = super()._create_perf_flows(endpoint_pairs, perf_test, msg_size)
        for flow in flows:
            flow.receiver_nic = self.matched.host2.eth0

        return flows
