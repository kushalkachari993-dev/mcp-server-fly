import os
import requests

BASE_URL = "https://api.openweathermap.org/data/2.5/weather"


def get_weather_data(location: str) -> dict:
    api_key = os.getenv("OPENWEATHER_API_KEY")

    if not api_key:
        return {"error": "OPENWEATHER_API_KEY not set"}

    try:
        response = requests.get(
            BASE_URL,
            params={
                "q": location,
                "appid": api_key,
                "units": "metric"
            },
            timeout=10
        )

        data = response.json()

        if response.status_code != 200:
            return {"error": data.get("message", "Failed to fetch weather")}

        return data

    except requests.exceptions.Timeout:
        return {"error": "Request timed out"}
    except requests.exceptions.RequestException as e:
        return {"error": f"Network issue - {str(e)}"}