#!/usr/bin/env python3
"""Re-evaluate measurement results from a previous LNST recipe run."""

import sys

from lnst.Controller.Recipe import RecipeRun, import_recipe_run
from lnst.Controller.RecipeResults import ResultLevel, ResultType
from lnst.Controller.RunSummaryFormatters import HumanReadableRunSummaryFormatter

old_run = import_recipe_run(sys.argv[1])

recipe_cls = type(old_run.recipe)
recipe = recipe_cls(**old_run.recipe.params._to_dict())

run = RecipeRun(recipe, match=old_run.match)
recipe._init_run(run)
recipe.evaluate_only(old_run.perf_results, old_run.ping_results)

overall_result = ResultType.PASS
fmt = HumanReadableRunSummaryFormatter(level=ResultLevel.IMPORTANT)
for run in recipe.runs:
    print(fmt.format_run(run))
    overall_result = ResultType.max_severity(overall_result, run.overall_result)

sys.exit(0 if overall_result == ResultType.PASS else 1)
