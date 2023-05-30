import requests

from lnst.Common.LnstError import LnstError
from lnst.Common.Parameters import BoolParam, StrParam


class BaseRESTConfigMixin:
    api_url = StrParam()
    rest_user = StrParam(default=None)
    rest_password = StrParam(default=None)
    ssl_verify = BoolParam(default=True, mandatory=False)

    @staticmethod
    def __get_request_function(method: str):
        try:
            return getattr(requests, method)
        except AttributeError:
            raise LnstError(f"Method {method} is not supported")

    def __build_request(self, endpoint: str, **kwargs):
        kwargs["url"] = self.params.api_url + endpoint

        if self.params.rest_user and self.params.rest_password:
            kwargs["auth"] = (self.rest_user, self.rest_password)

        kwargs["verify"] = self.params.ssl_verify

        return kwargs

    def api_request(self, method: str, endpoint: str, response_code: int = 200, **kwargs) -> bytes:
        request = self.__build_request(endpoint, **kwargs)
        req_func = self.__get_request_function(method)

        response = req_func(**request)
        if response.status_code != response_code:
            raise LnstError(f"Request failed with status code {response.status_code}")

        return response.content










