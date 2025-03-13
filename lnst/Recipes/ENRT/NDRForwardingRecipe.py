from .PerfTestMixins import NoDropRateMixin
from .ForwardingRecipe import ForwardingRecipe


class NDRForwardingRecipe(NoDropRateMixin, ForwardingRecipe):
    def _get_nic_to_watch(self, flow):
        return self.matched.host2.eth1  # forwarding egress inf
