from lnst.Common.Parameters import ChoiceParam, StrParam
from lnst.RecipeCommon.Perf.Measurements.XDPBenchMeasurement import XDPBenchMeasurement
from lnst.Recipes.ENRT.MeasurementGenerators.BaseFlowMeasurementGenerator import (
    BaseFlowMeasurementGenerator,
)

from lnst.Tests.XDPBench import XDP_BENCH_COMMANDS


class XDPFlowMeasurementGenerator(BaseFlowMeasurementGenerator):
    xdp_command = ChoiceParam(type=StrParam, choices=XDP_BENCH_COMMANDS)

    @property
    def net_perf_tool_class(self):
        return XDPBenchMeasurement

    def generate_perf_measurements_combinations(self, config):
        combinations = super(
            BaseFlowMeasurementGenerator, self
        ).generate_perf_measurements_combinations(config)

        for flow_combination in self.generate_flow_combinations(config):
            measurement = self.net_perf_tool_class(
                flow_combination, self.params.xdp_command
            )
            endpoints = self.extract_endpoints(config, [measurement])

            combinations.append([self.params.cpu_perf_tool(endpoints), measurement])

        return combinations
