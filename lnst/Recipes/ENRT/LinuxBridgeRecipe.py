from lnst.Common.Parameters import IPv4NetworkParam, IPv6NetworkParam
from lnst.Common.IpAddress import interface_addresses
from lnst.Controller import HostReq, DeviceReq, RecipeParam
from lnst.Recipes.ENRT.BaremetalEnrtRecipe import BaremetalEnrtRecipe
from lnst.RecipeCommon.Ping.PingEndpoints import PingEndpoints
from lnst.Recipes.ENRT.ConfigMixins.MTUHWConfigMixin import MTUHWConfigMixin
from lnst.Devices import BridgeDevice


class LinuxBridgeRecipe(MTUHWConfigMixin, BaremetalEnrtRecipe):
    """
    This recipe implements Enrt testing for a simple network scenario that looks
    as follows

    .. code-block:: none

                    +--------+
             +------+ switch +-----+
             |      +--------+     |
          +--+-+                 +-+--+
        +-|eth0|-+             +-|eth0|-+
        | +----+ |             | +----+ |
        |   |    |             |   |    |
        |  br0   |             |  br0   |
        |        |             |        |
        | host1  |             | host2  |
        +--------+             +--------+

    All sub configurations are included via Mixin classes.

    The actual test machinery is implemented in the :any:`BaseEnrtRecipe` class.
    """

    host1 = HostReq()
    host1.eth0 = DeviceReq(label="net1", driver=RecipeParam("driver"))

    host2 = HostReq()
    host2.eth0 = DeviceReq(label="net1", driver=RecipeParam("driver"))

    net_ipv4 = IPv4NetworkParam(default="192.168.101.0/24")
    net_ipv6 = IPv6NetworkParam(default="fc00::/64")

    def test_wide_configuration(self):
        """
        Test wide configuration for this recipe involves adding the matched
        NICs into a Linux bridge and configuring an IPv4 and IPv6 address
        on the bridge device on both hosts.

        host1.br0 = 192.168.101.1/24 and fc00::1/64

        host2.br0 = 192.168.101.2/24 and fc00::2/64
        """
        host1, host2 = self.matched.host1, self.matched.host2
        configuration = super().test_wide_configuration()
        configuration.test_wide_devices = []

        ipv4_addr = interface_addresses(self.params.net_ipv4)
        ipv6_addr = interface_addresses(self.params.net_ipv6)

        for host in [host1, host2]:
            host.br0 = BridgeDevice()
            host.eth0.down()
            host.br0.slave_add(host.eth0)
            host.eth0.up()
            host.br0.up()
            host.br0.ip_add(next(ipv4_addr))
            host.br0.ip_add(next(ipv6_addr))

            configuration.test_wide_devices.append(host.br0)

        self.wait_tentative_ips(configuration.test_wide_devices)

        return configuration

    def generate_test_wide_description(self, config):
        """
        Test wide description is extended with the configured addresses
        """
        desc = super().generate_test_wide_description(config)
        desc += [
            "\n".join(
                [
                    "Created bridge device {} on host {}".format(
                        dev.name,
                        dev.host.hostid,
                    )
                    for dev in config.test_wide_devices
                ]
            ),
            "\n".join(
                [
                    "Added device {} to bridge device {} on host {}".format(
                        dev.name,
                        br_dev.name,
                        dev.host.hostid,
                    )
                    for br_dev in config.test_wide_devices
                    for dev in br_dev.slaves
                ]
            ),
            "\n".join(
                [
                    "Configured {}.{}.ips = {}".format(
                        dev.host.hostid, dev.name, dev.ips
                    )
                    for dev in config.test_wide_devices
                ]
            ),
        ]
        return desc

    def test_wide_deconfiguration(self, config):
        """"""  # overriding the parent docstring
        del config.test_wide_devices

        super().test_wide_deconfiguration(config)

    def generate_ping_endpoints(self, config):
        """
        The ping endpoints for this recipe are the created bridge devices:

        host1.br0 and host2.br0

        Returned as::

            [PingEndpoints(self.matched.host1.br0, self.matched.host2.br0)]
        """
        return [PingEndpoints(self.matched.host1.br0, self.matched.host2.br0)]

    def generate_perf_endpoints(self, config):
        """
        The perf endpoints for this recipe are the created bridge devices:

        host1.br0 and host2.br0

        Returned as::

            [(self.matched.host1.br0, self.matched.host2.br0)]
        """
        return [(self.matched.host1.br0, self.matched.host2.br0)]

    @property
    def mtu_hw_config_dev_list(self):
        return [self.matched.host1.eth0, self.matched.host2.eth0]