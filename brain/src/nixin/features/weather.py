"""Weather from Open-Meteo — free, no API key, no account.

Location comes from (in order): the city in the command, [assistant] city in nixin.toml,
or the phone's location (if the user allowed it on the phone).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather codes -> (hinglish, english)
_CODES: dict[int, tuple[str, str]] = {
    0: ("aasmaan saaf", "clear sky"), 1: ("zyadatar saaf", "mainly clear"), 2: ("thode baadal", "partly cloudy"),
    3: ("baadal chhaye", "overcast"), 45: ("kohra", "fog"), 48: ("jamta kohra", "freezing fog"),
    51: ("halki boonda-baandi", "light drizzle"), 53: ("boonda-baandi", "drizzle"), 55: ("tez boonda-baandi", "heavy drizzle"),
    61: ("halki baarish", "light rain"), 63: ("baarish", "rain"), 65: ("tez baarish", "heavy rain"),
    66: ("thandi baarish", "freezing rain"), 67: ("tez thandi baarish", "heavy freezing rain"),
    71: ("halki barf", "light snow"), 73: ("barf", "snow"), 75: ("bhaari barf", "heavy snow"), 77: ("barf ke daane", "snow grains"),
    80: ("halki bauchhar", "light showers"), 81: ("bauchhar", "showers"), 82: ("tez bauchhar", "violent showers"),
    85: ("barf ki bauchhar", "snow showers"), 86: ("bhaari barf ki bauchhar", "heavy snow showers"),
    95: ("toofan / bijli", "thunderstorm"), 96: ("toofan aur ole", "thunderstorm with hail"), 99: ("tez toofan aur ole", "severe thunderstorm with hail"),
}


def describe_code(code: int | None, lang: str = "hinglish") -> str:
    hi, en = _CODES.get(int(code or 0), ("mausam", "weather"))
    return en if lang == "english" else hi


@dataclass
class Place:
    name: str
    lat: float
    lon: float


class WeatherError(Exception):
    pass


class Weather:
    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self.http = http or httpx.AsyncClient(timeout=15)
        self._geo_cache: dict[str, Place] = {}

    async def geocode(self, city: str) -> Place:
        key = city.strip().lower()
        if key in self._geo_cache:
            return self._geo_cache[key]
        try:
            r = await self.http.get(GEO_URL, params={"name": city, "count": 1, "language": "en", "format": "json"})
            r.raise_for_status()
            res = (r.json().get("results") or [])
        except httpx.HTTPError as e:
            raise WeatherError(f"weather service unreachable: {e}") from e
        if not res:
            raise WeatherError(f"'{city}' naam ki jagah nahi mili")
        p = Place(f"{res[0]['name']}", float(res[0]["latitude"]), float(res[0]["longitude"]))
        self._geo_cache[key] = p
        return p

    async def forecast(self, place: Place) -> dict:
        params = {
            "latitude": place.lat, "longitude": place.lon, "timezone": "auto", "forecast_days": 3,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        }
        try:
            r = await self.http.get(FORECAST_URL, params=params)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            raise WeatherError(f"weather service unreachable: {e}") from e

    async def report(self, place: Place, when: str = "now", lang: str = "hinglish") -> tuple[str, dict]:
        data = await self.forecast(place)
        cur = data.get("current") or {}
        daily = data.get("daily") or {}
        idx = {"now": 0, "today": 0, "tomorrow": 1}.get(when, 0)

        def d(key: str, i: int = idx):
            vals = daily.get(key) or []
            return vals[i] if i < len(vals) else None

        rain = d("precipitation_probability_max")
        tmax, tmin = d("temperature_2m_max"), d("temperature_2m_min")
        if when == "tomorrow":
            desc = describe_code(d("weather_code"), lang)
            if lang == "english":
                text = f"Tomorrow in {place.name}: {desc}, {tmin:.0f}–{tmax:.0f}°C"
                text += f", {rain:.0f}% chance of rain." if rain is not None else "."
            else:
                text = f"Kal {place.name} mein {desc}, {tmin:.0f} se {tmax:.0f}°C"
                text += f", baarish ka chance {rain:.0f}%." if rain is not None else "."
        else:
            desc = describe_code(cur.get("weather_code"), lang)
            t, feels = cur.get("temperature_2m"), cur.get("apparent_temperature")
            if lang == "english":
                text = f"{place.name}: {desc}, {t:.0f}°C (feels {feels:.0f}°)"
                if tmax is not None:
                    text += f", today {tmin:.0f}–{tmax:.0f}°C"
                if rain is not None:
                    text += f", rain chance {rain:.0f}%"
                text += "."
            else:
                text = f"{place.name} mein abhi {desc}, {t:.0f}°C (mehsoos {feels:.0f}°)"
                if tmax is not None:
                    text += f", aaj {tmin:.0f} se {tmax:.0f}°C"
                if rain is not None:
                    text += f", baarish ka chance {rain:.0f}%"
                text += "."
        return text, data

    async def aclose(self) -> None:
        await self.http.aclose()
