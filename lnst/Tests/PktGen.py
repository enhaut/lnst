import re
import time
import logging
from typing import Iterator
from subprocess import Popen

from lnst.Common.Utils import kmod_in_use
from lnst.Common.IpAddress import ipaddress, Ip4Address
from lnst.Tests.BaseTestModule import BaseTestModule, TestModuleError
from lnst.Common.Parameters import IntParam, IpParam, StrParam, ListParam


class PktGenResultsParser:
    def __init__(self, devs: list[str], res: dict) -> None:
        self._devs = devs
        self._res = res

    def _read_dev_outputs(self) -> Iterator[tuple[str, str]]:
        for device in self._devs:
            output = ""
            with open(f"/proc/net/pktgen/{device}", "r") as f:
                output = f.readlines()
            yield device, "\n".join(output)

    def _split_output(self, output: str) -> tuple:
        match = re.search(r"Params:(.+)Current:(.+)Result:\s(\w+)", output, re.DOTALL)
        if not match:
            raise TestModuleError("Could not parse pktgen devide output")

        return match.groups()

    def _parse_values(self, params) -> dict[str, str]:
        values = {}

        for key, value in re.findall(r"(\w+):?\s(\S+)", params, re.MULTILINE):
            values[key.lower()] = value

        return values

    def parse_dev_outputs(self):
        for device, output in self._read_dev_outputs():
            params, current, state = self._split_output(output)

            self._res[device] = {
                "params": self._parse_values(params),
                "current": self._parse_values(current),
                "state": state,
            }


class PktGen(BaseTestModule):
    """
    In the scope of this module, the physical interface is refered as `interface`.
    Pktgen device (interface@anything) is refered as device.

    Inspired by https://github.com/torvalds/linux/blob/master/samples/pktgen/pktgen_sample03_burst_single_flow.sh
    """

    cpus = ListParam(type=IntParam())  # each CPU is 1 generator

    pgctrl = StrParam(mandatory=False, default="/proc/net/pktgen/pgctrl")

    src_mac = StrParam(mandatory=False, default="90:e2:ba:ff:ff:ff")
    dst_mac = StrParam()

    src_ip = IpParam(
        mandatory=False, default=ipaddress("192.168.1.1")
    )  # IP doesn't really matter
    dst_ip = IpParam()

    interface = StrParam()

    count = IntParam(mandatory=False, default=0)  # 0 = no upper limit
    size = IntParam(mandatory=False, default=60)  # 4 bytes are added for CRC by NIC
    frags = IntParam(mandatory=False, default=1)
    burst = IntParam(mandatory=False, default=8)

    duration = IntParam(default=60)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        if not kmod_in_use("pktgen"):
            raise TestModuleError("pktgen module is not loaded")

        self._devices = []
        self._ip6 = True
        if isinstance(self.params.dst_ip, Ip4Address):
            self._ip6 = False

        self._res_data = {}
        self._output_parser = PktGenResultsParser(self._devices, self._res_data)

        self._pg_ctl("reset")

        self._configure_generator()

    def _write_command(self, file: str, cmd: str):
        with open(file, "w") as f:
            f.write(cmd + "\n")

    def _pg_ctl(self, cmd: str):
        self._write_command(self.params.pgctrl, cmd)

    def _pg_thread(self, thread: int, cmd: str):
        self._write_command(f"/proc/net/pktgen/kpktgend_{thread}", cmd)

    def _pg_set(self, thread: int, cmd: str):
        self._write_command(f"/proc/net/pktgen/{self.params.interface}@{thread}", cmd)

    def _configure_generator(self):
        logging.debug("Configuring generator")
        src = f"src{6 if self._ip6 else ''}"
        dest = f"dst{6 if self._ip6 else ''}"

        for cpu in self.params.cpus:
            dev = f"{self.params.interface}@{cpu}"
            logging.debug(f"Adding interface {self.params.interface} to cpu {cpu}")

            self._pg_thread(cpu, f"add_device {dev}")

            self._pg_set(cpu, f"flag QUEUE_MAP_CPU")
            self._pg_set(cpu, f"count {self.params.count}")
            self._pg_set(cpu, f"pkt_size {self.params.size}")
            self._pg_set(cpu, f"flag NO_TIMESTAMP")

            self._pg_set(cpu, f"dst_mac {self.params.dst_mac}")
            self._pg_set(cpu, f"src_mac {self.params.src_mac}")

            self._pg_set(cpu, f"{dest}_min {self.params.dst_ip}")
            self._pg_set(cpu, f"{dest}_max {self.params.dst_ip}")
            self._pg_set(cpu, f"{src}_min {self.params.src_ip}")
            self._pg_set(cpu, f"{src}_max {self.params.src_ip}")

            self._pg_set(cpu, f"burst {self.params.burst}")
            self._devices.append(dev)

    def _deconfigure_generator(self):
        logging.debug("Deconfiguring generator")
        for cpu in self.params.cpus:
            self._pg_thread(cpu, "rem_device_all")

        self._pg_ctl("reset")

    def run(self):
        logging.debug("Starting generator")
        pktgen = Popen("echo 'start' > /proc/net/pktgen/pgctrl", shell=True)
        # ^^ echoing start to controller is blocking => needs to be separated

        time.sleep(self.params.duration)

        pktgen.kill()  # stops pktgen

        self._output_parser.parse_dev_outputs()

        self._deconfigure_generator()
        return True
