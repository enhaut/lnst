from lnst.Common.Parameters import ListParam, StrParam, ChoiceParam
from lnst.Recipes.ENRT.ConfigMixins.BaseHWConfigMixin import BaseHWConfigMixin
from lnst.Recipes.ENRT.ConfigMixins.DevInterruptTools import pin_dev_interrupts


class MultiDevInterruptHWConfigMixin(BaseHWConfigMixin):
    """
    This class is an extension to the :any:`BaseEnrtRecipe` class that enables
    the CPU affinity (CPU pinning) of the test device IRQs. The test devices
    are defined by :attr:`dev_interrupt_hw_config_dev_list` property.

    This mixin is a "multi device" variant of the :any:`DevInterruptHWConfigMixin`
    and allows configuration of individual devices instead of sharing the same
    configuration. This may be required when different device IRQ pinning is
    required by a flow generator and receiver host.

     .. note::
        Note that this Mixin also stops the irqbalance service.

    :param dev_intr_cpu_lists:
        (optional test parameter) each list specifies the CPU ids to which the
        test device IRQs should be pinned, to skip the configuration for a device,
        specify an empty list
    :param dev_intr_cpu_policies:
        (optional test parameter) for each test devices policy can be defined:
        * all - pin each IRQ to all CPUs defined by the :attr:`dev_intr_cpu_lists`
        * round-robin - use one CPU from the :attr:`dev_intr_cpu_lists` for each
        test device IRQ, start from beginning if the number of IRQs is bigger
        than the number of CPUs
    """

    dev_intr_cpu_lists = ListParam(type=ListParam(), mandatory=False, default=[[]])
    dev_intr_cpu_policies = ListParam(
        type=ChoiceParam(type=StrParam, choices=set(["all", "round-robin"])),
        mandatory=False,
        default=[],
    )

    @property
    def dev_interrupt_hw_config_dev_list(self):
        """
        The value of this property is a list of devices for which the IRQ CPU
        affinity should be configured. It has to be defined by a derived class.
        """
        return []

    def hw_config(self, config):
        super().hw_config(config)

        hw_config = config.hw_config

        if "dev_intr_cpu_lists" in self.params and any(self.params.dev_intr_cpu_lists):
            intr_cfg = hw_config["dev_intr_cpu_configuration"] = {}
            intr_cfg["irq_devs"] = {}
            intr_cfg["irqbalance_hosts"] = []

            for dev, cpus, policy in zip(
                self.dev_interrupt_hw_config_dev_list,
                self.params.dev_intr_cpu_lists,
                self.params.dev_intr_cpu_policies,
            ):
                if not cpus:
                    continue

                if dev.host not in intr_cfg["irqbalance_hosts"]:
                    dev.host.run("service irqbalance stop")
                    intr_cfg["irqbalance_hosts"].append(dev.host)

                # TODO better service handling through HostAPI
                pin_dev_interrupts(dev, cpus, policy)
                intr_cfg["irq_devs"][dev] = (cpus, policy)

    def describe_hw_config(self, config):
        desc = super().describe_hw_config(config)

        hw_config = config.hw_config

        intr_cfg = hw_config.get("dev_intr_cpu_configuration", None)
        if intr_cfg:
            desc += [
                "{} irqbalance stopped".format(host.hostid)
                for host in intr_cfg["irqbalance_hosts"]
            ]
            desc += [
                "{}.{} irqs bound to cpu {} with policy:{}".format(
                    dev.host.hostid, dev._id, cpu, policy
                )
                for dev, (cpu, policy) in intr_cfg["irq_devs"].items()
            ]
        else:
            desc.append("Device irq configuration skipped.")
        return desc
