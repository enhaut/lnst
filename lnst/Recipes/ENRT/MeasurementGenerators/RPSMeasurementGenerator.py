"""
Module with generator class for RPS Recipe.

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
)

from lnst.Recipes.ENRT.MeasurementGenerators.BaseFlowMeasurementGenerator import (
    BaseFlowMeasurementGenerator,
)
from lnst.RecipeCommon.Perf.Measurements.RPSMeasurement import (
    RPSMeasurement,
)

from lnst.RecipeCommon.Perf.Measurements import Flow as PerfFlow
from lnst.RecipeCommon.endpoints import EndpointPair, IPEndpoint


class RPSMeasurementGenerator(BaseFlowMeasurementGenerator):
    perf_tool_cpu = ListParam(mandatory=True)
    ratep = IntParam(default=-1)
    burst = IntParam(default=1)
    backlog_size = IntParam(default=1000)

    @property
    def net_perf_tool_class(self):
        def RPSMeasurement_partial(*args, **kwargs):
            return RPSMeasurement(
                *args,
                cpus=self.params.perf_tool_cpu,
                ratep=self.params.ratep,
                burst=self.params.burst,
                results_dir=f"/root/.lnst/results/{self.__class__.__name__}",
                **kwargs,
            )

        return RPSMeasurement_partial

    def generator_cpupin(self, flow_id: int) -> list[int]:
        return self._cpupin_based_on_policy(
            flow_id, self.params.perf_tool_cpu, "round-robin"
        )

    def _create_perf_flows(
        self,
        endpoint_pairs: list[EndpointPair[IPEndpoint]],
        perf_test: str,
        msg_size,
    ) -> list[PerfFlow]:
        flows = super()._create_perf_flows(endpoint_pairs, perf_test, msg_size)
        for flow in flows:
            flow.receiver_nic = self.matched.host2.eth0

        return flows
