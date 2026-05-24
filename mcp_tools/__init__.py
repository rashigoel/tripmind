"""
TripMind MCP Tools — in-process dispatcher.

All tools are callable directly via dispatch_tool(name, arguments).
The server.py in this package exposes them over MCP stdio for Claude Desktop.
"""
from __future__ import annotations

from .geocoding        import resolve_location
from .weather          import get_weather
from .destination_info import get_destination_info
from .attractions      import search_attractions, get_attraction_details
from .cuisine          import get_local_cuisine
from .restaurants      import search_restaurants
from .transport        import get_route
from .hotels           import search_hotels
from .budget           import compute_budget

TOOL_MAP: dict[str, callable] = {
    "resolve_location":     resolve_location,
    "get_weather":          get_weather,
    "get_destination_info": get_destination_info,
    "search_attractions":   search_attractions,
    "get_attraction_details": get_attraction_details,
    "get_local_cuisine":    get_local_cuisine,
    "search_restaurants":   search_restaurants,
    "get_route":            get_route,
    "search_hotels":        search_hotels,
    "compute_budget":       compute_budget,
}


def dispatch_tool(tool_name: str, arguments: dict) -> dict:
    """
    Dispatch a tool call by name with keyword arguments.
    Returns a dict with at minimum {"status": "ok"|"error"}.
    """
    fn = TOOL_MAP.get(tool_name)
    if fn is None:
        return {
            "status":    "error",
            "message":   f"Unknown tool '{tool_name}'.",
            "available": list(TOOL_MAP),
        }
    try:
        return fn(**arguments)
    except TypeError as exc:
        return {"status": "error", "message": f"Bad arguments for '{tool_name}': {exc}"}
    except Exception as exc:
        return {"status": "error", "message": f"Tool runtime error: {exc}"}
