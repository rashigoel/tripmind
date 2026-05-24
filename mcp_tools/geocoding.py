"""
resolve_location — Open-Meteo Geocoding API (free, no key required).
Always call this first to get lat/lon before any other location-based tool.
"""
from __future__ import annotations
import httpx

_URL = "https://geocoding-api.open-meteo.com/v1/search"

# ISO-2 country code lookup for common country names in user queries
_COUNTRY_CODES: dict[str, str] = {
    "india": "IN", "usa": "US", "united states": "US", "uk": "GB",
    "united kingdom": "GB", "france": "FR", "germany": "DE", "italy": "IT",
    "spain": "ES", "japan": "JP", "china": "CN", "australia": "AU",
    "canada": "CA", "brazil": "BR", "mexico": "MX", "thailand": "TH",
    "indonesia": "ID", "vietnam": "VN", "nepal": "NP", "sri lanka": "LK",
    "malaysia": "MY", "singapore": "SG", "philippines": "PH",
}

# Aliases for cities/states the API indexes under a different spelling or wrong country.
# Key = any common variant (lowercased); value = the spelling the API recognises correctly.
_ALIASES: dict[str, str] = {
    # Indian cities with wrong-country collisions
    "bangalore":    "Bengaluru",
    "bengalore":    "Bengaluru",
    "bombay":       "Mumbai",
    "calcutta":     "Kolkata",
    "madras":       "Chennai",
    "mysore":       "Mysuru",
    "pondicherry":  "Puducherry",
    "varanasi":     "Varanasi",   # correct but keep for safety
    "benares":      "Varanasi",
    "allahabad":    "Prayagraj",
    "poona":        "Pune",
    "baroda":       "Vadodara",
    "cochin":       "Kochi",
    "calicut":      "Kozhikode",
    "trivandrum":   "Thiruvananthapuram",
    "trichur":      "Thrissur",
    "mangalore":    "Mangaluru",
    "hubli":        "Hubballi",
    "belgaum":      "Belagavi",
    "gulbarga":     "Kalaburagi",
    "bijapur":      "Vijayapura",
    # Indian states (not cities — map to capital)
    "goa":          "Madgaon",
    "kerala":       "Thiruvananthapuram",
    "rajasthan":    "Jaipur",
    "himachal":     "Shimla",
    "uttarakhand":  "Dehradun",
    "kashmir":      "Srinagar",
    "sikkim":       "Gangtok",
    "meghalaya":    "Shillong",
    "coorg":        "Madikeri",
    "kodagu":       "Madikeri",
    "wayanad":      "Kalpetta",
    "munnar":       "Munnar",    # keep; just ensure India filter applies
    "ooty":         "Udhagamandalam",
    "kodaikanal":   "Kodaikanal",
}


# All keys in _ALIASES that represent Indian locations — force IN country filter
_INDIAN_ALIASES: frozenset[str] = frozenset(_ALIASES)  # all current aliases are Indian


def _parse_query(name: str) -> tuple[str, str | None]:
    """Return (city_part, iso2_code_or_None) parsed from 'City, Country'."""
    parts = [p.strip() for p in name.split(",")]
    city = parts[0]
    country_code: str | None = None
    if len(parts) > 1:
        suffix = parts[-1].lower()
        country_code = _COUNTRY_CODES.get(suffix)
    # If no explicit country but the city is a known Indian alias, infer India
    if country_code is None and city.lower() in _INDIAN_ALIASES:
        country_code = "IN"
    return city, country_code


def _build_queries(name: str, city: str) -> list[str]:
    """Ordered candidate queries — apply alias first, then original city name."""
    alias = _ALIASES.get(city.lower())
    candidates: list[str] = []
    if alias:
        candidates.append(alias)
    candidates.append(city)
    return list(dict.fromkeys(candidates))


def resolve_location(name: str) -> dict:
    """Convert a place name to geographic coordinates and metadata."""
    if not name or not name.strip():
        return {"status": "error", "message": "Place name cannot be empty"}

    city, wanted_cc = _parse_query(name)

    for query in _build_queries(name, city):
        try:
            resp = httpx.get(
                _URL,
                params={"name": query, "count": 10, "language": "en", "format": "json"},
                timeout=10.0,
            )
            resp.raise_for_status()
            results = resp.json().get("results") or []
            if not results:
                continue

            # Prefer results matching the desired country
            if wanted_cc:
                matching = [r for r in results if r.get("country_code") == wanted_cc]
                if matching:
                    results = matching + [r for r in results if r.get("country_code") != wanted_cc]

            hits = [
                {
                    "name":         r.get("name"),
                    "lat":          r.get("latitude"),
                    "lon":          r.get("longitude"),
                    "country":      r.get("country"),
                    "country_code": r.get("country_code"),
                    "state":        r.get("admin1"),
                    "timezone":     r.get("timezone"),
                    "population":   r.get("population"),
                }
                for r in results[:3]
            ]
            best = hits[0]
            return {
                "status":       "ok",
                "query":        name,
                **best,
                "alternatives": hits[1:],
            }
        except httpx.HTTPStatusError as exc:
            return {"status": "error", "message": f"HTTP {exc.response.status_code}"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    return {"status": "error", "message": f"No location found for '{name}'"}
