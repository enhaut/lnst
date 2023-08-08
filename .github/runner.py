from lnst.Controller import Controller, HostReq, DeviceReq, BaseRecipe
from lnst.Controller.ContainerPoolManager import ContainerPoolManager
from lnst.Controller.MachineMapper import ContainerMapper
from lnst.Recipes.ENRT.XDPDropRecipe import XDPDropRecipe

ctl = Controller(
    debug=1,
)

recipe_instance = XDPDropRecipe(
        driver='ice',
        perf_tool_cpu=[5,6,7,8,9],
        perf_tool_cpu_policy='all',
        perf_parallel_processes=1,
        perf_duration=60,
        ip_versions=['ipv4'],
        perf_tests=['tcp_stream'],
        perf_msg_sizes=[60],
        rx_pause_frames=False,
        tx_pause_frames=False,
        disable_turboboost=True,
        minimal_idlestates_latency=0,
        drop_caches=True,
        offload_combinations=[{'gro': 'on', 'gso': 'on', 'tso': 'on', 'tx': 'on'}],
        perf_warmup_duration=3)
r = ctl.run(recipe_instance)

from lnst.Controller.Recipe import export_recipe_run

export_recipe_run(recipe_instance.runs[0], "/root/")

overall_result = all([run.overall_result for run in recipe_instance.runs])

exit(not overall_result)

