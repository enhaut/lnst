class PingEndpoints:
    def __init__(
        self, endpoint1, endpoint2, reachable=True, use_product_combinations=False
    ):
        self.endpoints = [endpoint1, endpoint2]
        self.reachable = reachable
        self.use_product_combinations = use_product_combinations  # instead of using zip for combinating endpoint IPs product is used

    @property
    def endpoints(self):
        return self._endpoints

    @endpoints.setter
    def endpoints(self, endpoints):
        self._endpoints = endpoints

    @property
    def reachable(self):
        return self._reachable

    @reachable.setter
    def reachable(self, reachable):
        self._reachable = reachable
