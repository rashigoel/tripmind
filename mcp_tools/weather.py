"""
get_weather — Open-Meteo Forecast API (free, no key required).
Returns daily forecast with human-readable condition labels.
"""
from __future__ import annotations
import httpx

_URL = "https://api.open-meteo.com/v1/forecast"

# WMO Weather Interpretation Codes → human labels
_WMO: dict[int, str] = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}

_RAIN_WARNING_CODES = {61, 63, 65, 80, 81, 82, 95, 96, 99}


def _advisory(code: int | None, temp_max: float | None) -> str:
    if code in _RAIN_WARNING_CODES:
        return "Carry rain gear; outdoor activities may be limited."
    if temp_max and temp_max > 38:
        return "Very hot — schedule outdoor activities before 11 AM and after 5 PM."
    if temp_max and temp_max < 10:
        return "Cold — pack warm layers."
    return "Good conditions for outdoor activities."


def get_weather(lat: float, lon: float, days: int = 5) -> dict:
    """Fetch daily weather forecast for given coordinates."""
    try:
        resp = httpx.get(
            _URL,
            params={
                "latitude":     lat,
                "longitude":    lon,
                "daily": [
                    "temperature_2m_max", "temperature_2m_min",
                    "precipitation_sum",  "precipitation_probability_max",
                    "windspeed_10m_max",  "weathercode", "uv_index_max",
                ],
                "current": ["temperature_2m", "weathercode", "windspeed_10m", "relative_humidity_2m"],
                "forecast_days": min(max(int(days), 1), 7),
                "timezone":     "auto",
            },
            timeout=12.0,
        )
        resp.raise_for_status()
        data = resp.json()

        daily   = data.get("daily", {})
        current = data.get("current", {})
        times   = daily.get("time", [])

        def _get(key: str, i: int):
            arr = daily.get(key, [])
            return arr[i] if i < len(arr) else None

        forecast = []
        for i, date in enumerate(times):
            code = _get("weathercode", i)
            t_max = _get("temperature_2m_max", i)
            forecast.append({
                "date":               date,
                "condition":          _WMO.get(code, "Unknown"),
                "temp_max_c":         t_max,
                "temp_min_c":         _get("temperature_2m_min", i),
                "precipitation_mm":   _get("precipitation_sum", i),
                "rain_chance_pct":    _get("precipitation_probability_max", i),
                "wind_kmh":           _get("windspeed_10m_max", i),
                "uv_index":           _get("uv_index_max", i),
                "advisory":           _advisory(code, t_max),
            })

        cur_code = current.get("weathercode")
        return {
            "status":   "ok",
            "lat":      lat,
            "lon":      lon,
            "timezone": data.get("timezone"),
            "current": {
                "temperature_c": current.get("temperature_2m"),
                "humidity_pct":  current.get("relative_humidity_2m"),
                "condition":     _WMO.get(cur_code, "Unknown"),
                "wind_kmh":      current.get("windspeed_10m"),
            },
            "forecast": forecast,
            "severe_weather_days": [
                f["date"] for f in forecast if f.get("rain_chance_pct", 0) > 70
            ],
        }
    except httpx.HTTPStatusError as exc:
        return {"status": "error", "message": f"HTTP {exc.response.status_code}"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
