import time

from .FirewallMixin import NftablesMixin


class NftablesConntrackMixin(NftablesMixin):
    @NftablesMixin.firewall_rulesets.getter
    def firewall_rulesets(self):
        nic = self.matched.host2.eth0.name
        ruleset = ""
        return {self.matched.host2: ruleset}

    def apply_sub_configuration(self, config):
        super().apply_sub_configuration(config)
        host2 = self.matched.host2

        host2.run("sysctl -w net.netfilter.nf_conntrack_tcp_timeout_syn_sent=3600")
        # ^^ unloading the module in remove_sub_configuration() will reset it

    def remove_sub_configuration(self, config):
        # conntrack-related modules to be unloaded to not 
        # interfere with following tests. Also, it flushes
        # conntrack table.
        super().remove_sub_configuration(config)

        host2 = self.matched.host2

        host2.run("systemctl stop nftables")
        time.sleep(2)
        host2.run("modprobe -rv nft_ct nf_conntrack_netlink nf_conntrack nft_counter")

