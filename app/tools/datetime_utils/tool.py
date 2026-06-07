from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _get_zone(timezone_name: str):
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        raise ValueError(
            "Unknown timezone. Use an IANA name like UTC, Asia/Kolkata, "
            "America/New_York, or Europe/London."
        )


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
