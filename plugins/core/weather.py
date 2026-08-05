from skills import Skill, SkillResult, registry
import asyncio
import logging
import time
import json
import difflib
import subprocess
import re
import memory
from typing import Optional, List, Dict, Callable, Any

log = logging.getLogger("LIS.plugins")

class WeatherSkill(Skill):
    name = "get_weather"
    description = "Get the current weather forecast for any location."

    async def execute(self, location: str = "", **kwargs) -> SkillResult:
        try:
            import httpx
            # Step 1: Geocode the location
            if not location:
                location = "auto"  # Will use IP-based location
            
            async with httpx.AsyncClient(timeout=8.0) as client:
                # Use Open-Meteo geocoding for dynamic locations
                if location != "auto":
                    from urllib.parse import quote
                    geo_resp = await client.get(f"https://geocoding-api.open-meteo.com/v1/search?name={quote(location)}&count=1")
                    if geo_resp.status_code == 200 and geo_resp.json().get("results"):
                        geo = geo_resp.json()["results"][0]
                        lat, lon = geo["latitude"], geo["longitude"]
                        loc_name = geo.get("name", location)
                    else:
                        # Fallback to IP location if geocoding fails on specific name
                        ip_resp = await client.get("https://ipapi.co/json/")
                        if ip_resp.status_code == 200:
                            ip_data = ip_resp.json()
                            lat, lon = ip_data.get("latitude", 0), ip_data.get("longitude", 0)
                            loc_name = ip_data.get("city", "your area")
                        else:
                            return SkillResult(False, f"Sorry sir, I couldn't find {location} on the map.")
                else:
                    # IP-based geolocation
                    ip_resp = await client.get("https://ipapi.co/json/")
                    if ip_resp.status_code == 200:
                        ip_data = ip_resp.json()
                        lat, lon = ip_data.get("latitude", 0), ip_data.get("longitude", 0)
                        loc_name = ip_data.get("city", "your area")
                    else:
                        lat, lon, loc_name = 0, 0, "unknown"

                # Step 2: Fetch weather
                url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,weathercode,windspeed_10m&temperature_unit=celsius"
                resp = await client.get(url)
                if resp.status_code == 200:
                    d = resp.json().get("current", {})
                    temp = d.get("temperature_2m", "?")
                    humidity = d.get("relative_humidity_2m", "?")
                    wind = d.get("windspeed_10m", "?")
                    code = d.get("weathercode", 0)
                    
                    # Weather code descriptions
                    conditions = {0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
                                  45: "Foggy", 48: "Depositing rime fog", 51: "Light drizzle", 61: "Light rain",
                                  63: "Moderate rain", 65: "Heavy rain", 71: "Light snow", 73: "Moderate snow",
                                  80: "Rain showers", 95: "Thunderstorm"}
                    condition = conditions.get(code, "Mixed conditions")
                    
                    # Track in adaptive learning
                    memory.remember(f"User asked weather for {loc_name}", "preference", importance=2)
                    
                    return SkillResult(True, 
                        f"The weather in {loc_name} is {temp} degrees with {condition.lower()}, sir. "
                        f"The humidity is {humidity} percent and the wind is at {wind} kilometers per hour. "
                        f"It feels quite nice, doesn't it?")
                return SkillResult(False, "I had a bit of trouble checking the weather, sir.")
        except Exception as e:
            log.error(f"Weather failed: {e}")
            return SkillResult(False, "I couldn't quite reach the weather station, I'm sorry.")
registry.register(WeatherSkill())

