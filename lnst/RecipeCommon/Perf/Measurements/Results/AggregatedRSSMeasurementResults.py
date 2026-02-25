"""
Module implementing results container for aggregated RSS measurement results.

Copyright 2025 Red Hat, Inc.
Licensed under the GNU General Public License, version 2 as
published by the Free Software Foundation; see COPYING for details.
"""

__author__ = """
sdobron@redhat.com (Samuel Dobron)
"""


from lnst.RecipeCommon.Perf.Results import SequentialPerfResult
from .RSSMeasurementResults import RSSMeasurementResults
from lnst.RecipeCommon.Perf.Measurements.MeasurementError import MeasurementError


class AggregatedRSSMeasurementResults(RSSMeasurementResults):
    def __init__(self, measurement, flows, warmup_duration=0):
        super().__init__(measurement, True, flows, warmup_duration=warmup_duration)

        self._generator_results = SequentialPerfResult()
        self._receiver_results = SequentialPerfResult()
        self._forwarded_results = SequentialPerfResult()
        self._drop_results = SequentialPerfResult()

        self._individual_results: list[RSSMeasurementResults] = []

    @property
    def individual_results(self) -> list[RSSMeasurementResults]:
        return self._individual_results

    @property
    def measurement_success(self) -> bool:
        if self.individual_results:
            return all(res.measurement_success for res in self.individual_results)
        else:
            return False

    def add_results(self, results):
        if results is None:
            return
        elif isinstance(results, AggregatedRSSMeasurementResults):
            self._individual_results.extend(results.individual_results)
            self.generator_results.extend(results.generator_results)
            self.receiver_results.extend(results.receiver_results)
            self.forwarded_results.extend(results.forwarded_results)
            self.drop_results.extend(results.drop_results)
        elif isinstance(results, RSSMeasurementResults):
            self._individual_results.append(results)
            self.generator_results.append(results.generator_results)
            self.receiver_results.append(results.receiver_results)
            self.forwarded_results.append(results.forwarded_results)
            self.drop_results.append(results.drop_results)
        else:
            raise MeasurementError("Adding incorrect results.")
