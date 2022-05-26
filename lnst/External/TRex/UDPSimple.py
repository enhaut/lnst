import logging
from lnst.External.TRex.TRexLib import TRexError


class UDPSimple(object):
    """
    Generate a simple continuous UDP stream
    Port MAC and IP addresses are used
    Extra arguments in kwargs:
    msg_size: the size of the packet to use (default 64)
    port_id:  The port the stream will be added to
    """

    def __init__(self):
        self._import_optionals()

    @staticmethod
    def _import_optionals():
        try:
            from trex_stl_lib.api import *
        except ModuleNotFoundError:
            msg = f"Module trex_stl_lib not found, please install it"
            logging.error(msg)
            raise TRexError(msg)

    def create_stream (self, **kwargs):
        # Use port's configured mac and ip addresses
        L2 = Ether()
        L3 = IP()
        L4 = UDP()

        size = kwargs.get("msg_size", 64)

        base_pkt = L2/L3/L4

        pad = max(0, size - len(base_pkt)) * 'x'
        packet = base_pkt/pad
        trex_packet = STLPktBuilder(pkt=packet)

        return STLStream(
                    packet=trex_packet,
                    mode=STLTXCont(percentage=100))

    def get_streams (self, direction = 0, **kwargs):
        # create 1 stream
        return [ self.create_stream(**kwargs) ]

# dynamic load - used for trex console or simulator
def register():
    return UDPSimple()
