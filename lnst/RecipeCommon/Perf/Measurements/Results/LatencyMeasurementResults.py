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
    def cached_samples(self):
        return self.latency.samples_slice(slice(1, -1))

    @property
    def uncached_samples(self):
        first = self.latency.samples_slice(slice(None, 1))
        last = self.latency.samples_slice(slice(-1, None))
        merged = first.merge_with(last)

        return merged

    @property
    def cached_latency_average(self):
        # using real_duration to exclude time between samples
        # NOTE: Latencymeasurement doesn't support variable samples count
        # if there are multiple measurements, so it's safe to take
        # length of first samples container
        return self.cached_samples.real_duration / (
            len(self.cached_samples[0]) - 2
        )
    
    @property
    def uncached_latency_average(self):
        return self.uncached_samples.real_duration / 2

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
        uncached_average = self.uncached_latency_average
        cached_average = self.cached_latency_average

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
        desc.append(
            "Uncached average / cached average ratio: {ratio:,f}".format(
                ratio=uncached_average / cached_average,
            )
        )

        return "\n".join(desc)
