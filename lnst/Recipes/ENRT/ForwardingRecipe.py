from collections.abc import Collection
import math
from socket import AF_INET, AF_INET6
from lnst.Common.Parameters import Param, IPv4NetworkParam, IPv6NetworkParam, StrParam
from lnst.Common.IpAddress import interface_addresses
from lnst.Controller import HostReq, DeviceReq, RecipeParam
from lnst.RecipeCommon.endpoints import EndpointPair, IPEndpoint
from lnst.Recipes.ENRT.MeasurementGenerators.ForwardingMeasurementGenerator import ForwardingMeasurementGenerator
from lnst.Recipes.ENRT.helpers import ip_endpoint_pairs
from lnst.Recipes.ENRT.BaseEnrtRecipe import BaseEnrtRecipe, EnrtConfiguration
from lnst.Recipes.ENRT.BaremetalEnrtRecipe import BaremetalEnrtRecipe
from lnst.RecipeCommon.Ping.PingEndpoints import PingEndpoints
import time
import itertools

from lnst.Common.IpAddress import Ip4Address, Ip6Address
from lnst.Devices import RemoteDevice
from lnst.RecipeCommon.endpoints import EndpointPair, IPEndpoint


class ForwardingRecipe(ForwardingMeasurementGenerator, BaremetalEnrtRecipe):
    host1 = HostReq()
    host1.eth0 = DeviceReq(label="net1", driver=RecipeParam("driver"))
    host1.eth1 = DeviceReq(label="net1", driver=RecipeParam("driver2"))

    host2 = HostReq()
    host2.eth0 = DeviceReq(label="net1", driver=RecipeParam("driver"))
    host2.eth1 = DeviceReq(label="net1", driver=RecipeParam("driver2"))

    net_ipv4 = IPv4NetworkParam(default="192.168.101.0/24")
    net_ipv6 = IPv6NetworkParam(default="fc00::/64")

    driver2 = StrParam()

    def test_wide_configuration(self) -> EnrtConfiguration:
        def filter_ip(iface, family):
            return [ip for ip in config._device_ips[iface] if ip.family == family][0]

        """
        Test wide configuration for this recipe involves just adding an IPv4 and
        IPv6 address to the matched eth0 nics on both hosts.

        host1.eth0 = 192.168.101.1/24 and fc00::1/64

        host2.eth0 = 192.168.101.2/24 and fc00::2/64
        """
        host1, host2 = self.matched.host1, self.matched.host2
        config: EnrtConfiguration = super().test_wide_configuration()

        egress4_net, ingress4_net, routed4_net, _ = self.params.net_ipv4.subnets(
            prefixlen_diff=2
        )
        egress6_net, ingress6_net, routed6_net, _ = self.params.net_ipv6.subnets(
            prefixlen_diff=2
        )
        #  ^          ^  direction based on generator PoV
        egress4 = interface_addresses(egress4_net)
        ingress4 = interface_addresses(ingress4_net)
        egress6 = interface_addresses(egress6_net)
        ingress6 = interface_addresses(ingress6_net)

        for host in [host1, host2]:
            config.configure_and_track_ip(host.eth0, next(egress4))
            config.configure_and_track_ip(host.eth0, next(egress6))
            host.eth0.up_and_wait()

            config.configure_and_track_ip(host.eth1, next(ingress4))
            config.configure_and_track_ip(host.eth1, next(ingress6))
            host.eth1.up_and_wait()

        host2.run("echo 1 > /proc/sys/net/ipv4/ip_forward")
        host2.run("echo 1 > /proc/sys/net/ipv6/conf/all/forwarding")

        self.wait_tentative_ips(config.configured_devices)

        host2.run(
            f"ip neigh add {filter_ip(host1.eth1, AF_INET)} lladdr {host1.eth1.hwaddr} dev {host2.eth1.name}"
        )
        host2.run(
            f"ip -6 neigh add {filter_ip(host1.eth1, AF_INET6)} lladdr {host1.eth1.hwaddr} dev {host2.eth1.name}"
        )
        # NOTE: needs to add neighs manually; generator ingress interface runs XDP drop,
        # so it doesn't respond to ARP/NDP requests from receiver egress interface
        # when routing traffic to ingress network of generator

        minimal_prefix_len = max(
            1, math.ceil(math.log2(self.params.perf_parallel_streams))
        )  # how many bites needed for networks
        routed4 = routed4_net.subnets(prefixlen_diff=minimal_prefix_len)
        routed6 = routed6_net.subnets(prefixlen_diff=minimal_prefix_len)
        routed4 = [next(routed4) for _ in range(self.params.perf_parallel_streams)]
        routed6 = [next(routed6) for _ in range(self.params.perf_parallel_streams)]

        self.routed = list(
            zip(routed4, routed6)
        )  # needs to be list, not generator. It's used multiple times
        for net4, net6 in self.routed:

            host2.run(
                f"ip neigh add {net4[1]} lladdr {host1.eth1.hwaddr} dev {host2.eth1.name}"
            )
            host2.run(
                f"ip -6 neigh add {net6[1]} lladdr {host1.eth1.hwaddr} dev {host2.eth1.name}"
            )
            # ^ net{4,6}[1]: IPvxNetwork.__getitem__ returns list of ALL IPs (including network IP), so first host is at [1]

            host1.run(
                f"ip route add {net4} via {filter_ip(host2.eth0, AF_INET)} dev {host1.eth0.name}"
            )
            host1.run(
                f"ip route add {net6} via {filter_ip(host2.eth0, AF_INET6)} dev {host1.eth0.name}"
            )

            host2.run(
                f"ip route add {net4} via {filter_ip(host1.eth1, AF_INET)} dev {host2.eth1.name}"
            )
            host2.run(
                f"ip route add {net6} via {filter_ip(host1.eth1, AF_INET6)} dev {host2.eth1.name}"
            )

        return config

    def test_wide_deconfiguration(self, config):
        super().test_wide_deconfiguration(config)
        host1, host2 = self.matched.host1, self.matched.host2

        host2.run("echo 0 > /proc/sys/net/ipv4/ip_forward")
        host2.run("echo 0 > /proc/sys/net/ipv6/conf/all/forwarding")

        # remove ingress network manually added neighs:
        for ip in config._device_ips[host1.eth1]:
            host2.run(f"ip neigh del {ip} dev {host2.eth1.name}")

        # remove routes and neighs for routed networks:
        for net4, net6 in self.routed:
            for host in [host1, host2]:
                host.run(f"ip route del {net4}")
                host.run(f"ip route del {net6}")

            host2.run(f"ip neigh del {net4[1]} dev {host2.eth1.name}")
            host2.run(f"ip -6 neigh del {net6[1]} dev {host2.eth1.name}")

        return config

    def generate_test_wide_description(self, config: EnrtConfiguration):
        """
        Test wide description is extended with the configured addresses
        """
        desc = super().generate_test_wide_description(config)
        desc += [
            "Configured {}.{}.ips = {}".format(dev.host.hostid, dev.name, dev.ips)
            for dev in config.configured_devices
        ]
        return desc

    def generate_ping_endpoints(self, config):
        """
        The ping endpoints for this recipe are simply the two matched NICs:

        host1.eth0 and host2.eth0

        Returned as::

            [PingEndpoints(self.matched.host1.eth0, self.matched.host2.eth0)]
        """
        return [PingEndpoints(self.matched.host1.eth0, self.matched.host2.eth0),
                PingEndpoints(self.matched.host2.eth1, self.matched.host1.eth1)]

    def generate_perf_endpoints(
        self, config: EnrtConfiguration
    ) -> list[Collection[EndpointPair[IPEndpoint]]]:
        """
        Function generates endpoints pairs where flow goes
        from host1.eth0 to host2.eth0. host2 then redirects
        traffic back to host1.eth1.
        """
        endpoint_pairs = []
        dev1 = self.matched.host1.eth0
        dev2 = self.matched.host2.eth0
        target_dev = self.matched.host1.eth1

        for ip_type in [Ip4Address, Ip6Address]:
            dev1_ips = [ip for ip in config.ips_for_device(dev1) if isinstance(ip, ip_type)]
            dev2_ips = [ip[0 if ip_type == Ip4Address else 1][1] for ip in self.routed]

            for ip1, ip2 in itertools.product(dev1_ips, dev2_ips):
                endpoint_pairs.append(
                    EndpointPair(
                        IPEndpoint(dev1, ip1),
                        IPEndpoint(dev2, ip2),
                    )
                )

        return [endpoint_pairs]
    # def do_perf_tests(self, recipe_config):
    #     print("testing...")
    #     time.sleep(10)
    #     input("waiting")
    #     self.matched.host1.run("ip link")
    #     self.matched.host2.run("ip link")
    #     return
