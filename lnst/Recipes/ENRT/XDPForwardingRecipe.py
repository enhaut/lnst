from .ForwardingRecipe import ForwardingRecipe

from lnst.Common.LnstError import LnstError


class XDPForwardingRecipe(ForwardingRecipe):
    """
    Recipe for testing XDP forwarding.

    This recipe requires xdp-forward tool to be installed
    and present in PATH on the forwarding host.

    xdp-forward installation steps are described at
    https://github.com/xdp-project/xdp-tools/tree/main/xdp-forward
    """

    def test_wide_configuration(self):
        config = super().test_wide_configuration()
        job = self.matched.host2.forwarder_ns.run(f"xdp-forward load {self.matched.host2.forwarder_ns.eth0.name} {self.matched.host2.forwarder_ns.eth1.name}")
        if not job.passed:
            raise LnstError(f"Failed to load XDP program: {job.stderr}")

        return config

    def test_wide_deconfiguration(self, config):
        super().test_wide_deconfiguration(config)
        job = self.matched.host2.forwarder_ns.run(f"xdp-forward unload {self.matched.host2.forwarder_ns.eth0.name} {self.matched.host2.forwarder_ns.eth1.name}")
        if not job.passed:
            raise LnstError(f"Failed to unload XDP program: {job.stderr}")

        return config
