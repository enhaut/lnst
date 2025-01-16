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
from lnst.Recipes.ENRT.ConfigMixins.MultiDevInterruptHWConfigMixin import (
    MultiDevInterruptHWConfigMixin,
)
from lnst.Recipes.ENRT.ConfigMixins.OffloadSubConfigMixin import OffloadSubConfigMixin

from lnst.Controller.NetNamespace import NetNamespace

class ForwardingRecipe(MultiDevInterruptHWConfigMixin, ForwardingMeasurementGenerator, OffloadSubConfigMixin, BaremetalEnrtRecipe):
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
        # TODO:ingress net might be removed completely
        # as destination networks are routed (but in separate NS)

        host1.receiver_ns = NetNamespace("lnst-receiver_ns")
        host1.receiver_ns.eth1 = host1.eth1
        host1.receiver_ns.run("ip link set dev lo up")

        for host in [host1, host2]:
            config.configure_and_track_ip(host.eth0, next(egress4))
            config.configure_and_track_ip(host.eth0, next(egress6))
            host.eth0.up_and_wait()

        receiver_ip = next(ingress4)
        receiver_ip6 = next(ingress6)
        config.configure_and_track_ip(host1.receiver_ns.eth1, receiver_ip)
        config.configure_and_track_ip(host1.receiver_ns.eth1, receiver_ip6)
        host1.receiver_ns.eth1.up_and_wait()

        config.configure_and_track_ip(host2.eth1, next(ingress4))
        config.configure_and_track_ip(host2.eth1, next(ingress6))
        host2.eth1.up_and_wait()

        host2.run("echo 1 > /proc/sys/net/ipv4/ip_forward")
        host2.run("echo 1 > /proc/sys/net/ipv6/conf/all/forwarding")

        self.wait_tentative_ips(config.configured_devices)

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
            config.configure_and_track_ip(host1.receiver_ns.eth1, Ip4Address(f"{net4[1]}/{net4.prefixlen}"))
            config.configure_and_track_ip(host1.receiver_ns.eth1, Ip6Address(f"{net6[1]}/{net6.prefixlen}"))
            # IPs above don't even need to be configured, they are
            # needed just for connectivity check. The routing is
            # based on static routes added bellow.

            host2.run(f"ip route add {net4} via {receiver_ip} dev {host2.eth1.name}")
            host2.run(f"ip -6 route add {net6} via {receiver_ip6} dev {host2.eth1.name}")

        # neighbors needs to be static as receiver is running XDP drop
        # which drops ARP/NDP packets as well
        host2.run(f"ip neigh add {receiver_ip} lladdr {host1.receiver_ns.eth1.hwaddr} dev {host2.eth1.name}")
        host2.run(f"ip -6 neigh add {receiver_ip6} lladdr {host1.receiver_ns.eth1.hwaddr} dev {host2.eth1.name}")
        self.router_ips = receiver_ip, receiver_ip6

        # setup default routes in receiver namespace to enable communication TO outside
        host1.receiver_ns.run(f"ip route add 0.0.0.0/0 via {filter_ip(host2.eth0, AF_INET)} dev {host1.receiver_ns.eth1.name}")
        host1.receiver_ns.run(f"ip -6 route add ::/0 via {filter_ip(host2.eth0, AF_INET6)} dev {host1.receiver_ns.eth1.name}")

        return config

    def test_wide_deconfiguration(self, config):
        super().test_wide_deconfiguration(config)
        host1, host2 = self.matched.host1, self.matched.host2

        host2.run("echo 0 > /proc/sys/net/ipv4/ip_forward")
        host2.run("echo 0 > /proc/sys/net/ipv6/conf/all/forwarding")

        # remove routes and neighs for routed networks:
        for net4, net6 in self.routed:
            for host in [host1, host2]:
                host.run(f"ip route del {net4}")
                host.run(f"ip route del {net6}")

        host2.run(f"ip -6 neigh del {self.router_ips[0]} dev {host2.eth1.name}")
        host2.run(f"ip -6 neigh del {self.router_ips[1]} dev {host2.eth1.name}")

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
                PingEndpoints(self.matched.host2.eth1, self.matched.host1.receiver_ns.eth1, use_product_combinations=True)]
                # PingEndpoints(self.matched.host1.eth0, self.matched.host1.receiver_ns.eth1, use_product_combinations=True)]  # TODO:

    def generate_perf_endpoints(
        self, config: EnrtConfiguration
    ) -> list[Collection[EndpointPair[IPEndpoint]]]:
        """
        Function generates endpoints pairs where flow goes
        from host1.eth0 to host2.eth0. host2 then redirects
        traffic back to host1.eth1.

        Pktgen doesn't do any lookup for MAC based on IP,
        so this function needs to set destination device
        forwarder NIC (because it's MAC is used in PktGen)
        BUT destination IP is set to regular destination.

        This is similar to what PC usually do, if it
        receives packet to some other net, it'll set IP
        to the destination and forward it to the next hop,
        which is in this case forwarder (host2).
        """
        endpoint_pairs = []
        dev1 = self.matched.host1.eth0
        dev2 = self.matched.host2.eth0

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

    @property
    def offload_nics(self):
        return [self.matched.host1.receiver_ns.eth1, self.matched.host2.eth0, self.matched.host2.eth1]
