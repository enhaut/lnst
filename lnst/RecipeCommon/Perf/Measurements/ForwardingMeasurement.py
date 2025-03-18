from lnst.RecipeCommon.Perf.Measurements.Results.AggregatedForwardingMeasurementResults import (
    AggregatedForwardingMeasurementResults,
)
from lnst.RecipeCommon.Perf.Measurements.Results.ForwardingMeasurementResults import (
    ForwardingMeasurementResults,
)
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
from lnst.Tests.PktGen import PktgenController, PktgenDevice
from lnst.Tests.XDPBench import XDPBench
from lnst.Controller.Job import Job
from lnst.Controller.RecipeResults import MeasurementResult, ResultType
from lnst.RecipeCommon.Perf.Measurements.BaseFlowMeasurement import BaseFlowMeasurement

from lnst.Tests.InterfaceStatsMonitor import InterfaceStatsMonitor
from lnst.RecipeCommon.Perf.Results import PerfInterval, SequentialPerfResult


class ForwardingMeasurement(XDPBenchMeasurement):
    def __init__(self, flows, ratep=-1, burst=1, recipe_conf=None):
        super().__init__(flows, "drop", "native", recipe_conf=recipe_conf)
        self._ratep = ratep
        self._burst = burst

        self._client_job = None
        self._server_jobs = {}
        self._forwarder_jobs = {}

        self._net_flows = []

    def start(self):
        self._prepare_flows()

        for server_job in self._server_jobs.values():
            server_job.start(bg=True)

        for forwarder_job in self._forwarder_jobs.values():
            forwarder_job.start(bg=True)

        self._client_job.start(bg=True)

    def _prepare_forwarder(self, flow):
        if flow.receiver.eth1 in self._forwarder_jobs:
            return self._forwarder_jobs[flow.receiver.eth1]

        monitor = InterfaceStatsMonitor(
            device=flow.receiver.eth1, duration=flow.duration + flow.warmup_duration * 2, stats=["tx_packets"]
        )
        job = flow.receiver.prepare_job(monitor)
        self._forwarder_jobs[flow.receiver.eth1] = job

        return job

    def _prepare_server(self, flow):
        if flow.generator.receiver_ns.eth1 in self._server_jobs:
            return self._server_jobs[flow.generator.receiver_ns.eth1]

        params = {
            "command": "drop",
            "xdp_mode": self.mode,
            "interface": flow.generator.receiver_ns.eth1,
            "duration": flow.duration + flow.warmup_duration * 2,
        }
        bench = XDPBench(**params)
        job = flow.generator.receiver_ns.prepare_job(bench)

        self._server_jobs[flow.generator.receiver_ns.eth1] = job
        return job

    def _prepare_client(self):
        config = []
        for flow in self.flows:
            config.append(
                {
                    "src_if": flow.generator_nic,
                    "dst_mac": flow.receiver_nic.hwaddr,
                    "src_ip": flow.generator_bind,
                    "dst_ip": flow.receiver_bind,
                    "cpu": flow.generator_cpupin[
                        0
                    ],  # FwdMeasGen round-robins cpus, so this will be list with 1 cpu only
                    "pkt_size": flow.msg_size,
                    "duration": flow.duration + flow.warmup_duration * 2,
                    "src_port": flow.generator_port,
                    "dst_port": flow.receiver_port,
                    "ratep": int(self._ratep / self._burst),
                    "burst": self._burst
                }
            )

        pktgen = PktgenController(config=config)

        job = flow.generator.prepare_job(pktgen)

        return job

    def _prepare_flows(self) -> list[NetworkFlowTest]:
        self._client_job = self._prepare_client()

        for flow in self.flows:
            forwarder = self._prepare_forwarder(flow)
            server = self._prepare_server(flow)

            net_flow = NetworkFlowTest(flow, server, self._client_job)
            net_flow.forwarder_job = forwarder

            self._net_flows.append(net_flow)

    def finish(self):
        try:
            self._client_job.wait(timeout=self._client_job.what.runtime_estimate())

            for forwarder_job in self._forwarder_jobs.values():
                forwarder_job.wait(timeout=forwarder_job.what.runtime_estimate())

            for server_job in self._server_jobs.values():
                server_job.wait(timeout=server_job.what.runtime_estimate())
        finally:
            self._client_job.kill()

            for forwarder_job in self._forwarder_jobs.values():
                forwarder_job.kill()

            for server_job in self._server_jobs.values():
                server_job.kill()

    def collect_results(self):
        results = []

        receiver_results = {}
        for inf, job in self._server_jobs.items():
            receiver_results[inf] = self._parse_receiver_results(job)

        forwarder_results = {}
        for inf, job in self._forwarder_jobs.items():
            forwarder_results[inf] = self._parse_forwarder_results(job)

        generator_results = self._parse_generator_results(self._client_job)

        for net_flow in self._net_flows:  # TODO: iterovat cez ten network flow
            flow = net_flow.flow
            result = ForwardingMeasurementResults(
                measurement=self,
                measurement_success=True,
                flow=net_flow,
                warmup_duration=flow.warmup_duration,
            )
            result.generator_results = generator_results[
                PktgenDevice.name_template(
                    flow.generator_nic.name, flow.generator_cpupin[0]
                )
            ]
            result.forwarder_results = self._spread_results(
                receiver_results[flow.generator.receiver_ns.eth1],
                flow,
                lambda cum_flow, curr_flow: cum_flow.receiver.eth1
                == curr_flow.receiver.eth1,
            )
            result.receiver_results = self._spread_results(
                forwarder_results[flow.receiver.eth1],
                flow,
                lambda cum_flow, curr_flow: cum_flow.generator.receiver_ns.eth1
                == curr_flow.generator.receiver_ns.eth1,
            )

            results.append(result)

        return results

    def _parse_generator_results(self, job: Job) -> dict[str, SequentialPerfResult]:
        results = {}

        for nic, raw_results in job.result.items():
            instance_results = SequentialPerfResult()  # instance (device) of pktgen
            for raw_result in raw_results:
                sample = PerfInterval(
                    raw_result["packets"],
                    raw_result["duration"],
                    "packets",
                    raw_result["timestamp"],
                )
                instance_results.append(sample)
            results[nic] = instance_results

        return results

    def _parse_forwarder_results(self, job):
        results = SequentialPerfResult()
        results.append(self.parse_samples(job.result, "tx_packets", "packets"))

        return results

    def _spread_results(self, device_results, flow, comparison_func):
        spread_results = SequentialPerfResult()

        flows_to_device = len([f for f in self._flows if comparison_func(f, flow)])

        for sample in device_results[0]:
            spread_results.append(
                PerfInterval(
                    sample.value / flows_to_device,
                    sample.duration,
                    sample.unit,
                    sample.start_timestamp,
                )
            )

        return spread_results

    def parse_samples(
        self, raw_samples: list[dict], metric: str, unit: str
    ) -> SequentialPerfResult:
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

        new_result = AggregatedForwardingMeasurementResults(
            measurement=self, flow=new_flow.flow
        )
        new_result.add_results(old_flow)
        new_result.add_results(new_flow)

        return new_result

    @classmethod
    def report_results(
        cls, recipe: BaseRecipe, results: list[AggregatedForwardingMeasurementResults]
    ):
        generated = 0
        forwarded = 0
        received = 0

        for result in results:
            generator = result.generator_results
            receiver = result.receiver_results
            forwarder = result.forwarder_results

            desc = []
            desc.append(result.describe())

            recipe_result = ResultType.PASS
            metrics = {
                "Generator": generator,
                "Receiver": receiver,
                "Forwarder": forwarder,
            }
            for name, metric_result in metrics.items():
                if cls._invalid_flow_duration(metric_result):
                    recipe_result = ResultType.FAIL
                    desc.append("{} has invalid duration!".format(name))

            recipe_result = MeasurementResult(
                "forwarding",
                result=(
                    ResultType.PASS if result.measurement_success else ResultType.FAIL
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
            generated += generator.average
            forwarded += forwarder.average
            received += receiver.average

        agg_results = {
                "generator_results": generated,
                "receiver_results": received,
                "forwarder_results": forwarded,
            }
        desc = ["Total results:"] + [
            "{}: {}".format(name, result) for name, result in agg_results.items()
        ]

        recipe_result = MeasurementResult(
            "forwarding",
            result=ResultType.PASS,
            description="\n".join(desc),
            data=agg_results,
        )
        recipe.add_custom_result(recipe_result)
