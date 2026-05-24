"""
TripMind MCP Server — stdio transport.

Exposes all 10 trip-planning tools over the Model Context Protocol.
Can be used with Claude Desktop or any MCP-compatible client.

Run:  uv run python -m mcp_tools.server
      or:  uv run mcp run mcp_tools/server.py
"""
from __future__ import annotations
import asyncio
import json

from mcp.server       import Server
from mcp.server.stdio import stdio_server
from mcp.types        import Tool, TextContent

from . import dispatch_tool

server = Server("tripmind-tools")

# ── Tool schema registry ──────────────────────────────────────────────────────
_SCHEMAS: dict[str, dict] = {
    "resolve_location": {
        "description": (
            "Convert a city or place name to geographic coordinates (lat/lon). "
            "MUST be called before any tool that requires lat/lon."
        ),
        "properties": {
            "name": {"type": "string", "description": "Place name, e.g. 'Nandi Hills' or 'Mysore'"},
        },
        "required": ["name"],
    },
    "get_weather": {
        "description": "Get a 1–7 day daily weather forecast for a location by coordinates.",
        "properties": {
            "lat":  {"type": "number"},
            "lon":  {"type": "number"},
            "days": {"type": "integer", "default": 5, "description": "Forecast horizon (1–7)"},
        },
        "required": ["lat", "lon"],
    },
    "get_destination_info": {
        "description": "Fetch a Wikipedia summary of a destination: geography, culture, key facts.",
        "properties": {
            "name": {"type": "string", "description": "Destination name"},
        },
        "required": ["name"],
    },
    "search_attractions": {
        "description": (
            "Find tourist POIs near a location — temples, viewpoints, museums, nature, "
            "heritage sites, beaches, parks."
        ),
        "properties": {
            "lat":      {"type": "number"},
            "lon":      {"type": "number"},
            "radius_m": {"type": "integer", "default": 10000, "description": "Search radius in metres"},
            "kinds": {
                "type": "string",
                "default": "interesting_places",
                "description": (
                    "Category filter: interesting_places | natural | historic | cultural | "
                    "museums | religion | architecture | beaches | viewpoints | parks | heritage"
                ),
            },
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["lat", "lon"],
    },
    "get_attraction_details": {
        "description": "Get detailed info (description, address, opening hours) for a specific POI by its OpenTripMap XID.",
        "properties": {
            "xid": {"type": "string", "description": "OpenTripMap XID from search_attractions result"},
        },
        "required": ["xid"],
    },
    "get_local_cuisine": {
        "description": (
            "Get traditional dish recommendations for a cuisine area or country. "
            "Use the country of the destination."
        ),
        "properties": {
            "area":  {"type": "string", "description": "Cuisine area, e.g. 'Indian', 'Italian', 'Japanese'"},
            "limit": {"type": "integer", "default": 6},
        },
        "required": ["area"],
    },
    "search_restaurants": {
        "description": "Find restaurants near a location filtered by cuisine type (Foursquare).",
        "properties": {
            "lat":       {"type": "number"},
            "lon":       {"type": "number"},
            "cuisine": {
                "type": "string",
                "default": "local",
                "description": (
                    "Cuisine type: indian | italian | chinese | japanese | thai | mexican | "
                    "french | mediterranean | seafood | vegetarian | cafe | street_food | local"
                ),
            },
            "radius_m":  {"type": "integer", "default": 5000},
            "limit":     {"type": "integer", "default": 10},
        },
        "required": ["lat", "lon"],
    },
    "get_route": {
        "description": (
            "Calculate driving/walking/cycling distance and travel time between two points (OSRM). "
            "Use to validate travel time constraints, e.g. ≤ 3.5 hrs for elderly travelers."
        ),
        "properties": {
            "origin_lat":  {"type": "number"},
            "origin_lon":  {"type": "number"},
            "dest_lat":    {"type": "number"},
            "dest_lon":    {"type": "number"},
            "mode": {
                "type": "string",
                "default": "driving",
                "description": "driving | walking | cycling",
            },
        },
        "required": ["origin_lat", "origin_lon", "dest_lat", "dest_lon"],
    },
    "search_hotels": {
        "description": "Search for hotel offers near a location using Amadeus Self-Service API.",
        "properties": {
            "lat":         {"type": "number"},
            "lon":         {"type": "number"},
            "checkin":     {"type": "string", "description": "YYYY-MM-DD"},
            "checkout":    {"type": "string", "description": "YYYY-MM-DD"},
            "adults":      {"type": "integer", "default": 2},
            "radius":      {"type": "integer", "default": 5, "description": "km"},
            "currency":    {"type": "string", "default": "INR"},
            "max_results": {"type": "integer", "default": 6},
        },
        "required": ["lat", "lon"],
    },
    "compute_budget": {
        "description": (
            "Calculate total trip budget: accommodation + transport + food + activities + buffer. "
            "MUST be called after collecting real costs from other tools."
        ),
        "properties": {
            "accommodation_cost": {"type": "number", "description": "Total accommodation (INR)"},
            "transport_cost":     {"type": "number", "description": "Total transport to/from destination (INR)"},
            "food_per_day":       {"type": "number", "description": "Daily food budget (INR)"},
            "days":               {"type": "integer"},
            "activities_budget":  {"type": "number", "default": 0},
            "buffer_pct":         {"type": "number", "default": 15, "description": "Contingency percentage"},
        },
        "required": ["accommodation_cost", "transport_cost", "food_per_day", "days"],
    },
}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name=name,
            description=schema["description"],
            inputSchema={
                "type":       "object",
                "properties": schema["properties"],
                "required":   schema.get("required", []),
            },
        )
        for name, schema in _SCHEMAS.items()
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    result = dispatch_tool(name, arguments)
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
