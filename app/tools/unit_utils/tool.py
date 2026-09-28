import json
import math
import re
from functools import lru_cache

import anyio
import pint
from pydantic import StrictFloat, StrictInt


_UNIT_EXPRESSION = re.compile(r"[A-Za-z_]+(?:\s*(?:\*\*|\^)\s*-?\d{1,2})?(?:\s*[*/]\s*[A-Za-z_]+(?:\s*(?:\*\*|\^)\s*-?\d{1,2})?)*", re.ASCII)


@lru_cache(maxsize=1)
def _registry():
    return pint.UnitRegistry()


def _parse_unit(registry, expression):
    expression = expression.strip()
    if len(expression) > 100 or not _UNIT_EXPRESSION.fullmatch(expression):
        raise ValueError("Use unit names with */ and integer powers, at most 100 characters")
    if any(abs(int(power)) > 12 for power in re.findall(r"-?\d+", expression)):
        raise ValueError("Unit powers must be between -12 and 12")
    return registry.parse_units(expression, as_delta=False)


def _convert(value, from_unit, to_unit):
    if not math.isfinite(value):
        raise ValueError("value must be finite")
    registry = _registry()
    source = _parse_unit(registry, from_unit)
    target = _parse_unit(registry, to_unit)
    quantity = registry.Quantity(value, source).to(target)
    converted = float(quantity.magnitude)
    if not math.isfinite(converted):
        raise ValueError("Converted value is outside the supported numeric range")
    return {"value": value, "from_unit": str(source), "to_unit": str(target), "result": converted}


def register(mcp):

    @mcp.tool()
    async def convert_units(value: StrictInt | StrictFloat, from_unit: str, to_unit: str) -> str:
        """Convert physical units with Pint, including offset temperatures (degC/degF).
        Accepts compatible unit names and compound units such as kilometer/hour or
        meter**2. Names are case-sensitive; powers are limited to -12..12. No currency
        rates, custom definitions, or conversion contexts. Returns JSON with result.
        """
        try:
            result = await anyio.to_thread.run_sync(_convert, value, from_unit, to_unit)
            return json.dumps(result, indent=2, allow_nan=False)
        except (ValueError, OverflowError, pint.errors.PintError, TypeError, ZeroDivisionError) as error:
            return f"Error: {error}"
