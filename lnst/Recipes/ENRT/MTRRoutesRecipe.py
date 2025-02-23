import logging
import pathlib

from lnst.Common.Parameters import StrParam


class MTRRoutesRecipe:
    mrt_file = StrParam()

    def test_wide_configuration(self):
        config = super().test_wide_configuration()
        host2 = self.matched.host2

        routes_path = pathlib.Path(self.params.mrt_file)
        if not routes_path.exists():
            raise ValueError(f"Routes file {routes_path} does not exist")

        logging.info(f"Setting up routes from {routes_path}")

        with routes_path.open() as f:
            for i, line in enumerate(f):
                _, _, _, nexthop, _, network, *_ = line.strip().split("|")
                host2.run(f"ip route add {network} via {nexthop} dev {host2.eth1.name} metric {i} onlink")
                # setting metric just to allow multiple routes to the same networks

        return config

    def test_wide_deconfiguration(self, config):
        host2 = self.matched.host2

        logging.info("Removing routes")

        routes_path = pathlib.Path(self.params.mrt_file)
        with routes_path.open() as f:
            for line in f:
                _, _, _, nexthop, _, network, *_ = line.strip().split("|")
                host2.run(f"ip route del {network} via {nexthop}")

        return super().test_wide_deconfiguration(config)
