import re
import time
import socket
import logging
from math import ceil
from ipaddress import IPv4Address
from dataclasses import dataclass, field
from subprocess import Popen, check_output, CalledProcessError
from threading import Thread
from typing import Iterator, Union, Optional

from lnst.Common.Utils import kmod_loaded
from lnst.Common.IpAddress import Ip4Address
from lnst.Tests.BaseTestModule import BaseTestModule, TestModuleError
from lnst.Common.Parameters import (
    IntParam,
    IpParam,
    StrParam,
    ListParam,
    DeviceParam,
    FloatParam,
)
from lnst.Devices.Device import Device


class PktGenResultsSampler:
    def __init__(self, devs: list[str], duration: int) -> None:
        """
        PktGen output is just a table with current stats of devices. Therefore,
        each device has a separate thread that captures current status of device
        each second for `duration`.
        """
        self._devs = devs
        self._duration = duration

        self._sampling_threads: list[Thread] = []
        self._raw_samples = {}

    def start_sampling(self):
        """
        This is a separate method just to emphasize that pktgen
        needs to be started immediately after the start of sampling.
        """
        self._setup_capturing()

        for thread in self._sampling_threads:
            thread.start()

    def _setup_capturing(self):
        for device in self._devs:
            thread = Thread(target=self._read_dev_samples, args=(device,))
            self._sampling_threads.append(thread)

    def _read_dev_samples(self, device: str):
        self._raw_samples[device] = []

        for _ in range(0, self._duration + 1):  # +1 because first sample is "empty"
            with open(f"/proc/net/pktgen/{device}", "r") as file:
                self._raw_samples[device].append((time.time(), file.read()))
                # TODO: ^^^ when upgrading to python interpreter without GIL check thread safety
                # NOTE: samples are saved at it's end => the timestamp represents ending time, not the start
            time.sleep(1)

    @property
    def device_samples(self) -> dict[str, list[dict[str, Union[float, int, dict]]]]:
        for thread in self._sampling_threads:
            thread.join(timeout=2)

        samples = {}
        for device in self._devs:
            samples[device] = []
            packets_sofar = 0
            start_timestamp = self._raw_samples[device][0][0]  # first "empty" sample
            # NOTE: sample's timestamp represent the end of sampling
            # so each sample actually starts at the timestamp of previous sample

            for timestamp, raw_sample in self._raw_samples[device][
                1:
            ]:  # ignore first empty sample
                params, current = self._split_output(raw_sample)
                current = self._parse_values(current)

                packets = int(current["sofar"]) - packets_sofar

                samples[device].append(
                    {
                        "timestamp": start_timestamp,
                        "duration": timestamp - start_timestamp,
                        "packets": packets,
                        "errors": int(current["errors"]),
                        "params": params,
                    }
                )
                packets_sofar += packets
                start_timestamp = timestamp

        return samples

    def _read_dev_outputs(self) -> Iterator[tuple[str, str]]:
        for device in self._devs:
            output = ""
            with open(f"/proc/net/pktgen/{device}", "r") as f:
                output = f.readlines()
            yield device, "\n".join(output)

    def _split_output(self, output: str) -> tuple:
        match = re.search(r"Params:(.+)Current:(.+)Result:\s(?:\w+)", output, re.DOTALL)
        if not match:
            raise TestModuleError(f"Could not parse pktgen devide output: {output}")

        return match.groups()

    def _parse_values(self, params) -> dict[str, str]:
        values = {}

        for key, value in re.findall(r"(\w+):?\s(\S+)", params, re.MULTILINE):
            values[key.lower()] = value

        return values


@dataclass
class PktgenDevice:
    """
    Class representing a single pktgen device. Each device is tied to
    a PktgenThread and so, a separate CPU.

    Running multiple PktgenDevices with the same src/dst IPs is almost
    the same as running iperf --parallel.

    Each device can generate packets for single flow only, so if you
    want to generate multiple flows in parallel, you need to create
    multiple pktgen devices (which is just tuple inf+cpu). There
    might be multiple pktgen devices generating packets for the same
    interface, but they need to be pinned to separate CPUs.
    """

    cpu: IntParam  # each CPU is 1 generator

    src_if: DeviceParam
    dst_mac: StrParam

    src_ip: IpParam
    dst_ip: IpParam

    src_port: IntParam = 9
    dst_port: IntParam = 9  #  WARN: port 9 is discard protocol!

    count: IntParam = 0  # 0 = no upper limit
    pkt_size: IntParam = 60  # 4 bytes are added for CRC by NIC
    frags: IntParam = 1
    burst: IntParam = 8

    duration: IntParam = 60

    ratep: IntParam = -1  # pps
    flags: ListParam = field(default_factory=lambda: ["NO_TIMESTAMP", "QUEUE_MAP_CPU"])
    vlan_id: IntParam = 0  # 0 is invalid vlan id, will be ignored

    export_controller: ListParam = field(default_factory=list)  # (IP, port) tuple
    # WARN: this will expose cotroller to the network

    ctl_proxy: Optional[Popen] = field(init=False, default=None)

    @staticmethod
    def name_template(inf: Device, cpu: int) -> str:
        return f"{inf.name}@{cpu}"

    @property
    def name(self):
        return PktgenDevice.name_template(self.src_if, self.cpu)

    def configure(self):
        for flag in self.flags:
            self._cmd(f"flag {flag}")

        self._cmd(f"count {self.count}")
        self._cmd(f"pkt_size {self.pkt_size}")

        self._cmd(f"dst_mac {self.dst_mac}")
        self._cmd(f"src_mac {self.src_if.hwaddr}")

        if isinstance(self.src_ip, Ip4Address):
            self._cmd(f"dst_min {self.dst_ip}")
            self._cmd(f"dst_max {self.dst_ip}")
            self._cmd(f"src_min {self.src_ip}")
            self._cmd(f"src_max {self.src_ip}")
        else:
            self._cmd(f"dst6 {self.dst_ip}")
            self._cmd(f"src6 {self.src_ip}")

        self._cmd(f"udp_src_min {self.src_port}")
        self._cmd(f"udp_src_max {self.src_port}")
        self._cmd(f"udp_dst_min {self.dst_port}")
        self._cmd(f"udp_dst_max {self.dst_port}")

        if self.vlan_id > 0:
            self._cmd(f"vlan_id {self.vlan_id}")

        if self.ratep > 0:
            self._cmd(f"ratep {self.ratep}")

        self._cmd(f"burst {self.burst}")

        if self.export_controller:
            self.start_controller()

    def start_controller(self):
        logging.debug(f"Starting controller proxy for {self.name}")
        ip, port = self.export_controller
        self.ctl_proxy = Popen(
            f"nc -l {ip} {port} > /proc/net/pktgen/{self.name}",
            shell=True,
        )
        logging.info(f"Controller proxy for {self.name} started at {ip}:{port}")

    def kill_controller(self):
        if self.ctl_proxy is not None:
            logging.debug(f"Killing controller proxy for {self.name}")
            self.ctl_proxy.kill()

    def _cmd(self, cmd: str):
        logging.debug(f"Writing {cmd} to {self.name}")
        with open(f"/proc/net/pktgen/{self.name}", "w") as f:
            f.write(f"{cmd}\n")


@dataclass
class PktgenThread:
    """
    Just a wrapper around pktgen thread. Each thread can have
    multiple PktgenDevices generating packets.
    """

    cpu: int
    devices: list[PktgenDevice] = field(init=False, default_factory=list)

    def add_device(self, device: PktgenDevice):
        logging.debug(f"Adding device {device.name} to cpu {self.cpu}")

        self._cmd(f"add_device {device.name}")
        self.devices.append(device)

    def remove_all_devices(self):
        logging.debug(f"Removing all devices from cpu{self.cpu}")

        self._cmd("rem_device_all")

        self.devices = []

    def _cmd(self, cmd: str):
        logging.debug(f"Writing {cmd} to cpu{self.cpu}")
        with open(f"/proc/net/pktgen/kpktgend_{self.cpu}", "w") as f:
            f.write(f"{cmd}\n")


class PktgenController(BaseTestModule):
    """
    Think of this as a iperf client process, however pktgen
    doesn't support multiple parallel processes. Therefore, single
    PktGenController per networking namespace is allowed.

    The config param represents a list of configs, each for individual
    PktgenDevice (dicts are just passed to PktgenDevice), each cpu/thread
    can be configured separately. This allows it to support running
    multiple streams in parallel.

    CPU pinning is handled by PktgenThread
    Device config is handled by PktgenDevice


    Args:
        config (list): List of dicts, each representing a PktgenDevice
            configuration. Each dict is passed directly to PktgenDevice.
            E.g.: [{"cpu": 0, "src_if": ..., "dst_mac": ..., ...}]
    """

    config = ListParam()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._threads: list[PktgenThread] = []

    def run(self):
        self._load_pktgen_module()
        if not self._check_cpu_pinning():
            raise TestModuleError("Each device needs to be pinned to separate CPU")

        self._cmd("reset")
        self._threads = self._setup_threads()

        devices = [dev.name for thread in self._threads for dev in thread.devices]

        output_parser = PktGenResultsSampler(devices, self.duration)
        output_parser.start_sampling()

        logging.debug("Starting generator")
        pktgen = Popen("echo 'start' > /proc/net/pktgen/pgctrl", shell=True)
        # ^^ echoing start to controller is blocking => needs to be separated

        try:
            time.sleep(self.duration)
        except KeyboardInterrupt:
            logging.info("Test interrupted, stopping")

        pktgen.kill()  # stops pktgen

        self._res_data = output_parser.device_samples

        self._teardown()
        return True

    def runtime_estimate(self):
        return self.duration + 5

    @property
    def duration(self):
        return max(thread["duration"] for thread in self.params.config)

    def _setup_threads(self) -> list[PktgenThread]:
        threads = []
        for device in self.params.config:
            thread = PktgenThread(device["cpu"])
            dev = PktgenDevice(**device)
            thread.add_device(dev)
            dev.configure()

            threads.append(thread)

        return threads

    def _teardown(self):
        for thread in self._threads:
            thread.remove_all_devices()

        self._cmd("reset")

    def _check_cpu_pinning(self):
        # check if each device is pinned to separate CPU
        return len(set(dev["cpu"] for dev in self.params.config)) == len(
            self.params.config
        )

    def _load_pktgen_module(self):
        try:
            check_output(["/usr/sbin/modprobe", "pktgen"])
        except CalledProcessError as e:
            logging.debug(f"Modprobe of pktgen failed {e.output}")

        if not kmod_loaded("pktgen"):
            raise TestModuleError("pktgen module is not loaded")

    def _cmd(self, cmd):
        with open("/proc/net/pktgen/pgctrl", "w") as f:
            f.write(cmd + "\n")

class NDRPktGenClient(BaseTestModule):
    generators = ListParam()  # list of tuples (IP, port)
    cutoff_step = IntParam(default=100)  # pps; binary search stops when reached
    initial_rate = IntParam(default=1_000_000)  # initial rate in pps

    ingress_nic = DeviceParam()  # nic used for receive
    egress_nic = DeviceParam()  # nic used for transmit

    drop_rate = FloatParam(default=0.0)
    wait_interval = FloatParam(default=5.0)  # seconds
    max_iterations = IntParam(default=15)
    pktgen_burst = IntParam(default=8)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.connections = []
        self._current_rate = 0

    def run(self):
        self.params.ingress_nic._if_manager.reconnect_netlink()
        self.params.egress_nic._if_manager.reconnect_netlink()
        self.connections = self._open_connections()

        self._current_rate = int(self.params.initial_rate / self.params.pktgen_burst)
        step_size = int(self.params.initial_rate / 2)

        prev_total, prev_dropped = self._read_stat()

        self._set_rate_all()

        prev_direction = None  # True = increase, False = decrease
        rates = []  # list of tuples (rate, drop_rate)
        updated = True

        try:
            for iteration in range(self.params.max_iterations):
                logging.info(f"Iteration {iteration+1}/{self.params.max_iterations}")

                # wait for changes to propagate
                time.sleep(self.params.wait_interval)

                curr_total, curr_dropped = self._read_stat()

                if "mlx5" not in self.params.ingress_nic.driver:
                    packets = curr_total - prev_total
                    dropped = curr_dropped - prev_dropped
                else:
                    packets = curr_total
                    dropped = curr_dropped - prev_dropped

                drop_rate = round((dropped / packets) * 100 if packets > 0 and dropped / packets > 0 else 0, 2)
                logging.debug(f"Total packets: {packets}, Dropped packets: {dropped}, Drop rate: {drop_rate}")

                if updated:
                    prev_total = curr_total
                    prev_dropped = curr_dropped
                    logging.info("Rate updated, waiting for changes to propagate.")
                    updated = False
                    continue

                logging.info(
                    f"Rate: {self._current_rate * self.params.pktgen_burst} pps, Drop rate: {drop_rate}, Step: {step_size}"
                )
                rates.append((self._current_rate * self.params.pktgen_burst, drop_rate))

                if drop_rate > self.params.drop_rate:
                    # too many drops, decrease rate
                    current_direction = False
                    new_rate = self._current_rate - step_size
                else:
                    # drops within range, increase rate
                    current_direction = True
                    new_rate = self._current_rate + step_size

                # drop rate direction changed, reduce step size
                if prev_direction is not None and prev_direction != current_direction:
                    step_size = int(step_size / 2)

                updated = (self._current_rate != new_rate)

                self._current_rate = max(new_rate, self.params.cutoff_step)
                self._set_rate_all()

                prev_total = curr_total
                prev_dropped = curr_dropped
                prev_direction = current_direction

                if step_size < self.params.cutoff_step:
                    logging.info(
                        f"Step size ({step_size}) below minimum threshold ({self.params.cutoff_step}). Stopping."
                    )
                    break
        except Exception as e:
            logging.info(f"Error during test: {e}")
            self._res_data = (0, 100)
            return False
        finally:
            for sock, _, _ in self.connections:
                try:
                    sock.close()
                except:
                    pass

        self._res_data = max(
            filter(
                lambda x: x[1] <= self.params.drop_rate, self._deduplicate_rates(rates)
            ),
            key=lambda x: x[0],
        )

        return True

    def _deduplicate_rates(self, rates):
        """
        Function merges duplicate rates and keeps only the one with
        the highest drop rate (worst case).
        """
        deduplicated = []
        for rate in rates:
            same_rate = list(filter(lambda x: x[0] == rate[0], deduplicated))
            if not same_rate:
                deduplicated.append(rate)
            else:
                same_rate = same_rate[0]
                if rate[1] > same_rate[1]:
                    deduplicated.remove(same_rate)
                    deduplicated.append(rate)

        return deduplicated

    def _read_stat(self):
        """Read a statistic from the NIC."""
        self.params.ingress_nic._if_manager.rescan_devices()
        self.params.egress_nic._if_manager.rescan_devices()
        # ^ needs to rescan devices to update netlink msg
        # where stats are fetched from
        ingress = self.params.ingress_nic.link_stats64
        egress = self.params.egress_nic.link_stats64

        dropped_ingress = ingress["rx_dropped"] + ingress["rx_missed_errors"]
        if "mlx5" not in self.params.ingress_nic.driver:
            # mlx5 doesn't increase ANY counter when running xdp program
            dropped_internally = ingress["rx_packets"] - egress["tx_packets"] + dropped_ingress
            # e.g. when running xdp program that drops packet,
            # drop counter is not increased
            # TODO: kernel bug??
            return ingress["rx_packets"], dropped_internally
        else:
        # if "mlx5" in self.params.ingress_nic.driver:
            # mlx5 doesn't increase ANY counter when running xdp program
            return max(self._current_rate * self.params.pktgen_burst, 1), dropped_ingress


    def _set_rate_all(self):
        """Send rate update command to all generators."""
        for sock, host, port in self.connections:
            try:
                cmd = f"ratep {int(self._current_rate)}\n"
                sock.send(cmd.encode())
            except socket.error as e:
                logging.error(f"Failed to send rate update to {host}:{port}: {e}")

    def _open_connections(self):
        conns = []
        for host, port in self.params.generators:
            sock = self._open_connection(host, port)
            conns.append((sock, host, port))
            logging.info(f"Connected to generator at {host}:{port}")

        return conns

    def _open_connection(self, host, port):
        try:
            sock = socket.socket(
                socket.AF_INET if isinstance(host, IPv4Address) else socket.AF_INET6,
                socket.SOCK_STREAM,
            )  # TODO: use lnst_ipaddr_class.family
            sock.connect((str(host), port))
            return sock
        except socket.error as e:
            raise TestModuleError(
                f"Failed to connect to generator at {host}:{port}: {e}"
            )

    def runtime_estimate(self):
        return ceil(self.params.max_iterations * self.params.wait_interval)
