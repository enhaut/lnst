import time
import pprint
import logging

from lnst.Controller.Job import Job
from lnst.Devices.Device import Device
from lnst.Common.Parameters import IntParam
from lnst.Tests.InterfaceStatsMonitor import InterfaceStatsMonitor
from .ForwardingRecipe import ForwardingRecipe
from lnst.Tests.PktGen import NDRPktGenClient, PktgenController
from lnst.RecipeCommon.Perf.Measurements.BaseFlowMeasurement import Flow


class DropRateRecipe(ForwardingRecipe):
    ratep = IntParam(default=1_000_000)

    def do_perf_tests(self, recipe_config):
        self.find_ndr_rate(recipe_config)

    def find_ndr_rate(self, recipe_config):
        receiver_jobs = self._prepare_receiver(recipe_config)
        duration = max(job.what.runtime_estimate() for job in receiver_jobs.values())

        generator_jobs = self._prepare_generators(recipe_config, duration + 5)
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

            # for generator_job in generator_jobs:
            #     generator_job.kill()  # TODO: crashes on kill

        self._report_results(receiver_jobs)

    def _report_results(self, jobs: dict[Device, Job]):
        for dev, job in jobs.items():
            if job.passed:
                logging.info(f"RESULTS for {dev.name} ({self.params.ratep}): " + str(job.result))

                self.add_result(
                    job.passed,
                    f"Drop rate measurement ({self.params.ratep}pps) for {dev.name}",
                    data={dev.name: job.result},
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
                    "ratep": self.params.ratep,
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

    def _prepare_receiver(self, config) -> dict:
        configs = {}

        for flow_combinations in self.generate_flow_combinations(config):
            for flow in flow_combinations:
                if flow.receiver_nic not in configs:
                    configs[flow.receiver_nic] = {
                        "device": flow.receiver_nic,
                        "duration": flow.duration
                    }

                if self.matched.host2.eth1 not in configs:
                    configs[self.matched.host2.eth1] = {
                        "device": self.matched.host2.eth1,
                        "duration": flow.duration
                    }
        jobs = {}
        for device, cfg in configs.items():
            ndr = InterfaceStatsMonitor(**cfg)

            jobs[device] = device.netns.prepare_job(ndr)

        return jobs
