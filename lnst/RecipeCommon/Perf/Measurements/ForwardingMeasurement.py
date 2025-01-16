from lnst.RecipeCommon.Perf.Measurements.Results.AggregatedForwardingMeasurementResults import AggregatedForwardingMeasurementResults
from lnst.RecipeCommon.Perf.Measurements.Results.ForwardingMeasurementResults import ForwardingMeasurementResults
from .XDPBenchMeasurement import XDPBenchMeasurement
from lnst.Controller.Recipe import BaseRecipe
from lnst.RecipeCommon.Perf.Measurements.Results.AggregatedXDPBenchMeasurementResults import (
    AggregatedXDPBenchMeasurementResults,
)
from lnst.Controller.RecipeResults import ResultType
from lnst.RecipeCommon.Perf.Measurements.BaseFlowMeasurement import (
    Flow,
    NetworkFlowTest,
)
from lnst.RecipeCommon.Perf.Measurements.MeasurementError import MeasurementError
from lnst.RecipeCommon.Perf.Measurements.Results.XDPBenchMeasurementResults import (
    XDPBenchMeasurementResults,
)
from lnst.RecipeCommon.Perf.Results import (
    PerfInterval,
    ParallelPerfResult,
    SequentialPerfResult,
)
from lnst.Tests.PktGen import PktGen
from lnst.Tests.XDPBench import XDPBench
from lnst.Controller.Job import Job
from lnst.Controller.RecipeResults import MeasurementResult, ResultType
from lnst.RecipeCommon.Perf.Measurements.BaseFlowMeasurement import BaseFlowMeasurement

from lnst.Tests.InterfaceStatsMonitor import InterfaceStatsMonitor
from lnst.RecipeCommon.Perf.Results import PerfInterval, SequentialPerfResult


class ForwardingMeasurement(XDPBenchMeasurement):
    def __init__(self, flows, recipe_conf=None):
        super().__init__(flows, "drop", "native", recipe_conf=recipe_conf)
    
    def start(self):
        net_flows = self._prepare_flows()
        for flow in net_flows:
            flow.forwarder_job.start(bg=True)
            flow.server_job.start(bg=True)
            flow.client_job.start(bg=True)
            # server starts immediately, no need to wait
            self._running_measurements.append(flow)

        self._running_measurements = net_flows

    def _prepare_forwarder(self, flow):
        monitor = InterfaceStatsMonitor(
            device=flow.receiver.eth1,
            duration=flow.duration + flow.warmup_duration * 2
        )
        job = flow.receiver.prepare_job(monitor)

        return job

    def _prepare_server(self, flow):
        params = {
            "command": "drop",
            "xdp_mode": self.mode,
            "interface": flow.generator.receiver_ns.eth1,
            "duration": flow.duration + flow.warmup_duration * 2,
        }
        bench = XDPBench(**params)
        job = flow.generator.receiver_ns.prepare_job(bench)

        return job

    def _prepare_client(self, flow: Flow):
        params = {
            "src_if": flow.generator_nic,
            "dst_mac": flow.receiver_nic.hwaddr,
            "src_ip": flow.generator_bind,
            "dst_ip": flow.receiver_bind,
            "cpus": flow.generator_cpupin,
            "pkt_size": flow.msg_size,
            "duration": flow.duration + flow.warmup_duration * 2,
            "src_port": flow.generator_port,
            "dst_port": flow.receiver_port,
        }
        pktgen = PktGen(**params)

        job = flow.generator.prepare_job(pktgen)

        return job

    def _prepare_flows(self) -> list[NetworkFlowTest]:
        flows = []
        for flow in self.flows:
            forwarder = self._prepare_forwarder(flow)
            client = self._prepare_client(flow)
            server = self._prepare_server(flow)

            net_flow = NetworkFlowTest(flow, server, client)
            net_flow.forwarder_job = forwarder

            flows.append(net_flow)

        return flows

    def finish(self):
        try:
            for flow in self._running_measurements:
                forwarder_job = flow.forwarder_job.what
                flow.forwarder_job.wait(timeout=forwarder_job.runtime_estimate())
        finally:
            for flow in self._running_measurements:
                flow.forwarder_job.kill()

        super().finish()

    def collect_results(self):
        results = []
        for flow in self._finished_measurements:
            result = ForwardingMeasurementResults(measurement=self, measurement_success=True, flow=flow, warmup_duration=flow.flow.warmup_duration)
            result.generator_results = self._parse_generator_results(flow.client_job)
            result.receiver_results = self._parse_receiver_results(flow.server_job)
            result.forwarder_results = self._parse_forwarder_results(flow.forwarder_job)
            results.append(result)

        return results

    def _parse_forwarder_results(self, job):
        results = ParallelPerfResult()  # container for multiple NICs
        results.append(self.parse_samples(job.result, "tx_packets", "packets"))

        return results

    def parse_samples(self, raw_samples: list[dict], metric: str, unit: str) -> SequentialPerfResult:
        result = SequentialPerfResult()
        previous_timestamp = 0
        previous_value = None

        for raw_sample in raw_samples:
            if not previous_timestamp:
                previous_timestamp = raw_sample["timestamp"]
                previous_value = raw_sample[metric]
                continue

            sample = PerfInterval(
                raw_sample[metric] - previous_value,
                raw_sample["timestamp"] - previous_timestamp,
                unit,
                raw_sample["timestamp"],
            )
            result.append(sample)

            previous_timestamp = raw_sample["timestamp"]
            previous_value = raw_sample[metric]
        return result

    def _aggregate_flows(self, old_flow, new_flow):
        if old_flow is not None and old_flow.flow is not new_flow.flow:
            return MeasurementError("Aggregating different flows")

        new_result = AggregatedForwardingMeasurementResults(measurement=self, flow=new_flow.flow)
        new_result.add_results(old_flow)
        new_result.add_results(new_flow)

        return new_result

    @classmethod
    def report_results(cls, recipe: BaseRecipe, results: list[AggregatedForwardingMeasurementResults]):
        for result in results:
            generator = result.generator_results
            receiver = result.receiver_results
            forwarder = result.forwarder_results

            desc = []
            desc.append(result.describe())

            recipe_result = ResultType.PASS
            metrics = {"Generator": generator, "Receiver": receiver, "Forwarder": forwarder}
            for name, metric_result in metrics.items():
                if cls._invalid_flow_duration(metric_result):
                    recipe_result = ResultType.FAIL
                    desc.append("{} has invalid duration!".format(name))

            recipe_result = MeasurementResult(
                "forwarding",
                result=(
                    ResultType.PASS
                    if result.measurement_success
                    else ResultType.FAIL
                ),
                description="\n".join(desc),
                data={
                    "generator_results": generator,
                    "receiver_results": receiver,
                    "flow_results": result,
                    "forwarder_results": forwarder,
                },
            )
            recipe.add_custom_result(recipe_result)
