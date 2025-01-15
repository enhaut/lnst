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



class ForwardingMeasurement(XDPBenchMeasurement):
    def __init__(self, flows, recipe_conf=None):
        super().__init__(flows, "drop", "native", recipe_conf=recipe_conf)

    def _prepare_forwarder(self, flow):
        pass

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
            client = self._prepare_client(flow)
            # forwarder = self._prepare_forwarder(flow)
            server = self._prepare_server(flow)
            net_flow = NetworkFlowTest(flow, server, client)
            flows.append(net_flow)

        return flows
