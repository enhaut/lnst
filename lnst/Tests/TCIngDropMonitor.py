"""
Module implementing TCIngDropMonitor test module — a TC ingress BPF
drop counter that counts packets per-CPU per-second.

When xdp-bench uses ``-r pass``, packets reach the network stack on
remote CPUs.  A TC ingress BPF program drops and counts them per-CPU.

Copyright 2025 Red Hat, Inc.
Licensed under the GNU General Public License, version 2 as
published by the Free Software Foundation; see COPYING for details.
"""

__author__ = """
sdobron@redhat.com (Samuel Dobron)
"""

import time
import signal
import logging

from lnst.Tests.BaseTestModule import BaseTestModule, InterruptException
from lnst.Common.Parameters import DeviceParam, FloatParam, ListParam

BPF_PROGRAM = r"""
#define TC_ACT_SHOT 2

BPF_PERCPU_ARRAY(drop_cnt, u64, 1);

int tc_drop(struct __sk_buff *skb) {
    u32 key = 0;
    u64 *val = drop_cnt.lookup(&key);
    if (val)
        (*val) += 1;
    return TC_ACT_SHOT;
}
"""


def sigint_handler(signum, frame):
    raise InterruptException()


class TCIngDropMonitor(BaseTestModule):
    """
    TC ingress BPF drop counter.

    Attaches a BPF program to TC ingress that drops every packet and
    increments a per-CPU counter.  The module periodically samples the
    counters, computes deltas for the tracked CPUs, and returns the
    results on SIGINT.

    Requires ``python3-bcc`` and ``kernel-devel`` on the agent machine.
    """

    device = DeviceParam(mandatory=True)
    interval = FloatParam(default=1.0)
    cpus = ListParam(mandatory=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._res_data = []

    def run(self):
        from bcc import BPF
        from pyroute2 import IPRoute

        dev = self.params.device
        idx = dev.ifindex
        cpus = [int(c) for c in self.params.cpus]
        interval = self.params.interval

        logging.info(
            "TCIngDropMonitor: attaching to %s (ifindex %d), cpus=%s",
            dev.name,
            idx,
            cpus,
        )

        b = BPF(text=BPF_PROGRAM)
        fn = b.load_func("tc_drop", BPF.SCHED_CLS)

        ipr = IPRoute()
        try:
            ipr.tc("add", "clsact", idx)
        except Exception:
            logging.warning("clsact qdisc may already exist, continuing")

        ipr.tc(
            "add-filter",
            "bpf",
            idx,
            ":1",
            fd=fn.fd,
            name=fn.name,
            parent="ffff:fff2",
            direct_action=True,
        )

        drop_cnt = b["drop_cnt"]

        # Read initial per-CPU values
        prev_values = {}
        for cpu in cpus:
            prev_values[cpu] = drop_cnt[drop_cnt.Key(0)][cpu]

        results = []
        old_handler = None
        prev_time = time.time()

        try:
            old_handler = signal.signal(signal.SIGINT, sigint_handler)
            while True:
                time.sleep(interval)
                now = time.time()
                duration = now - prev_time

                drops_per_cpu = {}
                for cpu in cpus:
                    cur = drop_cnt[drop_cnt.Key(0)][cpu]
                    drops_per_cpu[cpu] = cur - prev_values[cpu]
                    prev_values[cpu] = cur

                results.append(
                    {
                        "timestamp": prev_time,
                        "duration": duration,
                        "drops_per_cpu": drops_per_cpu,
                    }
                )

                prev_time = now
                logging.debug(
                    "TCIngDropMonitor: sampled drops_per_cpu=%s", drops_per_cpu
                )
        except InterruptException:
            pass
        finally:
            if old_handler is not None:
                signal.signal(signal.SIGINT, old_handler)

            logging.info("TCIngDropMonitor: removing clsact qdisc from ifindex %d", idx)
            try:
                ipr.tc("del", "clsact", idx)
            except Exception:
                logging.warning("Failed to remove clsact qdisc")
            ipr.close()

        self._res_data = results

        return True
