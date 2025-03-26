from lnst.Devices import VlanDevice
from lnst.Common.Parameters import IntParam
from lnst.Recipes.ENRT.PingMixins import VlanPingEvaluatorMixin


class VlansForwardingMixin(VlanPingEvaluatorMixin):
    vlan0_id = IntParam(default=10)
    vlan1_id = IntParam(default=20)

    def test_wide_configuration(self):
        host1, host2 = self.matched.host1, self.matched.host2

        host1.eth0.up()
        host2.eth0.up()
        host2.eth1.up()
        # NOTE: ForwardingRecipe sets up interfaces returned by
        # {generator,receiver,forwarder_ingress,forwarder_egress}_nic properties
        # those are set to vlan devices in this recipe. But, underlying root
        # devices needs to be up before setting up the vlan devices.

        host1.vlan0 = VlanDevice(realdev=host1.eth0, vlan_id=self.params.vlan0_id)
        host2.vlan0 = VlanDevice(realdev=host2.eth0, vlan_id=self.params.vlan0_id)

        host2.vlan1 = VlanDevice(realdev=host2.eth1, vlan_id=self.params.vlan1_id)
        # NOTE: receiver vlan interface is created in setup_namespaces, it needs
        # to be created after moving eth1 to the namespace

        config = super().test_wide_configuration()

        return config

    def setup_namespaces(self):
        """
        Needs to be separated because of ForwardingRecipe.setup_namespaces
        moves eth1 (which is based device for vlan1) to the namespace).
        If we create vlan1 before moving eth1 to the namespace, it'll
        remove vlan1 device.
        """
        super().setup_namespaces()

        host1 = self.matched.host1

        host1.receiver_ns.eth1.up_and_wait()
        host1.receiver_ns.vlan1 = VlanDevice(
            realdev=host1.receiver_ns.eth1, vlan_id=self.params.vlan1_id
        )

    @property
    def generator_nic(self):
        return self.matched.host1.vlan0

    @property
    def receiver_nic(self):
        return self.matched.host1.receiver_ns.vlan1

    @property
    def forwarder_ingress_nic(self):
        return self.matched.host2.vlan0

    @property
    def forwarder_egress_nic(self):
        return self.matched.host2.vlan1
