from lnst.Common.Parameters import ConstParam, ChoiceParam, StrParam
from lnst.Recipes.ENRT.MeasurementGenerators.BaseFlowMeasurementGenerator import BaseFlowMeasurementGenerator


from lnst.Tests.XDPBench import XDP_BENCH_COMMANDS


class XDPFlowMeasurementGenerator(BaseFlowMeasurementGenerator):
    net_perf_tool = ConstParam(value="xdp-bench")

    xdp_command = ChoiceParam(type=StrParam, choices=XDP_BENCH_COMMANDS)

    def generate_perf_measurements_combinations(self, config):
        combinations = super(BaseFlowMeasurementGenerator, self).generate_perf_measurements_combinations(config)

        for flow_combination in self.generate_flow_combinations(config):
            perf_class = self.net_perf_tool_class
            combinations.append([perf_class(flow_combination, self.params.xdp_command)])
        
        return combinations

