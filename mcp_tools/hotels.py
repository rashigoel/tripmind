"""
search_hotels — OpenTripMap (free, uses OPENTRIPMAP_API_KEY).
Returns accommodation listings near a location sorted by rating.
"""
from __future__ import annotations
import os
import httpx

_RADIUS_URL  = "https://api.opentripmap.com/0.1/en/places/radius"
_DETAIL_URL  = "https://api.opentripmap.com/0.1/en/places/xid/{xid}"

_RATE_LABEL = {0: "Unrated", 1: "Basic", 2: "Standard", 3: "Good", 4: "Excellent"}

_KIND_LABEL: dict[str, str] = {
    "hotels":       "Hotel",
    "other_hotels": "Hotel",
    "apartments":   "Apartment / Self-catering",
    "hostels":      "Hostel",
    "guest_houses": "Guest House",
    "motels":       "Motel",
    "campsites":    "Campsite / Resort",
}


def search_hotels(
    lat: float,
    lon: float,
    checkin: str  = "",
    checkout: str = "",
    adults: int   = 2,
    radius: int   = 10,
    currency: str = "INR",
    max_results: int = 8,
) -> dict:
    """Search for hotels/accommodation near coordinates using OpenTripMap."""
    api_key = os.getenv("OPENTRIPMAP_API_KEY")
    if not api_key:
        return {"status": "error", "message": "OPENTRIPMAP_API_KEY not configured in .env"}

    radius_m = min(radius * 1000, 50000)

    try:
        resp = httpx.get(
            _RADIUS_URL,
            params={
                "radius": radius_m,
                "lon":    lon,
                "lat":    lat,
                "kinds":  "accomodations",
                "rate":   "1",
                "limit":  min(max_results * 2, 40),
                "apikey": api_key,
            },
            timeout=12.0,
        )
        resp.raise_for_status()
        features = resp.json().get("features", [])

        # Sort by rate desc, keep top max_results with a name
        features.sort(key=lambda f: f.get("properties", {}).get("rate", 0), reverse=True)

        hotels = []
        for f in features:
            if len(hotels) >= max_results:
                break
            props = f.get("properties", {})
            name  = (props.get("name") or "").strip()
            if not name:
                continue

            xid       = props.get("xid", "")
            rate      = props.get("rate", 0)
            kinds_raw = props.get("kinds", "")
            kind_tags = [k.strip() for k in kinds_raw.split(",")]
            kind_label = next(
                (_KIND_LABEL[k] for k in kind_tags if k in _KIND_LABEL),
                "Accommodation",
            )
            coord = f.get("geometry", {}).get("coordinates", [None, None])

            address     : str | None = None
            description : str | None = None
            if xid:
                try:
                    dr = httpx.get(
                        _DETAIL_URL.format(xid=xid),
                        params={"apikey": api_key},
                        timeout=8.0,
                    )
                    if dr.status_code == 200:
                        d    = dr.json()
                        addr = d.get("address") or {}
                        address = ", ".join(filter(None, [
                            addr.get("house_number"), addr.get("road"),
                            addr.get("suburb"), addr.get("city"),
                        ])) or None
                        description = (d.get("wikipedia_extracts") or {}).get("text", "")[:300] or None
                except Exception:
                    pass

            hotels.append({
                "name":        name,
                "type":        kind_label,
                "rating":      _RATE_LABEL.get(rate, str(rate)),
                "address":     address,
                "description": description,
                "lat":         coord[1] if len(coord) > 1 else None,
                "lon":         coord[0] if coord else None,
            })

        note_parts = [f"{len(hotels)} accommodation options within {radius} km"]
        if checkin and checkout:
            note_parts.append(f"{checkin} to {checkout}")
        note_parts.append("Prices not included — check Booking.com or MakeMyTrip for current rates")

        return {
            "status": "ok",
            "source": "OpenTripMap",
            "query":  {"lat": lat, "lon": lon, "radius_km": radius, "checkin": checkin, "checkout": checkout},
            "hotels": hotels,
            "total":  len(hotels),
            "note":   ". ".join(note_parts) + ".",
        }
    except httpx.HTTPStatusError as exc:
        return {"status": "error", "message": f"HTTP {exc.response.status_code}"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
