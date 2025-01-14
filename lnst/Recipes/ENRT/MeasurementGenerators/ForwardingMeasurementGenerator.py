from lnst.Common.Parameters import ChoiceParam, StrParam
from lnst.RecipeCommon.Perf.Measurements.XDPBenchMeasurement import XDPBenchMeasurement
from lnst.Recipes.ENRT.MeasurementGenerators.BaseFlowMeasurementGenerator import (
    BaseFlowMeasurementGenerator,
)
import itertools
from lnst.RecipeCommon.Perf.Measurements.ForwardingMeasurement import ForwardingMeasurement


class ForwardingMeasurementGenerator(BaseFlowMeasurementGenerator):
    @property
    def net_perf_tool_class(self):
        def ForwardingMeasurement_partial(*args, **kwargs):
            return ForwardingMeasurement(*args, **kwargs)

        return ForwardingMeasurement_partial
    
    def _create_perf_flows(
        self,
        endpoint_pairs,
        perf_test: str,
        msg_size,
    ) -> list:
        port_iter = itertools.count(12000)

        flows = []
        for endpoint_pair in endpoint_pairs:
            client, server = endpoint_pair
            for i in range(1):  # TODO:vymenit za perf_parallel_processes, potom je cela tato funkcia zbytocna a moze sa pouzit parent implementacia

                server_port = client_port = next(port_iter)
                flow = self._create_perf_flow(
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

                flows.append(flow)

        return flows
