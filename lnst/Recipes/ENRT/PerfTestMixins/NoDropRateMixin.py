import time
import pprint

from lnst.Controller.Job import Job
from lnst.Devices.Device import Device
from lnst.Common.Parameters import FloatParam, IntParam
from lnst.Tests.PktGen import NDRPktGenClient, PktgenController
from lnst.RecipeCommon.Perf.Measurements.BaseFlowMeasurement import Flow


class NoDropRateMixin:
    """
    This is more like functional recipe that tries to find
    amount of packets that can be generated against receiver
    without being dropped.
    """
    drop_rate = FloatParam(default=0.0)
    min_step = FloatParam(default=5)
    max_iterations = IntParam(default=100)

    def do_perf_tests(self, recipe_config):
        for i in range(self.params.perf_iterations):
            self.find_ndr_rate(recipe_config)

    def find_ndr_rate(self, recipe_config):
        receiver_jobs = self._prepare_receiver(recipe_config)
        duration = max(job.what.runtime_estimate() for job in receiver_jobs.values())

        generator_jobs = self._prepare_generators(recipe_config, duration + 30)
        for generator_job in generator_jobs:  # 2 seconds for setup
            generator_job.start(bg=True)

        time.sleep(1)

        for receiver_job in receiver_jobs.values():
            receiver_job.start(bg=True)

        try:
            for receiver_job in receiver_jobs.values():
                receiver_job.wait(timeout=duration + 5)

            for generator_job in generator_jobs:
                generator_job.wait(timeout=5)
        finally:
            for receiver_job in receiver_jobs.values():
                receiver_job.kill()

            for generator_job in generator_jobs:
                generator_job.kill()

        self._report_results(receiver_jobs)

    def _report_results(self, jobs: dict[Device, Job]):
        for dev, job in jobs.items():
            desc = f"{self.__class__.__name__} on {dev.name}:"
            results = {}
            if job.passed:
                results = {"acceptable_pps": job.result[0], "drop_rate": job.result[1]}

            self.add_result(
                job.passed,
                "\n".join([desc, pprint.pformat(results, indent=4, width=1)]),
                data=results,
            )

    def _prepare_generators(self, config, max_duration):
        configs = {}
        for flow_combinations in self.generate_flow_combinations(config):
            for flow in flow_combinations:
                params = {
                    "src_if": flow.generator_nic,
                    "dst_mac": flow.receiver_nic.hwaddr,
                    "src_ip": flow.generator_bind,
                    "dst_ip": flow.receiver_bind,
                    "cpu": flow.generator_cpupin[0],
                    "pkt_size": flow.msg_size,
                    "duration": max_duration,
                    "src_port": flow.generator_port,
                    "dst_port": flow.receiver_port,
                    "export_controller": self._get_ctl_address(flow),
                }

                # it's pktgen, so single instance per MACHINE, thats why machine
                # is used as a key
                if flow.generator not in configs:
                    configs[flow.generator] = []

                if params not in configs[flow.generator]:
                    # This is not separate measurement, so we need
                    # to filter unnecessary flows manually.
                    # If there are multiple perf_tests this will iterate
                    # multiple times, so it would add the same params
                    # multiple times
                    configs[flow.generator].append(params)

        jobs = []
        for machine, pktgen_cfg in configs.items():
            pktgen = PktgenController(config=pktgen_cfg)
            jobs.append(machine.prepare_job(pktgen))

        return jobs

    def _get_ctl_address(self, flow):
        """
        Receiver port is uniquely set by _create_perf_flow, so we can just
        reuse it. If you need to pin it to different port, you can override
        this method.
        """
        return flow.generator_bind, flow.generator_port - 4000

    def _prepare_receiver(self, config) -> dict:
        configs = {}

        for flow_combinations in self.generate_flow_combinations(config):
            for flow in flow_combinations:
                if flow.receiver_nic not in configs:
                    configs[flow.receiver_nic] = {
                        "generators": [],
                        "nic": self._get_nic_to_watch(flow),
                        "drop_rate": self.params.drop_rate,
                        "cutoff_step": self.params.min_step,
                        "max_iterations": self.params.max_iterations,
                    }

                endpoint = self._get_ctl_address(flow)
                if endpoint not in configs[flow.receiver_nic]["generators"]:
                    # This is not separate measurement, so we need
                    # to filter unnecessary flows manually.
                    # If there are multiple perf_tests this will iterate
                    # multiple times, so it would add the same endpoint
                    # multiple times.
                    configs[flow.receiver_nic]["generators"].append(endpoint)

        jobs = {}
        for device, cfg in configs.items():
            ndr = NDRPktGenClient(**cfg)

            jobs[device] = device.netns.prepare_job(ndr)

        return jobs

    def _get_nic_to_watch(self, flow: Flow):
        """
        If you need to measure drop rate on some other interface than
        flow.receiver_nic (e.g. if the machine is just receiving packets),
        you can override this method.
        """
        return flow.receiver_nic
