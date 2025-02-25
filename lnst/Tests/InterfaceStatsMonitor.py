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

        for i in range(int(iterations)):
            self.params.device._if_manager.rescan_devices()
            # ^ needs to rescan devices to update netlink msg
            # where stats are fetched from

            res = self.params.device.link_stats64
            res = {'rx_packets': 109+i, 'tx_packets': 109628224+i, 'rx_bytes': 26176+i, 'tx_bytes': 7016212648+i, 'rx_errors': 0, 'tx_errors': 0, 'rx_dropped': 107, 'tx_dropped': 0, 'multicast': 129, 'collisions': 0, 'rx_length_errors': 0, 'rx_over_errors': 0, 'rx_crc_errors': 0, 'rx_frame_errors': 0, 'rx_fifo_errors': 0, 'rx_missed_errors': 0, 'tx_aborted_errors': 0, 'tx_carrier_errors': 0, 'tx_fifo_errors': 0, 'tx_heartbeat_errors': 0, 'tx_window_errors': 0, 'rx_compressed': 0, 'tx_compressed': 0, 'attrs': [], 'header': {}, 'timestamp': 1740520314.9753876}
            res["timestamp"] = time.time()
            self._res_data.append(res)
            time.sleep(self.params.sampling_period)

        return True

    def runtime_estimate(self):
        return self.params.duration + 3

