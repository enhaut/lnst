from lnst.RecipeCommon.Perf.Measurements.Results.BaseMeasurementResults import BaseMeasurementResults


class CPUMeasurementResults(BaseMeasurementResults):
    def __init__(self, measurement, host, cpu):
        super(CPUMeasurementResults, self).__init__(measurement)
        self._host = host
        self._cpu = cpu
        self._utilization = None

    @property
    def host(self):
        return self._host

    @property
    def cpu(self):
        return self._cpu

    @property
    def utilization(self):
        return self._utilization

    @utilization.setter
    def utilization(self, value):
        self._utilization = value
