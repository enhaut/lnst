import re
import logging
from ipaddress import ip_address
from typing import Literal, Optional, Any
from lnst.Common.IpAddress import Ip4Address
from lnst.Common.LnstError import LnstError
from lnst.Common.Parameters import DictParam
from lnst.Devices.VlanDevice import VlanDevice


from lnst.Recipes.ENRT.ConfigMixins.BaseHWConfigMixin import BaseHWConfigMixin
from lnst.Recipes.ENRT.ConfigMixins.DevInterruptTools import pin_dev_interrupts


class DevFlowsPinningHWConfigMixin(BaseHWConfigMixin):
    """
        This class is an extension to the :any:`BaseEnrtRecipe` class that
        enables flow steering across test device queues. Generated flows
        are iterated and pinned to `Flow.receiver_cpupin` CPU queue.
        Flow steering "keys" are configurable by overriding the
        `steer_flow_by` method.

        This mixin does NOT pin IRQs to `Flow.receiver_cpupin` CPUs, which
        is required for optimal performance.
    """

    def hw_config(self, config):
        super().hw_config(config)

        config.hw_config["flow_steering_rules"] = {}

        for combination in self.generate_flow_combinations(config):
            for flow in combination:
                if flow.steer_by is None:
                    continue

                receiver_nic = flow.receiver_nic
                if isinstance(receiver_nic, VlanDevice):
                    receiver_nic = receiver_nic.realdev

                if receiver_nic not in config.hw_config["flow_steering_rules"]:
                    config.hw_config["flow_steering_rules"][receiver_nic] = []

                pin_info = self._pin_flow(flow)
                config.hw_config["flow_steering_rules"][receiver_nic].append(
                    pin_info
                )

        return config

    def _pin_flow(self, flow) -> Any:
        cpupin = flow.receiver_cpupin
        if len(cpupin) > 1:
            logging.warning(
                "Flow is pinned to multiple CPUs.\
            Why? Usual rx-hash algos will throw packets from \
            the same flow to the same queue anyway (based on its' 5-tuple)."
            )

            logging.warning(f"Using only the first CPU: {cpupin[0]}")

        receiver_nic = flow.receiver_nic
        if isinstance(receiver_nic, VlanDevice):
            receiver_nic = receiver_nic.realdev

        flow_type = self._get_flow_type(flow)
        steering_key = self._get_steering_key(flow)
        job = flow.receiver.run(
            f"ethtool -N {receiver_nic.name} flow-type "
            f"{flow_type} {flow.steer_by} "
            f"{steering_key} action {cpupin[0]}"
        )
        if not job.passed:
            raise LnstError("Failed to pin flow to CPU.")

        desc = (
            f"{flow} is pinned to queue {cpupin[0]} by {flow.steer_by} ({steering_key})"
        )

        return self.rule_id_from_job(job), desc

    @staticmethod
    def rule_id_from_job(job):
        """
        If your driver returns rule ID in some other format,
        you should override this method. It's later used
        for removing the rule.
        """
        return int(re.search(r"Added rule with ID (\d+)", job.stdout).group(1))

    def _get_steering_key(self, flow):
        if flow.steer_by == "src-ip":
            return flow.generator_bind
        elif flow.steer_by == "dst-ip":
            return flow.receiver_bind
        elif flow.steer_by == "src-port":
            return flow.generator_port
        elif flow.steer_by == "dst-port":
            return flow.receiver_port
        else:
            raise NotImplementedError(
                f"Flow steering by {flow.steer_by} not implemented (yet)."
            )

    def _get_flow_type(self, flow):
        ip_version = (
            "4" if isinstance(ip_address(flow.receiver_bind), Ip4Address) else "6"
        )

        protocol = None
        if "ip" in flow.steer_by:  # e.g. src-ip, dst-ip
            protocol = "ip"

        elif "port" in flow.steer_by:  # e.g. src-port, dst-port
            if "tcp" in flow.type:
                protocol = "tcp"
            elif "sctp" in flow.type:
                protocol = "sctp"
            elif "udp" in flow.type or "xdp" in flow.type:  # xdp tests uses udp
                protocol = "udp"
            else:
                raise NotImplementedError(
                    f"Flow steering for {flow.type} not implemented (yet)."
                )
        else:
            raise NotImplementedError(
                f"Flow steering by {flow.steer_by} not implemented (yet)."
            )

        return protocol + ip_version

    def hw_deconfig(self, config):
        if "flow_steering_rules" in config.hw_config:
            for nic, rules in config.hw_config["flow_steering_rules"].items():
                for id, _ in rules:
                    nic.netns.run(f"ethtool -N {nic.name} delete {id}")

        super().hw_deconfig(config)

    def _create_perf_flow(self, *args, **kwargs):
        flow = super()._create_perf_flow(*args, **kwargs)

        flow.steer_by = self.steer_flow_by(flow)

        return flow

    def steer_flow_by(
        self, flow
    ) -> Optional[Literal["dst-ip", "src-ip", "dst-port", "src-port"]]:
        raise NotImplementedError("Should be implemented in derived class.")

    def describe_hw_config(self, config):
        desc = super().describe_hw_config(config)

        hw_config = config.hw_config

        for nic, rules in hw_config["flow_steering_rules"].items():
            desc.append(f"Steered flows on {nic.name}:")
            for id, rule in rules:
                desc.append(f"{rule} (rule: {id})")

        return desc
