"""
Pydantic schemas for TripMind agent responses.

Every LLM turn must produce exactly one of four validated types:
  REASONING_STEP  — structured thinking before any action
  FUNCTION_CALL   — tool invocation with typed arguments
  SELF_CHECK      — verification of a prior claim
  FINAL_ANSWER    — complete, validated trip plan
"""
from __future__ import annotations

from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, Field, model_validator


# ─────────────────────────────────────────────────────────────────────────────
# Schema A — REASONING_STEP
# ─────────────────────────────────────────────────────────────────────────────

class ReasoningStep(BaseModel):
    type: Literal["REASONING_STEP"]
    step_number: int = Field(ge=1)
    reasoning_type: Literal[
        "decomposition", "assumption", "analysis",
        "arithmetic", "lookup", "constraint_check",
        "comparison", "validation", "synthesis",
    ]
    thought: str = Field(default="", min_length=0)
    next_action: Literal["TOOL_CALL", "SELF_CHECK", "REASONING_STEP", "FINAL_ANSWER"]


# ─────────────────────────────────────────────────────────────────────────────
# Schema B — FUNCTION_CALL
# ─────────────────────────────────────────────────────────────────────────────

class FunctionCall(BaseModel):
    type: Literal["FUNCTION_CALL"]
    step_number: int = Field(ge=1)
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    why_this_tool: str = Field(default="", min_length=0)
    expected_output: str = Field(default="", min_length=0)


# ─────────────────────────────────────────────────────────────────────────────
# Schema C — SELF_CHECK
# ─────────────────────────────────────────────────────────────────────────────

class SelfCheck(BaseModel):
    type: Literal["SELF_CHECK"]
    step_number: int = Field(ge=1)
    claim_being_checked: str = Field(min_length=10)
    verification_method: Literal[
        "constraint_review", "order_of_magnitude",
        "assumption_review", "cross_validation", "accessibility_check",
    ]
    passed: bool
    notes: str = Field(default="", min_length=0)


# ─────────────────────────────────────────────────────────────────────────────
# Schema D — FINAL_ANSWER
# ─────────────────────────────────────────────────────────────────────────────

class Activity(BaseModel):
    time: Optional[str] = None
    activity: str
    duration: Optional[str] = None
    cost_inr: int = Field(default=0, ge=0)
    accessibility: Optional[Literal["easy", "moderate", "difficult"]] = None
    tip: Optional[str] = None


class Meal(BaseModel):
    meal_type: Literal["Breakfast", "Lunch", "Dinner"]   # renamed from "meal" to avoid LLM confusion
    suggestion: str
    cuisine: Optional[str] = None
    est_cost_inr: int = Field(default=0, ge=0)


class ItineraryDay(BaseModel):
    day: int = Field(ge=1)
    title: str
    activities: list[Activity] = Field(default_factory=list)
    meals: list[Meal] = Field(default_factory=list)
    stay: Optional[str] = None
    transport_note: Optional[str] = None


class CostBreakdown(BaseModel):
    accommodation: int = Field(default=0, ge=0)
    transport: int = Field(default=0, ge=0)
    food: int = Field(default=0, ge=0)
    activities: int = Field(default=0, ge=0)
    buffer: int = Field(default=0, ge=0)
    total: int = Field(ge=0)
    within_budget: bool

    @model_validator(mode="after")
    def total_check(self) -> "CostBreakdown":
        expected = self.accommodation + self.transport + self.food + self.activities + self.buffer
        if abs(self.total - expected) > 500:
            raise ValueError(f"total ({self.total}) doesn't match component sum ({expected})")
        return self


class FinalAnswer(BaseModel):
    type: Literal["FINAL_ANSWER"]
    destination: str
    country: str
    confidence: Literal["high", "medium", "low"]
    weather_summary: str
    itinerary: list[ItineraryDay] = Field(default_factory=list)
    cost_breakdown: CostBreakdown
    key_assumptions: list[str] = Field(default_factory=list)
    travel_tips: list[str] = Field(default_factory=list)
    local_cuisine_highlights: list[str] = Field(default_factory=list)
    top_attractions: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    fallback_advice: str = Field(default="Check local travel agents for alternatives.")


# ─────────────────────────────────────────────────────────────────────────────
# Union + dispatcher
# ─────────────────────────────────────────────────────────────────────────────

LLMResponse = Union[ReasoningStep, FunctionCall, SelfCheck, FinalAnswer]

_TYPE_MAP: dict[str, type] = {
    "REASONING_STEP": ReasoningStep,
    "FUNCTION_CALL":  FunctionCall,
    "SELF_CHECK":     SelfCheck,
    "FINAL_ANSWER":   FinalAnswer,
}


def parse_llm_response(data: dict) -> LLMResponse:
    t = data.get("type")
    cls = _TYPE_MAP.get(t)
    if cls is None:
        raise ValueError(f"Unknown response type: {t!r}. Must be one of: {list(_TYPE_MAP)}")
    return cls.model_validate(data)
