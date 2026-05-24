"""
get_local_cuisine — TheMealDB API (free, no key required).
Returns traditional dish recommendations for a cuisine area/country.
"""
from __future__ import annotations
import httpx

_BASE = "https://www.themealdb.com/api/json/v1/1"

# Map varied input → TheMealDB area names
_AREA_MAP: dict[str, str] = {
    "india": "Indian", "indian": "Indian",
    "goa": "Indian", "kerala": "Indian", "rajasthan": "Indian",
    "france": "French", "french": "French",
    "italy": "Italian", "italian": "Italian",
    "japan": "Japanese", "japanese": "Japanese",
    "china": "Chinese", "chinese": "Chinese",
    "thailand": "Thai", "thai": "Thai",
    "mexico": "Mexican", "mexican": "Mexican",
    "greece": "Greek", "greek": "Greek",
    "spain": "Spanish", "spanish": "Spanish",
    "turkey": "Turkish", "turkish": "Turkish",
    "vietnam": "Vietnamese", "vietnamese": "Vietnamese",
    "usa": "American", "american": "American",
    "uk": "British", "british": "British", "england": "British",
    "morocco": "Moroccan", "moroccan": "Moroccan",
    "egypt": "Egyptian", "egyptian": "Egyptian",
    "malaysia": "Malaysian", "malaysian": "Malaysian",
    "philippines": "Filipino", "filipino": "Filipino",
    "poland": "Polish", "polish": "Polish",
    "portugal": "Portuguese", "portuguese": "Portuguese",
    "russia": "Russian", "russian": "Russian",
    "canada": "Canadian", "canadian": "Canadian",
    "croatia": "Croatian", "ireland": "Irish", "irish": "Irish",
    "dutch": "Dutch", "netherlands": "Dutch",
    "ukraine": "Ukrainian",
    "jamaica": "Jamaican", "jamaican": "Jamaican",
    "kenya": "Kenyan",
    "indonesia": "Indonesian", "indonesian": "Indonesian",
    "bali": "Indonesian",
    "nepal": "Nepalese", "nepalese": "Nepalese",
    "sri lanka": "Sri Lankan", "srilanka": "Sri Lankan",
}

# Keyword fallback for areas where TheMealDB's area filter returns null on the free tier
_KEYWORD_FALLBACK: dict[str, list[str]] = {
    "Indian":     ["biryani", "curry", "dal", "samosa", "tikka"],
    "French":     ["crepe", "ratatouille", "quiche"],
    "Greek":      ["moussaka", "souvlaki", "spanakopita"],
    "Vietnamese": ["pho", "banh mi", "spring roll"],
    "Indonesian": ["rendang", "nasi goreng", "satay"],
    "Nepalese":   ["momo", "dal bhat", "thukpa"],
    "Sri Lankan": ["curry", "kottu", "hoppers"],
}


def _fetch_by_keyword(keywords: list[str], limit: int) -> list[dict]:
    dishes: list[dict] = []
    seen: set[str] = set()
    for kw in keywords:
        if len(dishes) >= limit:
            break
        try:
            r = httpx.get(f"{_BASE}/search.php", params={"s": kw}, timeout=10.0)
            r.raise_for_status()
            for raw in (r.json().get("meals") or []):
                if raw["idMeal"] in seen:
                    continue
                seen.add(raw["idMeal"])
                ingredients = [
                    raw[f"strIngredient{i}"]
                    for i in range(1, 16)
                    if (raw.get(f"strIngredient{i}") or "").strip()
                ]
                dishes.append({
                    "dish":            raw.get("strMeal"),
                    "category":        raw.get("strCategory"),
                    "description":     (raw.get("strInstructions") or "")[:250].strip() + "…",
                    "key_ingredients": ingredients[:8],
                    "image":           raw.get("strMealThumb"),
                    "video":           raw.get("strYoutube") or None,
                })
                if len(dishes) >= limit:
                    break
        except Exception:
            continue
    return dishes


def get_local_cuisine(area: str, limit: int = 6) -> dict:
    """Fetch traditional dish recommendations for a region/country."""
    # Strip country suffix ("Goa, India" → "goa") for alias lookup
    city_part   = area.split(",")[0].lower().strip()
    normalized  = area.lower().strip()
    mealdb_area = _AREA_MAP.get(normalized) or _AREA_MAP.get(city_part) or area.title()

    try:
        # Try area filter first
        list_resp = httpx.get(f"{_BASE}/filter.php", params={"a": mealdb_area}, timeout=10.0)
        list_resp.raise_for_status()
        meals = list_resp.json().get("meals") or []

        if meals:
            dishes = []
            for m in meals[:limit]:
                detail_resp = httpx.get(f"{_BASE}/lookup.php", params={"i": m["idMeal"]}, timeout=8.0)
                detail_resp.raise_for_status()
                raw = (detail_resp.json().get("meals") or [None])[0]
                if not raw:
                    continue
                ingredients = [
                    raw[f"strIngredient{i}"]
                    for i in range(1, 16)
                    if (raw.get(f"strIngredient{i}") or "").strip()
                ]
                dishes.append({
                    "dish":            raw.get("strMeal"),
                    "category":        raw.get("strCategory"),
                    "description":     (raw.get("strInstructions") or "")[:250].strip() + "…",
                    "key_ingredients": ingredients[:8],
                    "image":           raw.get("strMealThumb"),
                    "video":           raw.get("strYoutube") or None,
                })
            return {
                "status":       "ok",
                "area":         mealdb_area,
                "total_in_db":  len(meals),
                "dishes":       dishes,
                "note": f"Showing {len(dishes)} of {len(meals)} traditional {mealdb_area} dishes.",
            }

        # Area filter returned nothing — try keyword search fallback
        fallback_kws = _KEYWORD_FALLBACK.get(mealdb_area)
        if fallback_kws:
            dishes = _fetch_by_keyword(fallback_kws, limit)
            if dishes:
                return {
                    "status":      "ok",
                    "area":        mealdb_area,
                    "total_in_db": len(dishes),
                    "dishes":      dishes,
                    "note":        f"Results sourced via keyword search for {mealdb_area} cuisine.",
                }

        return {
            "status":  "error",
            "message": (
                f"No cuisine data found for '{area}' (tried '{mealdb_area}'). "
                "Use a country or cuisine name like 'Italian', 'Japanese', 'Thai'."
            ),
        }
    except httpx.HTTPStatusError as exc:
        return {"status": "error", "message": f"HTTP {exc.response.status_code}"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
