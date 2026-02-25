"""
Module with RSSRecipe class that implements ENRT recipe
for testing RSS distribution via XDP redirect-cpu.

Copyright 2025 Red Hat, Inc.
Licensed under the GNU General Public License, version 2 as
published by the Free Software Foundation; see COPYING for details.
"""

__author__ = """
sdobron@redhat.com (Samuel Dobron)
"""

import re
import logging

from lnst.Recipes.ENRT.ConfigMixins.MultiDevInterruptHWConfigMixin import (
    MultiDevInterruptHWConfigMixin,
)
from lnst.Recipes.ENRT.MeasurementGenerators.XDPRedirectCPUMeasurementGenerator import (
    XDPRedirectCPUMeasurementGenerator,
)
from lnst.Recipes.ENRT.SimpleNetworkRecipe import SimpleNetworkRecipe
from lnst.Recipes.ENRT.BaseEnrtRecipe import EnrtConfiguration
from lnst.RecipeCommon.Ping.PingEndpoints import PingEndpoints


class RSSRecipe(
    MultiDevInterruptHWConfigMixin,
    XDPRedirectCPUMeasurementGenerator,
    SimpleNetworkRecipe,
):
    """
    This recipe implements ENRT recipe for testing RSS (Receive Side Scaling)
    distribution via XDP redirect-cpu. It uses 2 hosts: host1 generates
    traffic with pktgen, host2 receives and processes it via xdp-bench
    redirect-cpu.

    RSS is effectively disabled on host2 by zeroing the hash key and
    disabling rxhash. All IRQs on host2 are pinned to a single CPU
    (via multi_dev_interrupt_config). xdp-bench redirect-cpu then
    redistributes packets across the configured CPUs.

    .. code-block:: none

        +--------+              +--------+
        | host1  |              | host2  |
        |  eth0 -+-- switch  ---+- eth0  |
        |pktgen  |              | xdp-bench redirect-cpu |
        +--------+              +--------+

    IRQ pinning should be configured via ``multi_dev_interrupt_config``
    parameter, pinning host2.eth0 IRQs to a single CPU (first in
    ``perf_tool_cpu``).
    """

    def test_wide_configuration(self, config: EnrtConfiguration) -> EnrtConfiguration:
        config = super().test_wide_configuration(config)

        host2 = self.matched.host2
        dev = host2.eth0

        # Install python3-bcc and symlink for TC drop monitor
        host2.run("dnf install -y python3-bcc", timeout=300)
        host2.run(
            "ln -sf /usr/lib/python3.9/site-packages/bcc"
            " /tmp/virtualenvs/rhextensions-lnst-Xo1BSm3a-py3.9/lib/python3.9/site-packages/bcc"
        )

        # Set combined rx/tx queues to 1 on host2
        # self._set_queue_count(host2, dev, config)

        # Set NIC ring buffer size
        self._set_ring_size(host2, dev, config)

        # Zero RSS hash key on host2
        self._zero_rss_hash_key(host2, dev, config)

        return config

    def test_wide_deconfiguration(self, config):
        host2 = self.matched.host2
        dev = host2.eth0

        # Restore original RSS hash key
        self._restore_rss_hash_key(host2, dev, config)

        # Restore rxhash
        host2.run(f"ethtool -K {dev.name} rxhash on")

        # Restore NIC ring buffer size
        self._restore_ring_size(host2, dev, config)

        # Restore original queue count
        self._restore_queue_count(host2, dev, config)

        super().test_wide_deconfiguration(config)

        return config

    def _set_ring_size(self, host, dev, config):
        """Save current RX ring size and set to driver maximum."""
        result = host.run(f"ethtool -g {dev.name}")

        max_match = re.search(
            r"Pre-set maximums:.*?RX:\s+(\d+)", result.stdout, re.DOTALL
        )
        cur_match = re.search(
            r"Current hardware settings:.*?RX:\s+(\d+)", result.stdout, re.DOTALL
        )
        config.rss_original_ring_size = int(cur_match.group(1)) if cur_match else None

        max_rx = int(max_match.group(1)) if max_match else 8192
        host.run(f"ethtool -G {dev.name} rx {max_rx}")
        logging.info(f"Set RX ring size to {max_rx} (max) on {dev.name}")

    def _restore_ring_size(self, host, dev, config):
        """Restore original RX ring size."""
        original = getattr(config, "rss_original_ring_size", None)
        if original:
            host.run(f"ethtool -G {dev.name} rx {original}")
            logging.info(f"Restored RX ring size to {original} on {dev.name}")

    # def _set_queue_count(self, host, dev, config):
    #     """Save current combined queue count and set to 1."""
    #     return
    #     result = host.run(f"ethtool -l {dev.name}")
    #     match = re.search(
    #         r"Current hardware settings:.*?Combined:\s+(\d+)", result.stdout, re.DOTALL
    #     )
    #     if match:
    #         config.rss_original_queue_count = int(match.group(1))
    #     else:
    #         config.rss_original_queue_count = None
    #
    #     host.run(f"ethtool -L {dev.name} combined 1")
    #     logging.info(f"Set combined queue count to 1 on {dev.name}")
    #
    # def _restore_queue_count(self, host, dev, config):
    #     """Restore original combined queue count."""
    #     return
    #     original = getattr(config, "rss_original_queue_count", None)
    #     if original:
    #         host.run(f"ethtool -L {dev.name} combined {original}")
    #         logging.info(f"Restored combined queue count to {original} on {dev.name}")

    def _zero_rss_hash_key(self, host, dev, config):
        """
        Query current RSS hash key length and set all zeros.
        Saves original key for restoration.
        """
        result = host.run(f"ethtool -x {dev.name}")
        output = result.stdout

        # Parse hash key from ethtool -x output
        key_match = re.search(r"RSS hash key:\s*\n((?:[0-9a-fA-F]{2}:?)+)", output)
        if key_match:
            original_key = key_match.group(1).strip()
            key_bytes = original_key.split(":")
            key_length = len(key_bytes)

            config.rss_original_hash_key = original_key

            zero_key = ":".join(["00"] * key_length)
            host.run(f"ethtool -X {dev.name} hkey {zero_key}")

            logging.info(
                f"Zeroed RSS hash key on {dev.name} "
                f"(original length: {key_length} bytes)"
            )
        else:
            logging.warning(f"Could not parse RSS hash key from ethtool -x output")
            config.rss_original_hash_key = None

    def _restore_rss_hash_key(self, host, dev, config):
        """Restore original RSS hash key."""
        original_key = getattr(config, "rss_original_hash_key", None)
        if original_key:
            host.run(f"ethtool -X {dev.name} hkey {original_key}")
            logging.info(f"Restored RSS hash key on {dev.name}")

    def _cpu_measurement_kwargs(self):
        cpu_names = ["cpu0", "cpu"] + [f"cpu{c}" for c in self.params.perf_tool_cpu]
        return {
            "log_cpu_filter": cpu_names,
            "log_host_filter": {"host2"},
            "results_dir": f"/root/.lnst/results/{self.__class__.__name__}",
        }

    def generate_ping_endpoints(self, config):
        return [
            PingEndpoints(self.matched.host1.eth0, self.matched.host2.eth0),
        ]

    @property
    def offload_nics(self):
        return [self.matched.host1.eth0, self.matched.host2.eth0]
