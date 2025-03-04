import re
import time
import socket
import logging
from math import ceil, log2
from subprocess import Popen, check_output, CalledProcessError
from threading import Thread
from typing import Iterator, Union

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
    BoolParam,
)


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


class PktGen(BaseTestModule):
    """
    In the scope of this module, the physical interface is refered as `interface`.
    Pktgen device (interface@anything) is refered as device.

    Inspired by https://github.com/torvalds/linux/blob/master/samples/pktgen/pktgen_sample03_burst_single_flow.sh
    """

    cpus = ListParam(type=IntParam())  # each CPU is 1 generator

    src_if = DeviceParam()
    dst_mac = StrParam()

    src_ip = IpParam()
    dst_ip = IpParam()

    src_port = IntParam(default=9)
    dst_port = IntParam(default=9)  #  WARN: port 9 is discard protocol!

    count = IntParam(default=0)  # 0 = no upper limit
    pkt_size = IntParam(default=60)  # 4 bytes are added for CRC by NIC
    frags = IntParam(default=1)
    burst = IntParam(default=8)

    duration = IntParam(default=60)

    ratep = IntParam(default=-1)  # pps

    export_controller = BoolParam(default=False)  # WARN: this will expose controller to the network

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._devices = []

        self._res_data = {}
        self._output_parser = None

    def run(self):
        self._load_pktgen_module()
        self._pg_ctrl("reset")
        self._configure_generator()

        if self.params.export_controller:
            ctl_proxy = Popen(
                f"nc -l 0.0.0.0 1234 > /proc/net/pktgen/{self.params.src_if.name}@0",
                shell=True,
            )

        output_parser = PktGenResultsSampler(self._devices, self.params.duration)
        output_parser.start_sampling()

        logging.debug("Starting generator")
        pktgen = Popen("echo 'start' > /proc/net/pktgen/pgctrl", shell=True)
        # ^^ echoing start to controller is blocking => needs to be separated

        time.sleep(self.params.duration)

        pktgen.kill()  # stops pktgen
        if self.params.export_controller:
            ctl_proxy.kill()  # stops controller proxy

        self._res_data = output_parser.device_samples

        self._deconfigure_generator()
        return True

    def _load_pktgen_module(self):
        try:
            check_output(["/usr/sbin/modprobe", "pktgen"])
        except CalledProcessError as e:
            logging.debug(f"Modprobe of pktgen failed {e.output}")

        if not kmod_loaded("pktgen"):
            raise TestModuleError("pktgen module is not loaded")

    def _configure_generator(self):
        logging.debug("Configuring generator")

        for cpu in self.params.cpus:
            dev = f"{self.params.src_if.name}@{cpu}"
            logging.debug(f"Adding interface {self.params.src_if.name} to cpu {cpu}")

            self._pg_thread(cpu, f"add_device {dev}")

            self._pg_set(cpu, "flag QUEUE_MAP_CPU")
            self._pg_set(cpu, f"count {self.params.count}")
            self._pg_set(cpu, f"pkt_size {self.params.pkt_size}")
            self._pg_set(cpu, "flag NO_TIMESTAMP")

            self._pg_set(cpu, f"dst_mac {self.params.dst_mac}")
            self._pg_set(cpu, f"src_mac {self.params.src_if.hwaddr}")

            if isinstance(self.params.src_ip, Ip4Address):
                self._pg_set(cpu, f"dst_min {self.params.dst_ip}")
                self._pg_set(cpu, f"dst_max {self.params.dst_ip}")
                self._pg_set(cpu, f"src_min {self.params.src_ip}")
                self._pg_set(cpu, f"src_max {self.params.src_ip}")
            else:
                self._pg_set(cpu, f"dst6 {self.params.dst_ip}")
                self._pg_set(cpu, f"src6 {self.params.src_ip}")

            self._pg_set(cpu, f"udp_src_min {self.params.src_port}")
            self._pg_set(cpu, f"udp_src_max {self.params.src_port}")
            self._pg_set(cpu, f"udp_dst_min {self.params.dst_port}")
            self._pg_set(cpu, f"udp_dst_max {self.params.dst_port}")

            if self.params.ratep > 0:
                self._pg_set(cpu, f"ratep {self.params.ratep}")

            self._pg_set(cpu, f"burst {self.params.burst}")
            self._devices.append(dev)

    def _deconfigure_generator(self):
        logging.debug("Deconfiguring generator")
        for cpu in self.params.cpus:
            self._pg_thread(cpu, "rem_device_all")

        self._pg_ctrl("reset")

    def _pg_ctrl(self, cmd: str):
        self._write_command("/proc/net/pktgen/pgctrl", cmd)

    def _pg_thread(self, thread: int, cmd: str):
        self._write_command(f"/proc/net/pktgen/kpktgend_{thread}", cmd)

    def _pg_set(self, thread: int, cmd: str):
        self._write_command(f"/proc/net/pktgen/{self.params.src_if.name}@{thread}", cmd)

    def _write_command(self, file: str, cmd: str):
        logging.debug(f"Writing {cmd} to {file}")
        with open(file, "w") as f:
            f.write(f"{cmd}\n")

    def runtime_estimate(self):
        return self.params.duration + 5


class NDRPktGenClient(BaseTestModule):
    MIN_STEP = 50

    generator_ctl = (
        StrParam()
    )  # IP:PORT to generator control process. e.g. 1.1.1.1:1234
    initial_rate = IntParam(default=1_000_000)  # initial rate in pps
    min_step = IntParam(default=10)  # minimum step size in pps
    nic = DeviceParam()  # nic used for receive
    drop_rate = FloatParam(default=0.0)  # acceptable drop rate in percentage
    wait_interval = FloatParam(default=5.0)

    def run(self):
        # Parse generator control address
        host, port = self.params.generator_ctl.split(":")
        port = int(port)

        # Initialize TCP connection to generator
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.sock.connect((host, port))
        except socket.error as e:
            logging.error(f"Failed to connect to generator: {e}")
            return False

        # Initialize rate variables
        current_rate = self.params.initial_rate
        step_size = current_rate / 2

        # Initialize packet counters
        prev_total = self._read_stat("rx_packets")
        prev_dropped = self._read_stat("rx_dropped")

        # Set initial rate
        self._set_rate(current_rate)

        # Previous direction (True = increase, False = decrease)
        prev_direction = None

        iters = self.max_iterations
        logging.info(f"Maximum iterations based on configration {iters}")
        updated = True
        rates = []

        try:
            while iters:
                time.sleep(self.params.wait_interval)

                curr_total = self._read_stat("rx_packets")
                curr_dropped = self._read_stat("rx_dropped")

                total_packets = curr_total - prev_total
                dropped = curr_dropped - prev_dropped

                drop_rate = dropped / total_packets if total_packets > 0 else 0
                rates.append((current_rate, drop_rate))

                if updated:
                    # If rate was updated, reset counters
                    updated = False
                    prev_total = curr_total
                    prev_dropped = curr_dropped
                    logging.info(
                        "Rate updated, skipping check to let numbers stabilize"
                    )
                    continue

                logging.info(
                    f"Rate: {int(current_rate)} pps, Drop rate: {drop_rate:.2f}, Step: {int(step_size)}"
                )

                if drop_rate > self.params.drop_rate:
                    # Too many drops, decrease rate
                    current_direction = False
                    new_rate = current_rate - step_size
                else:
                    # Acceptable drops, increase rate
                    current_direction = True
                    new_rate = current_rate + step_size

                # If direction changed, reduce step size
                if prev_direction is not None and prev_direction != current_direction:
                    step_size /= 2

                prev_direction = current_direction

                current_rate = max(new_rate, self.MIN_STEP)
                if current_rate != new_rate:
                    updated = True

                if step_size <= self.MIN_STEP:
                    logging.info("Minimum rate reached")
                    break

                self._set_rate(current_rate)

                prev_total = curr_total
                prev_dropped = curr_dropped

                iters -= 1
        except Exception as e:
            logging.error(f"Error during test: {e}")
        finally:
            # Close the connection
            try:
                self.sock.close()
            except:
                pass

        acceptable_rates = sorted(
            filter(
                lambda x: x[1] <= self.params.drop_rate, self._deduplicate_rates(rates)
            )
        )
        best_rate = acceptable_rates[-1]
        logging.info(f"Acceptable rates: {acceptable_rates}")
        logging.info(
            f"Best rate measured {best_rate[0]} pps with drop rate {best_rate[1]:.2f}"
        )
        self._res_data = best_rate

        return True

    def _deduplicate_rates(self, rates):
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

    def _read_stat(self, stat_name) -> int:
        """Read a statistic from the NIC."""
        path = f"/sys/class/net/{self.params.nic.name}/statistics/{stat_name}"
        try:
            with open(path, "r") as f:
                return int(f.read().strip())
        except (OSError, ValueError) as e:
            logging.error(f"Error reading {stat_name}: {e}")
            return -1

    def _set_rate(self, rate):
        """Send rate update command to the generator."""
        try:
            cmd = f"ratep {int(rate)}\n"
            self.sock.send(cmd.encode())
        except socket.error as e:
            logging.error(f"Failed to send rate update: {e}")
            # Attempt to reconnect
            try:
                host, port = self.params.generator_ctl.split(":")
                port = int(port)
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.connect((host, port))
                # Try sending again
                self.sock.send(cmd.encode())
            except Exception as reconnect_error:
                logging.error(f"Failed to reconnect to generator: {reconnect_error}")

    @property
    def max_iterations(self):
        return ceil(log2(self.params.initial_rate / self.MIN_STEP))

    def runtime_estimate(self):
        return ceil(self.max_iterations * self.params.wait_interval)
