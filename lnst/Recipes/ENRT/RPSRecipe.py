"""
Module with RPSRecipe class that implements ENRT recipe
for testing RPS (Receive Packet Steering) distribution.

Copyright 2025 Red Hat, Inc.
Licensed under the GNU General Public License, version 2 as
published by the Free Software Foundation; see COPYING for details.
"""

__author__ = """
sdobron@redhat.com (Samuel Dobron)
"""

import re
import logging

from lnst.Recipes.ENRT.MeasurementGenerators.RPSMeasurementGenerator import (
    RPSMeasurementGenerator,
)
from lnst.Recipes.ENRT.RSSRecipe import RSSRecipe
from lnst.Recipes.ENRT.BaseEnrtRecipe import EnrtConfiguration


class RPSRecipe(
    RPSMeasurementGenerator,
    RSSRecipe,
):
    """
    This recipe implements ENRT recipe for testing RPS (Receive Packet
    Steering) distribution. It uses 2 hosts: host1 generates traffic
    with pktgen, host2 steers packets to configured CPUs via RPS.

    Inherits from RSSRecipe for shared NIC setup (ring size, hash key,
    IRQ pinning). Adds RPS-specific configuration: queue count reduction,
    RPS CPU mask, and netdev_max_backlog tuning.

    .. code-block:: none

        +--------+              +--------+
        | host1  |              | host2  |
        |  eth0 -+-- switch  ---+- eth0  |
        |pktgen  |              | RPS + TC drop counter |
        +--------+              +--------+

    IRQ pinning should be configured via ``multi_dev_interrupt_config``
    parameter, pinning host2.eth0 IRQs to a single CPU (first in
    ``perf_tool_cpu``).
    """

    def test_wide_configuration(self, config: EnrtConfiguration) -> EnrtConfiguration:
        config = super().test_wide_configuration(config)

        host2 = self.matched.host2
        dev = host2.eth0

        # Configure RPS
        self._configure_rps(host2, dev, config)

        # Set netdev_max_backlog
        self._set_backlog_size(host2, config)

        return config

    def test_wide_deconfiguration(self, config):
        host2 = self.matched.host2
        dev = host2.eth0

        # Restore backlog size
        self._restore_backlog_size(host2, config)

        # Restore RPS config
        self._deconfigure_rps(host2, dev, config)

        return super().test_wide_deconfiguration(config)

    # def _set_queue_count(self, host, dev, config):
    #     """Save current combined queue count and set to 1."""
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
    #     original = getattr(config, "rss_original_queue_count", None)
    #     if original:
    #         host.run(f"ethtool -L {dev.name} combined {original}")
    #         logging.info(f"Restored combined queue count to {original} on {dev.name}")

    def _set_backlog_size(self, host, config):
        """Save current netdev_max_backlog and set to backlog_size param."""
        result = host.run("sysctl -n net.core.netdev_max_backlog")
        config.rps_original_backlog = result.stdout.strip()

        backlog = self.params.backlog_size
        host.run(f"sysctl -w net.core.netdev_max_backlog={backlog}")
        logging.info(f"Set netdev_max_backlog to {backlog}")

    def _restore_backlog_size(self, host, config):
        """Restore original netdev_max_backlog."""
        original = getattr(config, "rps_original_backlog", None)
        if original:
            host.run(f"sysctl -w net.core.netdev_max_backlog={original}")
            logging.info(f"Restored netdev_max_backlog to {original}")

    def _configure_rps(self, host, dev, config):
        """Configure RPS by writing CPU bitmask to all RX queues."""
        bitmask = 0
        for cpu in self.params.perf_tool_cpu:
            bitmask |= 1 << cpu
        hex_mask = format(bitmask, "x")

        host.run(
            f"for f in /sys/class/net/{dev.name}/queues/rx-*/rps_cpus; "
            f"do echo {hex_mask} > $f; done"
        )
        config.rss_rps_configured = True
        logging.info(f"Configured RPS on {dev.name} with CPU mask 0x{hex_mask}")

    def _deconfigure_rps(self, host, dev, config):
        """Reset RPS configuration (set mask to 0 = disabled)."""
        if getattr(config, "rss_rps_configured", False):
            host.run(
                f"for f in /sys/class/net/{dev.name}/queues/rx-*/rps_cpus; "
                f"do echo 0 > $f; done"
            )
            logging.info(f"Disabled RPS on {dev.name}")
