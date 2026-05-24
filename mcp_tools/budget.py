"""
compute_budget — local calculation, no API required.
Aggregates all trip costs with configurable buffer percentage.
"""
from __future__ import annotations


def compute_budget(
    accommodation_cost: float,
    transport_cost: float,
    food_per_day: float,
    days: int,
    activities_budget: float = 0.0,
    buffer_pct: float = 15.0,
) -> dict:
    """
    Calculate full trip budget with itemised breakdown and buffer.

    All costs in INR. food_per_day * days = total food cost.
    buffer_pct adds a contingency on top of the subtotal.
    """
    if days <= 0:
        return {"status": "error", "message": "days must be ≥ 1"}
    if buffer_pct < 0 or buffer_pct > 50:
        return {"status": "error", "message": "buffer_pct must be between 0 and 50"}

    food     = round(food_per_day * days)
    subtotal = accommodation_cost + transport_cost + food + activities_budget
    buffer   = round(subtotal * buffer_pct / 100)
    total    = round(subtotal + buffer)

    return {
        "status": "ok",
        "breakdown": {
            "accommodation": round(accommodation_cost),
            "transport":     round(transport_cost),
            "food":          food,
            "activities":    round(activities_budget),
            "subtotal":      round(subtotal),
            f"buffer_{int(buffer_pct)}pct": buffer,
            "total":         total,
        },
        "total": total,
        "formula": (
            f"₹{accommodation_cost:.0f} stay + ₹{transport_cost:.0f} transport + "
            f"₹{food_per_day:.0f}×{days}d food + ₹{activities_budget:.0f} activities "
            f"+ {buffer_pct:.0f}% buffer = ₹{total:,}"
        ),
    }
