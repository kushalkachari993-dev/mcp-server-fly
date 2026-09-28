import json
from datetime import datetime

from croniter import CroniterError, croniter

from app.tools.datetime_utils.tool import _get_zone


def register(mcp):

    @mcp.tool()
    def cron_next_runs(
        expression: str,
        timezone_name: str = "UTC",
        count: int = 5,
        from_datetime: str = "",
    ) -> str:
        """Preview the next 1-20 runs of a five-field cron schedule in an IANA timezone.
        Fields are minute, hour, day-of-month, month, day-of-week. Runs are strictly
        after from_datetime (ISO format), or the current time if omitted. Naive
        input uses timezone_name; explicit offsets are converted to that timezone.
        Searches at most five years ahead per run. Does not create a scheduled job.
        """
        try:
            expression = expression.strip()
            if len(expression) > 200 or len(expression.split()) != 5:
                raise ValueError("Use a five-field cron expression of at most 200 characters")
            if not 1 <= count <= 20:
                raise ValueError("Count must be between 1 and 20")
            zone = _get_zone(timezone_name.strip() or "UTC")
            base = datetime.fromisoformat(from_datetime.strip()) if from_datetime.strip() else datetime.now(zone)
            base = base.replace(tzinfo=zone) if base.tzinfo is None else base.astimezone(zone)
            schedule = croniter(expression, base, max_years_between_matches=5)
            runs = [schedule.get_next(datetime).isoformat() for _ in range(count)]
            return json.dumps({
                "expression": expression, "timezone": zone.key,
                "start": base.isoformat(), "next_runs": runs,
            }, indent=2)
        except (ValueError, CroniterError, OverflowError) as error:
            return f"Error: {error}"
