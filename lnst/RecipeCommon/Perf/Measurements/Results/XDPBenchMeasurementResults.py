from lnst.RecipeCommon.Perf.Results import ParallelPerfResult, SequentialPerfResult
from lnst.RecipeCommon.Perf.Measurements.Results.FlowMeasurementResults import FlowMeasurementResults
from lnst.RecipeCommon.Perf.Measurements.MeasurementError import MeasurementError


class XDPBenchMeasurementResults(FlowMeasurementResults):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._generator_results = ParallelPerfResult()  # multiple instances of pktgen
        self._receiver_results = ParallelPerfResult()  # single instance of xdpbench


    def add_results(self, results):
        if results is None:
            return
        if isinstance(results, XDPBenchMeasurementResults):
            self.generator_results.append(results.generator_results)
            self.receiver_results.append(results.receiver_results)
        else:
            raise MeasurementError("Adding incorrect results.")

    
    def time_slice(self, start, end):
        result_copy = XDPBenchMeasurementResults(self.measurement, self.flow, warmup_duration=0)

        result_copy.generator_results = self.generator_results.time_slice(start, end)
        result_copy.receiver_results = self.receiver_results.time_slice(start, end)

        return result_copy

    # @property
    # def start_timestamp(self):
    #     return min(
    #         [
    #             self.generator_results.start_timestamp,
    #             self.receiver_results.start_timestamp,
    #         ]
    #     )
    #
    # @property
    # def end_timestamp(self):
    #     return max(
    #         [
    #             self.generator_results.end_timestamp,
    #             self.receiver_results.end_timestamp,
    #         ]
    #     )
    #
    # @property
    # def warmup_end(self):
    #     if self.warmup_duration == 0:
    #         return self.start_timestamp
    #
    #     return max(
    #         [
    #             parallel[self.warmup_duration - 1].end_timestamp
    #             for parallel in (*self.generator_results, *self.receiver_results)
    #         ]
    #     )
    #
    # @property
    # def warmdown_start(self):
    #     if self.warmup_duration == 0:
    #         return self.end_timestamp
    #
    #     return min(
    #         [
    #             parallel[-self.warmup_duration].start_timestamp
    #             for parallel in (*self.generator_results, *self.receiver_results)
    #         ]
    #     )
