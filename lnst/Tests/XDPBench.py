import re
import time
import signal
import logging
from subprocess import Popen, PIPE
from lnst.Devices.Device import Device

from lnst.Tests.BaseTestModule import BaseTestModule, TestModuleError
from lnst.Common.Parameters import (
    ChoiceParam,
    StrParam,
    IntParam,
    DeviceParam,
)


class XDPBenchOutputParser:
    def __init__(self, process: Popen, output: list) -> None:
        self._process = process
        self._out = output

    def parse_output(self):
        stdout, stderr = self._process.communicate()

        logging.debug("Stderr of xdp-bench:")
        logging.debug(str(stderr))

        self._parse_raw_results(stdout)

        if not self._out:
            raise TestModuleError(f"Could not parse xdp-bench output: {stdout}")

    def _parse_raw_results(self, raw_results: bytes):
        decoded = raw_results.decode()
        intervals = decoded.splitlines()

        for line in intervals:
            self._parse_line(line)

    def _parse_line(self, line: str):
        match = re.search(r"Summary\s+([\d,]+)\srx/s\s+([\d,]+)\serr/s?", line)

        if not match:  # skip summary line at the end + corrupted lines
            logging.error(f"Could not parse xdp-bench output: {line}")
            return

        rx = match.group(1).replace(",", "")
        err = match.group(2).replace(",", "")
        # ^^ remove thousands separators

        self._out.append({"rx": int(rx), "err": int(err)})


class XDPBench(BaseTestModule):
    """
    xdp-bench tool abstraction. [1]

    This tool does NOT check params validity.

    xdp-bench is expected to be included in PATH env variable.

    [1] https://github.com/xdp-project/xdp-tools/
    """

    command = ChoiceParam(
        type=StrParam,
        choices=(
            "pass",
            "drop",
            "tx",
            "redirect",
            "redirect-cpu",
            "redirect-map",
            "redirect-multi",
        ),
        mandatory=True,
    )
    interface = DeviceParam(mandatory=True)
    interface2 = DeviceParam()  # used for redirect modes

    interval = IntParam(default=1)

    redirect_device = DeviceParam()
    xdp_mode = ChoiceParam(type=StrParam, choices=("native", "skb"), default="native")
    load_mode = ChoiceParam(type=StrParam, choices=("dpa", "load-bytes"))
    packet_operation = ChoiceParam(
        type=StrParam, choices=("no-touch", "read-data", "parse-ip", "swap-macs")
    )
    qsize = IntParam()
    remote_action = ChoiceParam(
        type=StrParam, choices=("disabled", "drop", "pass", "redirect")
    )

    # NOTE: order and names of params above matters. xdp-bench accepts params in that way
    duration = IntParam(default=60, mandatory=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._res_data = []

    def run(self):
        logging.debug("Starting xdp-bench")
        command = self._prepare_command()

        bench = Popen(command, stdout=PIPE)
        output_parser = XDPBenchOutputParser(bench, self._res_data)

        time.sleep(self.params.duration)

        bench.send_signal(signal.SIGINT)  # needs to be shutdown gracefully

        output_parser.parse_output()

        return True

    def _prepare_command(self):
        return ["xdp-bench"] + self._prepare_arguments()

    def _prepare_arguments(self):
        args = []
        for param, value in self.params:
            if param == "duration":
                continue  # not a xdp-bench argument

            if param not in ("interface", "interface2", "command"):
                # ^^^ those 3 arguments are passed without arg name
                args.append(f"--{param.replace('_', '-')}")

            if isinstance(value, Device):
                value = value.name  # get if name

            args.append(str(value))

        return args
