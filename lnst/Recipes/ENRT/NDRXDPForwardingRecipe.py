from .PerfTestMixins import NoDropRateMixin
from .XDPForwardingRecipe import XDPForwardingRecipe


class NDRXDPForwardingRecipe(NoDropRateMixin, XDPForwardingRecipe):
    pass
