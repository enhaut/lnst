from lnst.Recipes.ENRT.MeasurementGenerators.BaseFlowMeasurementGenerator import (
    BaseFlowMeasurementGenerator,
)
from lnst.RecipeCommon.Perf.Measurements.ForwardingMeasurement import ForwardingMeasurement


class ForwardingMeasurementGenerator(BaseFlowMeasurementGenerator):
    @property
    def net_perf_tool_class(self):
        def ForwardingMeasurement_partial(*args, **kwargs):
            return ForwardingMeasurement(*args, **kwargs)

        return ForwardingMeasurement_partial
