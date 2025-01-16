import time
import logging

from lnst.Tests.BaseTestModule import BaseTestModule
from lnst.Common.Parameters import DeviceParam, FloatParam, IntParam


class InterfaceStatsMonitor(BaseTestModule):
    device = DeviceParam()
    duration = IntParam(default=10)
    sampling_period = FloatParam(default=1.0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._res_data = []

    def run(self):
        logging.info(
            f"Gathering stats for {self.params.duration} on device {self.params.device.name}"
        )
        iterations = self.params.duration / self.params.sampling_period

        for _ in range(int(iterations)):
            self.params.device._if_manager.rescan_devices()
            # ^ needs to rescan devices to update netlink msg
            # where stats are fetched from

            res = self.params.device.link_stats64
            res["timestamp"] = time.time()
            self._res_data.append(res)
            time.sleep(self.params.sampling_period)

        return True

    def runtime_estimate(self):
        return self.params.duration + 3

