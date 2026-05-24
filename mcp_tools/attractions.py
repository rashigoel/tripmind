"""
search_attractions — OpenTripMap API (free tier, 5k req/day, API key required).
Returns tourist POIs: temples, viewpoints, museums, nature, heritage sites.
"""
from __future__ import annotations
import os
import httpx

_BASE = "https://api.opentripmap.com/0.1/en/places"

# Curated kinds mapping for common travel requests
KINDS = {
    "all":            "interesting_places",
    "nature":         "natural",
    "historical":     "historic",
    "cultural":       "cultural",
    "museums":        "museums",
    "religion":       "religion",
    "architecture":   "architecture",
    "beaches":        "beaches",
    "parks":          "parks_and_recreation_areas",
    "entertainment":  "amusements",
    "viewpoints":     "view_points",
    "heritage":       "historic,cultural",
}


def search_attractions(
    lat: float,
    lon: float,
    radius_m: int = 10000,
    kinds: str = "interesting_places",
    limit: int = 10,
) -> dict:
    """Find tourist attractions and POIs near a location."""
    api_key = os.getenv("OPENTRIPMAP_API_KEY")
    if not api_key:
        return {"status": "error", "message": "OPENTRIPMAP_API_KEY not configured in .env"}

    # Resolve alias
    resolved_kinds = KINDS.get(kinds.lower(), kinds)

    try:
        resp = httpx.get(
            f"{_BASE}/radius",
            params={
                "radius":  int(radius_m),
                "lon":     lon,
                "lat":     lat,
                "kinds":   resolved_kinds,
                "format":  "json",
                "limit":   min(int(limit), 20),
                "rate":    "2",          # filter by importance (0=all, 3=world-famous)
                "apikey":  api_key,
            },
            timeout=12.0,
        )
        resp.raise_for_status()
        places = resp.json()

        results = []
        for p in places:
            name = (p.get("name") or "").strip()
            if not name:
                continue
            results.append({
                "name":       name,
                "xid":        p.get("xid"),
                "kinds":      [k.strip() for k in (p.get("kinds") or "").split(",") if k.strip()][:4],
                "distance_m": round(p.get("dist", 0)),
                "lat":        (p.get("point") or {}).get("lat"),
                "lon":        (p.get("point") or {}).get("lon"),
                "rate":       p.get("rate", 0),
                "wikidata":   p.get("wikidata"),
            })

        # Sort by rate (importance) descending
        results.sort(key=lambda x: -x.get("rate", 0))

        return {
            "status":  "ok",
            "query":   {"lat": lat, "lon": lon, "radius_m": radius_m, "kinds": resolved_kinds},
            "results": results,
            "total":   len(results),
        }
    except httpx.HTTPStatusError as exc:
        return {"status": "error", "message": f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def get_attraction_details(xid: str) -> dict:
    """Get detailed info (description, address, hours) for a specific POI."""
    api_key = os.getenv("OPENTRIPMAP_API_KEY")
    if not api_key:
        return {"status": "error", "message": "OPENTRIPMAP_API_KEY not configured"}
    try:
        resp = httpx.get(
            f"{_BASE}/xid/{xid}",
            params={"apikey": api_key},
            timeout=10.0,
        )
        resp.raise_for_status()
        d = resp.json()
        wp = d.get("wikipedia_extracts") or {}
        return {
            "status":    "ok",
            "name":      d.get("name"),
            "kinds":     (d.get("kinds") or "").split(","),
            "address":   d.get("address", {}),
            "extract":   (wp.get("text") or "")[:400],
            "image":     (d.get("preview") or {}).get("source"),
            "url":       d.get("url"),
            "hours":     d.get("opening_hours"),
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
