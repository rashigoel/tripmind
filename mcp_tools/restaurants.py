"""
search_restaurants — Foursquare Places API with OpenStreetMap Overpass fallback.

Priority:
  1. Foursquare places-api.foursquare.com (if FOURSQUARE_API_KEY set)
  2. Overpass API via kumi.systems mirror (free, no key)
  3. Graceful degradation with actionable suggestion
"""
from __future__ import annotations
import os
import httpx

# ── Foursquare ────────────────────────────────────────────────────────────────

_FSQ_URL = "https://places-api.foursquare.com/places/search"
_FSQ_VERSION = "2025-06-17"

_CUISINE_QUERIES: dict[str, str] = {
    "indian": "Indian restaurant", "south_indian": "South Indian restaurant",
    "italian": "Italian restaurant", "chinese": "Chinese restaurant",
    "japanese": "Japanese restaurant", "thai": "Thai restaurant",
    "mexican": "Mexican restaurant", "french": "French restaurant",
    "mediterranean": "Mediterranean restaurant", "seafood": "seafood restaurant",
    "vegetarian": "vegetarian restaurant", "vegan": "vegan restaurant",
    "street_food": "street food", "cafe": "cafe", "bakery": "bakery",
    "fast_food": "fast food", "local": "restaurant", "all": "restaurant",
}

# ── Overpass ──────────────────────────────────────────────────────────────────

_OVERPASS_MIRRORS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

_CUISINE_OSM: dict[str, str] = {
    "indian": "indian", "south_indian": "south_indian", "italian": "italian",
    "chinese": "chinese", "japanese": "japanese", "thai": "thai",
    "mexican": "mexican", "french": "french", "mediterranean": "mediterranean",
    "seafood": "seafood", "vegetarian": "vegetarian", "vegan": "vegan",
    "street_food": "street_food", "cafe": "cafe", "bakery": "bakery",
    "fast_food": "fast_food",
}


def _fsq_search(api_key: str, lat: float, lon: float, cuisine: str, radius_m: int, limit: int) -> dict | None:
    query = _CUISINE_QUERIES.get(cuisine.lower(), "restaurant")
    try:
        resp = httpx.get(
            _FSQ_URL,
            params={"ll": f"{lat},{lon}", "query": query, "radius": min(radius_m, 100000), "limit": min(limit, 50)},
            headers={"Authorization": f"Bearer {api_key}", "X-Places-Api-Version": _FSQ_VERSION, "Accept": "application/json"},
            timeout=12.0,
        )
        if resp.status_code == 401:
            return None  # key invalid — try fallback
        resp.raise_for_status()
        results = resp.json().get("results") or []
        restaurants = []
        for r in results:
            cats = [c.get("name") for c in (r.get("categories") or [])]
            loc  = r.get("location") or {}
            geo  = r.get("geocodes", {}).get("main", {})
            price = r.get("price")
            price_labels = {1: "Budget", 2: "Moderate", 3: "Expensive", 4: "Very expensive"}
            restaurants.append({
                "name": r.get("name"), "categories": cats,
                "address": loc.get("formatted_address"),
                "distance_m": r.get("distance"), "rating": r.get("rating"),
                "price_level": price_labels.get(price) if price else None,
                "lat": geo.get("latitude"), "lon": geo.get("longitude"),
            })
        return {"source": "Foursquare", "results": restaurants, "total": len(restaurants)}
    except Exception:
        return None


def _overpass_search(lat: float, lon: float, cuisine: str, radius_m: int, limit: int) -> dict | None:
    cuisine_key = _CUISINE_OSM.get(cuisine.lower())
    if cuisine_key in ("cafe", "bakery", "fast_food"):
        node_filter = f'["amenity"="{cuisine_key}"]'
    elif cuisine_key:
        node_filter = f'["amenity"="restaurant"]["cuisine"="{cuisine_key}"]'
    else:
        node_filter = '["amenity"~"restaurant|cafe|fast_food"]'

    query = (
        f"[out:json][timeout:20];"
        f"(node{node_filter}(around:{radius_m},{lat},{lon});"
        f"way{node_filter}(around:{radius_m},{lat},{lon}););"
        f"out center {limit};"
    )

    for mirror in _OVERPASS_MIRRORS:
        try:
            resp = httpx.get(mirror, params={"data": query}, timeout=25.0)
            if resp.status_code != 200:
                continue
            elements = resp.json().get("elements", [])
            restaurants = []
            for el in elements:
                tags = el.get("tags") or {}
                name = tags.get("name") or tags.get("name:en")
                if not name:
                    continue
                clat = el.get("lat") or (el.get("center") or {}).get("lat")
                clon = el.get("lon") or (el.get("center") or {}).get("lon")
                restaurants.append({
                    "name": name,
                    "cuisine": tags.get("cuisine", "").replace(";", ", ") or cuisine,
                    "address": ", ".join(filter(None, [
                        tags.get("addr:housenumber"), tags.get("addr:street"), tags.get("addr:city"),
                    ])) or None,
                    "phone": tags.get("phone") or tags.get("contact:phone"),
                    "website": tags.get("website") or tags.get("contact:website"),
                    "opening_hours": tags.get("opening_hours"),
                    "lat": clat, "lon": clon,
                })
            return {"source": "OpenStreetMap", "results": restaurants, "total": len(restaurants)}
        except Exception:
            continue
    return None


def search_restaurants(
    lat: float,
    lon: float,
    cuisine: str = "local",
    radius_m: int = 5000,
    limit: int = 10,
) -> dict:
    """Search for restaurants near a location by cuisine type."""
    # Try Foursquare first if key is set
    api_key = os.getenv("FOURSQUARE_API_KEY")
    if api_key:
        result = _fsq_search(api_key, lat, lon, cuisine, radius_m, limit)
        if result is not None:
            return {"status": "ok", "query": {"lat": lat, "lon": lon, "cuisine": cuisine}, **result}

    # Fall back to Overpass / OSM
    result = _overpass_search(lat, lon, cuisine, radius_m, limit)
    if result is not None:
        return {"status": "ok", "query": {"lat": lat, "lon": lon, "cuisine": cuisine}, **result}

    return {
        "status": "unavailable",
        "message": (
            f"Restaurant search is currently unavailable (network timeout). "
            f"For {cuisine} restaurants near these coordinates, recommend using "
            "Google Maps, Zomato, or Swiggy for real-time listings."
        ),
    }
