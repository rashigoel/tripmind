"""
get_route — OSRM (Open Source Routing Machine), free, no API key required.
Calculates road distance and travel duration between two coordinates.
"""
from __future__ import annotations
import httpx

_URL = "https://router.project-osrm.org/route/v1/{mode}/{coords}"

_VALID_MODES = {"driving", "walking", "cycling"}
_MODE_SPEED_KMH = {"driving": 60, "walking": 5, "cycling": 15}  # fallback estimates


def get_route(
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    mode: str = "driving",
) -> dict:
    """
    Calculate route between two points.

    Returns distance (km), duration (min + hr), and a human-readable summary.
    Useful for validating travel time constraints (e.g. ≤ 3.5 hrs for elderly).
    """
    mode = mode.lower()
    if mode not in _VALID_MODES:
        mode = "driving"

    coords = f"{origin_lon},{origin_lat};{dest_lon},{dest_lat}"

    try:
        resp = httpx.get(
            _URL.format(mode=mode, coords=coords),
            params={"overview": "false", "alternatives": "false", "steps": "false"},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != "Ok":
            return {"status": "error", "message": data.get("message", "OSRM returned error")}

        routes = data.get("routes") or []
        if not routes:
            return {"status": "error", "message": "No route found between these points"}

        route      = routes[0]
        dist_m     = route.get("distance", 0)
        dur_s      = route.get("duration", 0)
        dist_km    = round(dist_m / 1000, 1)
        dur_min    = round(dur_s / 60)
        dur_hr     = round(dur_s / 3600, 1)

        advisory = ""
        if mode == "driving" and dur_hr > 3.5:
            advisory = "Long drive — consider rest stops every 2 hours."
        elif mode == "driving" and dur_hr > 5:
            advisory = "Very long drive — consider overnight break or alternative transport."

        return {
            "status":      "ok",
            "mode":        mode,
            "distance_km": dist_km,
            "duration_min": dur_min,
            "duration_hr": dur_hr,
            "origin":      {"lat": origin_lat, "lon": origin_lon},
            "destination": {"lat": dest_lat,   "lon": dest_lon},
            "summary":     f"{dist_km} km by {mode} — approx {dur_hr} hrs ({dur_min} min)",
            "advisory":    advisory or None,
        }
    except httpx.HTTPStatusError as exc:
        return {"status": "error", "message": f"HTTP {exc.response.status_code}"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
