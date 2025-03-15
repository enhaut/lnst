import time
import logging

from lnst.Tests.BaseTestModule import BaseTestModule
from lnst.Common.Parameters import DeviceParam, FloatParam, IntParam, ListParam


class InterfaceStatsMonitor(BaseTestModule):
    device = DeviceParam()
    duration = IntParam(default=10)
    sampling_period = FloatParam(default=1.0)
    stats = ListParam(default=["rx_bytes", "tx_bytes", "rx_packets", "tx_packets"])

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

            sample = {"timestamp": time.time()}
            for stat in self.params.stats:
                sample |= {stat: res[stat]}

            self._res_data.append(sample)
            time.sleep(self.params.sampling_period)

        return True

    def runtime_estimate(self):
        return self.params.duration + 3
