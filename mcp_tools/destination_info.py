"""
get_destination_info — Wikipedia REST API (free, no key required).
Returns a factual summary of a destination: geography, culture, highlights.
"""
from __future__ import annotations
import httpx

_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"


def _wiki_fetch(title: str) -> httpx.Response | None:
    headers = {"Accept": "application/json", "User-Agent": "TripMind/2.0"}
    try:
        r = httpx.get(_URL.format(title=title), headers=headers, timeout=10.0, follow_redirects=True)
        if r.status_code == 200:
            return r
    except Exception:
        pass
    return None


def get_destination_info(name: str) -> dict:
    """Fetch Wikipedia summary for a destination."""
    if not name or not name.strip():
        return {"status": "error", "message": "Destination name cannot be empty"}
    try:
        # Build candidate Wikipedia titles to try in order
        cleaned = name.strip()
        city_part = cleaned.split(",")[0].strip()   # "Goa, India" → "Goa"
        first_word = cleaned.split()[0]             # "Tokyo Japan" → "Tokyo"
        candidates = [
            cleaned.replace(" ", "_"),              # exact title attempt
            city_part.replace(" ", "_"),             # strip country after comma
            first_word,                              # just first word (fallback for "City Country")
            f"{city_part.replace(' ', '_')}_(city)",
        ]

        resp = None
        for title in dict.fromkeys(candidates):
            resp = _wiki_fetch(title)
            if resp:
                break

        if resp is None:
            return {"status": "error", "message": f"No Wikipedia page for '{name}'"}

        resp.raise_for_status()
        d = resp.json()

        return {
            "status":       "ok",
            "title":        d.get("title"),
            "description":  d.get("description"),
            "extract":      (d.get("extract") or "")[:1200],
            "coordinates":  d.get("coordinates"),
            "thumbnail":    (d.get("thumbnail") or {}).get("source"),
            "url":          (d.get("content_urls") or {}).get("desktop", {}).get("page"),
        }
    except httpx.HTTPStatusError as exc:
        return {"status": "error", "message": f"HTTP {exc.response.status_code}"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
