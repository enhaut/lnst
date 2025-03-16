from lnst.Recipes.ENRT.MeasurementGenerators.BaseFlowMeasurementGenerator import (
    BaseFlowMeasurementGenerator,
)
from lnst.RecipeCommon.Perf.Measurements.ForwardingMeasurement import ForwardingMeasurement
from collections.abc import Iterator, Collection
import itertools

from lnst.Common.Parameters import (
    Param,
    IntParam,
    ListParam,
    StrParam,
    ChoiceParam,
)

from lnst.Common.IpAddress import ip_version_string
from lnst.RecipeCommon.Perf.Measurements import Flow as PerfFlow
from lnst.RecipeCommon.Perf.Measurements import (
    IperfFlowMeasurement,
    NeperFlowMeasurement,
)
from lnst.RecipeCommon.endpoints import EndpointPair, IPEndpoint
from lnst.Recipes.ENRT.BaseEnrtRecipe import EnrtConfiguration


class ForwardingMeasurementGenerator(BaseFlowMeasurementGenerator):
    @property
    def net_perf_tool_class(self):
        def ForwardingMeasurement_partial(*args, **kwargs):
            return ForwardingMeasurement(*args, ratep=self.params.ratep, burst=self.params.burst, **kwargs)

        return ForwardingMeasurement_partial


    def generator_cpupin(self, flow_id: int) -> list[int]:
        # needs to be round-robin, pktgen doesn't support a generator
        # to be pinned to multiple CPUs. If single cpu is not sufficient,
        # just create more flows with same/different src/dst IPs/ports.
        return self._cpupin_based_on_policy(flow_id, self.params.perf_tool_cpu, "round-robin")

    def _create_perf_flows(
        self,
        endpoint_pairs: list[EndpointPair[IPEndpoint]],
        perf_test: str,
        msg_size,
    ) -> list[PerfFlow]:
        """
        Same as BaseFlowMeasurementGenerator._create_perf_flows, but without
        iterating over parallel processes. This is already done by generating
        multiple perf endpoint IPs with different destination IP in ForwardingRecipe.generate_perf_endpoints.
        """
        port_iter = itertools.count(12000)

        flows = []
        for i, endpoint_pair in enumerate(endpoint_pairs):
            client, server = endpoint_pair
            server_port = client_port = next(port_iter)
            flows.append(
                self._create_perf_flow(
                    perf_test,
                    client.device,
                    client.address,
                    client_port if perf_test != "mptcp_stream" else None,
                    server.device,
                    server.address,
                    server_port,
                    msg_size,
                    self.generator_cpupin(i),
                    self.receiver_cpupin(i),
                )
            )

        return flows
