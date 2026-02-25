"""
Module implementing RPS measurement.

Copyright 2025 Red Hat, Inc.
Licensed under the GNU General Public License, version 2 as
published by the Free Software Foundation; see COPYING for details.
"""

__author__ = """
sdobron@redhat.com (Samuel Dobron)
"""

from lnst.RecipeCommon.Perf.Measurements.RSSMeasurement import RSSMeasurement


class RPSMeasurement(RSSMeasurement):
    """
    RPS (Receive Packet Steering) measurement.

    RPS is configured at the recipe level. This measurement only runs
    pktgen + TCIngDropMonitor (no receiver-side tool needed).
    """
    pass
