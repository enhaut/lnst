import re
import time
import random
import signal
import logging
from subprocess import Popen, PIPE
from threading import Thread

from lnst.Tests.BaseTestModule import BaseTestModule, TestModuleError
from lnst.Common.Parameters import (
    StrParam,
    IntParam,
    DeviceParam,
    ListParam,
)


class XDPBenchRedirectCpuOutputParser:
    def __init__(self, process: Popen):
        self._process = process
        self._raw_samples = []
        self._capturing_start = 0

    def start_sampling(self):
        thread = Thread(target=self._capture_output)
        thread.start()
        self._capturing_start = time.time()

    def _capture_output(self):
        try:
            for sample in iter(self._process.stdout.readline, ""):
                self._raw_samples.append((time.time(), sample.decode()))
                # logging.debug(sample.decode().rstrip())
        except ValueError:
            pass  # .readline raises exception on killing xdp-bench subprocess

    def parse_output(self) -> list[dict]:
        _, stderr = self._process.communicate()

        logging.debug("Stderr of xdp-bench redirect-cpu:")
        logging.debug(str(stderr))

        # logging.debug(
        #     "Stdout of xdp-bench redirect-cpu:\n%s",
        #     "".join(line for _, line in self._raw_samples),
        # )

        results = []
        blocks = self._split_into_blocks()

        for block_timestamp, block_lines in blocks:
            try:
                received, forwarded_per_cpu = self._parse_block(block_lines)
            except ValueError:
                logging.error(f"Could not parse block: {block_lines}")
                continue

            if results:
                duration = block_timestamp - (
                    results[-1]["timestamp"] + results[-1]["duration"]
                )
            else:
                duration = block_timestamp - self._capturing_start

            results.append(
                {
                    "received": received,
                    "forwarded_per_cpu": forwarded_per_cpu,
                    "duration": duration,
                    "timestamp": block_timestamp - duration,
                }
            )

        if not results:
            raise TestModuleError("Could not get xdp-bench redirect-cpu output")

        return results

    def _split_into_blocks(self) -> list[tuple[float, list[str]]]:
        """
        Split captured output into interval blocks.
        Each block starts with an interface line matching `^\S+->`.
        """
        blocks = []
        current_block = []
        current_timestamp = self._capturing_start

        for timestamp, line in self._raw_samples:
            if re.match(r"^\S+->", line):
                if current_block:
                    blocks.append((current_timestamp, current_block))
                current_block = [line]
                current_timestamp = timestamp
            else:
                current_block.append(line)

        if current_block:
            blocks.append((current_timestamp, current_block))

        return blocks

    def _parse_block(self, lines: list[str]) -> tuple[int, dict[int, int]]:
        """
        Parse a single interval block for received count and per-CPU
        kthread forwarded counts.

        Returns (received, forwarded_per_cpu) where forwarded_per_cpu is
        a dict mapping cpu_id -> pkt/s.

        Example kthread section::

            kthread total         4,334,231 pkt/s ...
              cpu:4               2,162,754 pkt/s ...
              cpu:6               2,171,476 pkt/s ...

        """
        received = None
        forwarded_per_cpu = {}
        in_kthread_section = False

        for line in lines:
            if received is None:
                match = re.search(r"receive\s+total\s+([\d,]+)\s+pkt/s", line)
                if match:
                    received = int(match.group(1).replace(",", ""))

            if re.search(r"kthread\s+total\s+[\d,]+\s+pkt/s", line):
                in_kthread_section = True
                continue

            if in_kthread_section:
                cpu_match = re.match(r"\s+cpu:(\d+)\s+([\d,]+)\s+pkt/s", line)
                if cpu_match:
                    cpu_id = int(cpu_match.group(1))
                    pkt_s = int(cpu_match.group(2).replace(",", ""))
                    forwarded_per_cpu[cpu_id] = pkt_s
                else:
                    in_kthread_section = False

        if received is None or not forwarded_per_cpu:
            raise ValueError("Could not parse received/forwarded from block")

        return received, forwarded_per_cpu


class XDPBenchRedirectCpu(BaseTestModule):
    """
    xdp-bench redirect-cpu tool abstraction.

    Runs `xdp-bench redirect-cpu` with the specified interface and CPU list.
    Each CPU becomes a separate `-c` flag. The output is multi-line per
    interval and is parsed by XDPBenchRedirectCpuOutputParser.

    xdp-bench is expected to be included in PATH env variable.
    """

    interface = DeviceParam(mandatory=True)
    cpus = ListParam(mandatory=True)
    program = StrParam(default="l4-hash")
    remote_action = StrParam(default="pass")
    interval = IntParam(default=1)
    duration = IntParam(default=60)
    queue_size = IntParam(default=512)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._res_data = []

    def run(self):
        command = self._prepare_command()
        logging.debug(f"Starting xdp-bench redirect-cpu: `{command}`")

        bench = Popen(command, stdout=PIPE)
        output_parser = XDPBenchRedirectCpuOutputParser(bench)
        output_parser.start_sampling()
        time.sleep(self.params.duration)

        bench.send_signal(signal.SIGINT)  # needs to be shutdown gracefully

        self._res_data = output_parser.parse_output()

        return True

    def _prepare_command(self):
        args = ["xdp-bench", "redirect-cpu", self.params.interface.name]

        for cpu in self.params.cpus:
            args.extend(["-c", str(cpu)])

        args.extend(["-p", "l4-hash"])
        args.extend(["-r", "pass"])
        args.extend(["-i", str(self.params.interval)])
        args.extend(["-q", str(self.params.queue_size)])
        args.append("-e")  # extended stats

        return args

    def runtime_estimate(self):
        return self.params.duration + 2
