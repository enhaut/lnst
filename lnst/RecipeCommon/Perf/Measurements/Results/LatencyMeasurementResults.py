from lnst.RecipeCommon.Perf.Results import SequentialPerfResult
from lnst.RecipeCommon.Perf.Measurements.Results.FlowMeasurementResults import (
    FlowMeasurementResults,
)
from lnst.RecipeCommon.Perf.Measurements.MeasurementError import MeasurementError
from .BaseMeasurementResults import BaseMeasurementResults


class LatencyMeasurementResults(BaseMeasurementResults):
    def __init__(self, flow, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._latency_samples = SequentialPerfResult()  # samples are ALWAYS sequential
        self.flow = flow

    @property
    def latency(self) -> SequentialPerfResult:
        return self._latency_samples

    @latency.setter
    def latency(self, value: SequentialPerfResult):
        self._latency_samples = value

    @property
    def latency_cached(self):
        return self.latency.samples_slice(slice(1, -1))  # [1:-1]

    @property
    def latency_uncached(self):
        return self.latency.samples_slice(slice(None, 1))  # [:1]

    @property
    def metrics(self) -> list[str]:
        return ["latency_cached", "latency_uncached"]

    def add_results(self, results):
        if results is None:
            return
        if isinstance(results, LatencyMeasurementResults):
            self.latency.append(results.latency)
        else:
            raise MeasurementError("Adding incorrect results.")

    def time_slice(self, start, end):
        result_copy = LatencyMeasurementResults(self.measurement, self.flow)

        result_copy.latency = self.latency.time_slice(start, end)

        return self

    def describe(self) -> str:
        # TODO: doriesit
        cached_average = self.latency_cached.duration / (
            len(self.latency_cached[0]) - 2
        )  # TODO: atleast 3 sampels are required
        uncached_average = self.latency_uncached.duration / 2

        desc = []
        desc.append(str(self.flow))
        desc.append(
            "Generator <-> receiver cached latency (average):   {latency:,f} {unit}.".format(
                latency=cached_average, unit=self.latency.unit
            )
        )
        desc.append(
            "Generator <-> receiver uncached latency (average): {latency:,f} {unit}.".format(
                latency=uncached_average, unit=self.latency.unit
            )
        )

        return "\n".join(desc)
