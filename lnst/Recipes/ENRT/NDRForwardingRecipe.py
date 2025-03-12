from .PerfTestMixins import NoDropRateMixin
from .ForwardingRecipe import ForwardingRecipe


class NDRForwardingRecipe(NoDropRateMixin, ForwardingRecipe):
    pass
