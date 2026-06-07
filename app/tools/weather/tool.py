from .service import get_weather_data


def register(mcp):

    @mcp.tool()
    def get_weather(location: str) -> str:
        """
        Get current weather for any city.
        Example: Kolkata, Delhi, London
        """

        location = location.strip()
        if not location:
            return "Error: Please provide a valid location"

        data = get_weather_data(location)

        if "error" in data:
            return f"Error: {data['error']}"

        main = data.get("main", {})
        weather = data.get("weather", [{}])[0]
        wind = data.get("wind", {})

        return (
            f"📍 Weather in {location}:\n"
            f"🌡 Temperature: {main.get('temp')}°C "
            f"(feels like {main.get('feels_like')}°C)\n"
            f"🌥 Condition: {weather.get('description')}\n"
            f"💧 Humidity: {main.get('humidity')}%\n"
            f"🌬 Wind Speed: {wind.get('speed')} m/s"
        )