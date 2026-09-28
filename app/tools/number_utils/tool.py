import json
import math
import statistics

from pydantic import StrictFloat, StrictInt


def register(mcp):

    @mcp.tool()
    def summarize_numbers(values: list[StrictInt | StrictFloat]) -> str:
        """Summarize 1-10000 finite numbers, without accepting strings or booleans.
        Returns count, sum, min, max, mean, median, population_stddev, and
        sample_stddev (null for a single value). Uses Python statistics.
        """
        try:
            if not 1 <= len(values) <= 10000:
                raise ValueError("Provide between 1 and 10000 numbers")
            if any(not math.isfinite(value) for value in values):
                raise ValueError("All values must be finite numbers")
            result = {"count": len(values), "sum": math.fsum(values),
                      "min": min(values), "max": max(values),
                      "mean": statistics.mean(values), "median": statistics.median(values),
                      "population_stddev": statistics.pstdev(values),
                      "sample_stddev": statistics.stdev(values) if len(values) > 1 else None}
            return json.dumps(result, indent=2, allow_nan=False)
        except (ValueError, OverflowError, statistics.StatisticsError) as error:
            return f"Error: {error}"
