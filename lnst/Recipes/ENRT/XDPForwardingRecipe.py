from .ForwardingRecipe import ForwardingRecipe


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
        self.matched.host2.run(f"xdp-forward load {self.matched.host2.eth0.name} {self.matched.host2.eth1.name}")
        return config

    def test_wide_deconfiguration(self, config):
        super().test_wide_deconfiguration(config)
        self.matched.host2.run(f"xdp-forward unload {self.matched.host2.eth0.name} {self.matched.host2.eth1.name}")
        return config
