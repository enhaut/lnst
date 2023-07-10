from lnst.Common.Parameters import ConstParam
from lnst.Recipes.ENRT.SimpleNetworkRecipe import SimpleNetworkRecipe
from lnst.Recipes.ENRT.MeasurementGenerators.XDPFlowMeasurementGenerator import XDPFlowMeasurementGenerator


class XDPDropRecipe(XDPFlowMeasurementGenerator, SimpleNetworkRecipe):
    xdp_command = ConstParam(value="drop")

