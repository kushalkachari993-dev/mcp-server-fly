import math
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _get_zone(timezone_name: str):
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        raise ValueError(
            "Unknown timezone. Use an IANA name like UTC, Asia/Kolkata, "
            "America/New_York, or Europe/London."
        )


def _timestamp_scale(unit: str) -> int:
    if unit == "seconds":
        return 1
    if unit == "milliseconds":
        return 1000
    raise ValueError("Unit must be seconds or milliseconds")


def register(mcp):

    @mcp.tool()
    def current_time(timezone_name: str = "UTC") -> str:
        """
        Get the current date and time for an IANA timezone.
        Examples: UTC, Asia/Kolkata, America/New_York, Europe/London.
        """

        try:
            zone = _get_zone(timezone_name.strip() or "UTC")
            now = datetime.now(zone)
            return now.isoformat(timespec="seconds")
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool()
    def convert_time(datetime_text: str, from_timezone: str, to_timezone: str) -> str:
        """
        Convert a datetime between IANA timezones.
        datetime_text should be ISO-like, for example: 2026-06-07 14:30.
        """

        try:
            source_zone = _get_zone(from_timezone.strip())
            target_zone = _get_zone(to_timezone.strip())
            clean_text = datetime_text.strip().replace("Z", "+00:00")
            parsed = datetime.fromisoformat(clean_text)

            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=source_zone)
            else:
                parsed = parsed.astimezone(source_zone)

            converted = parsed.astimezone(target_zone)
            return converted.isoformat(timespec="seconds")
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool()
    def timestamp_to_datetime(
        timestamp: float, timezone_name: str = "UTC", unit: str = "seconds"
    ) -> str:
        """Convert a Unix timestamp to an ISO datetime in an IANA timezone.
        The unit must be seconds or milliseconds. Negative timestamps are supported.
        """
        try:
            scale = _timestamp_scale(unit)
            if not math.isfinite(timestamp):
                raise ValueError("Timestamp must be finite")
            zone = _get_zone(timezone_name.strip() or "UTC")
            return datetime.fromtimestamp(timestamp / scale, tz=zone).isoformat()
        except (ValueError, OverflowError, OSError) as error:
            return f"Error: {error}"

    @mcp.tool()
    def datetime_to_timestamp(datetime_text: str, unit: str = "seconds") -> str:
        """Convert an ISO datetime to a Unix timestamp in seconds or milliseconds.
        Respects an explicit UTC offset or Z suffix. A datetime without an offset
        is interpreted as UTC. Preserves fractional seconds to microsecond precision.
        """
        try:
            scale = _timestamp_scale(unit)
            parsed = datetime.fromisoformat(datetime_text.strip())
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            delta = parsed.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
            microseconds = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
            return format(Decimal(microseconds) * scale / 1000000, "f")
        except (ValueError, OverflowError) as error:
            return f"Error: {error}"
