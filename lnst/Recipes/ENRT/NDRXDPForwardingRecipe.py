from .PerfTestMixins import NoDropRateMixin
from .XDPForwardingRecipe import XDPForwardingRecipe


class NDRXDPForwardingRecipe(NoDropRateMixin, XDPForwardingRecipe):
    def _get_nic_to_watch(self, flow):
        return self.matched.host2.eth1  # forwarding egress inf
