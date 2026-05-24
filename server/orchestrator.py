"""
TripMind Orchestrator — multi-turn agent reasoning loop.

Pattern (FinDecide-inspired):
  1. Call LLM with accumulated message history
  2. Strip markdown, extract JSON
  3. Validate against Pydantic schemas  (parse_llm_response)
  4. If FUNCTION_CALL → dispatch tool → inject result as user message
  5. Loop until FINAL_ANSWER, error, or max_steps

Supports three LLM backends via LLM_PROVIDER env var:
  external — LLM Gateway at EXTERNAL_BASE_URL  (default)
  ollama   — local Ollama at OLLAMA_BASE_URL
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Iterator, Optional

import httpx
from json_repair import repair_json

# Resolve imports whether run as package or from project root
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from server.schemas import parse_llm_response, FunctionCall, FinalAnswer, ReasoningStep, SelfCheck
from mcp_tools import dispatch_tool
from prompts.trip_planner import SYSTEM_PROMPT

# ── Continuation messages injected after each non-terminal schema ─────────────
_CONTINUE: dict[str, str] = {
    "REASONING_STEP": (
        "Reasoning step recorded. Continue with the next step or make a tool call."
    ),
    "SELF_CHECK": (
        "Self-check recorded. "
        "If passed=true on all criteria, emit FINAL_ANSWER. "
        "If passed=false, emit a corrective REASONING_STEP first."
    ),
    "PARSE_ERROR": (
        "Your previous response could not be parsed or failed schema validation. "
        "Emit a single JSON object matching exactly one of: "
        "REASONING_STEP, FUNCTION_CALL, SELF_CHECK, or FINAL_ANSWER. "
        "No text outside the JSON object."
    ),
}


# ── JSON extraction ────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """
    Robustly extract the first JSON object from LLM output.
    Handles markdown fences, leading prose, unescaped newlines in strings,
    missing commas, and other common LLM JSON formatting errors.
    """
    if not text:
        raise ValueError("Empty LLM response")

    # Strip ```json ... ``` fences
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip()
    cleaned = re.sub(r"```\s*$", "", cleaned, flags=re.MULTILINE).strip()

    # Fast path: entire response is valid JSON
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Brace-matching extraction (handles leading prose)
    start = cleaned.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in response: {text[:300]!r}")

    depth, in_str, escape = 0, False, False
    candidate = None
    for i, ch in enumerate(cleaned[start:], start):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_str:
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = cleaned[start : i + 1]
                break

    if candidate is None:
        candidate = cleaned[start:]

    # Try strict parse first
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # Fall back to json_repair — handles unescaped newlines, trailing commas,
    # missing delimiters, and other LLM-generated JSON quirks
    try:
        repaired = repair_json(candidate, return_objects=True)
        if isinstance(repaired, dict):
            return repaired
        raise ValueError(f"Repaired JSON is not an object: {type(repaired)}")
    except Exception as exc:
        raise ValueError(f"JSON repair failed: {exc}") from exc


# ── LLM backends ───────────────────────────────────────────────────────────────

def _call_llm(
    messages: list[dict],
    *,
    provider: Optional[str] = None,
    model: Optional[str]    = None,
    max_tokens: int  = 8192,
    temperature: float = 0.15,
) -> str:
    """
    Call the configured LLM backend and return raw response text.

    Temperature 0.15 keeps JSON output deterministic while allowing enough
    flexibility for long-chain reasoning.
    """
    backend = os.getenv("LLM_PROVIDER", "external").lower()

    if backend == "ollama":
        url          = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        ollama_model = model or os.getenv("OLLAMA_MODEL", "llama3.2")
        payload = {
            "model":   ollama_model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            "stream":  False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        resp = httpx.post(f"{url}/api/chat", json=payload, timeout=300.0)
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")

    else:  # external gateway
        url = os.getenv("EXTERNAL_BASE_URL", "http://localhost:8100")
        payload = {
            "messages":    messages,
            "system":      SYSTEM_PROMPT,
            "provider":    provider,
            "model":       model,
            "max_tokens":  max_tokens,
            "temperature": temperature,
        }
        resp = httpx.post(f"{url}/v1/chat", json=payload, timeout=180.0)
        resp.raise_for_status()
        return resp.json().get("text", "")


# ── Agent loop ─────────────────────────────────────────────────────────────────

def agent_steps(
    user_query: str,
    history: Optional[list] = None,
    *,
    provider: Optional[str] = None,
    model:    Optional[str] = None,
    max_steps: int = 18,
) -> Iterator[dict]:
    """
    Sync generator — yields one event dict per agent turn.

    Event shapes
    ────────────
    {"event": "step",        "schema": str,      "data": dict}
    {"event": "tool_result", "tool_name": str,   "result": dict}
    {"event": "error",       "message": str,     "recoverable": bool}
    {"event": "end",         "reason": "final_answer"|"max_steps"|"error"}
    """
    messages: list[dict] = list(history or [])
    messages.append({"role": "user", "content": user_query})

    consecutive_errors        = 0
    tool_calls_made           = 0      # total successful tool dispatches
    has_analysis              = False  # REASONING_STEP(analysis/synthesis/…) after tools
    has_self_check            = False  # any SELF_CHECK emitted
    awaiting_post_tool_reason = False  # gate: must reason before next tool call

    _ANALYSIS_TYPES = {"analysis", "synthesis", "arithmetic", "constraint_check", "lookup"}

    for _turn in range(max_steps):

        # ── 1. LLM call ────────────────────────────────────────────────────────
        try:
            raw = _call_llm(messages, provider=provider, model=model)
        except Exception as exc:
            yield {"event": "error", "message": f"LLM call failed: {exc}", "recoverable": False}
            yield {"event": "end",   "reason": "error"}
            return

        # ── 2. JSON extraction ─────────────────────────────────────────────────
        try:
            data = _extract_json(raw)
        except ValueError as exc:
            consecutive_errors += 1
            yield {
                "event":       "error",
                "message":     f"JSON parse failed (attempt {consecutive_errors}/3): {exc}",
                "recoverable": True,
            }
            if consecutive_errors >= 3:
                yield {"event": "end", "reason": "error"}
                return
            messages.append({"role": "assistant", "content": raw or "(empty)"})
            messages.append({"role": "user",      "content": _CONTINUE["PARSE_ERROR"]})
            continue

        # ── 3. Pydantic validation ─────────────────────────────────────────────
        try:
            response = parse_llm_response(data)
        except Exception as exc:
            consecutive_errors += 1
            yield {
                "event":       "error",
                "message":     f"Schema validation failed (attempt {consecutive_errors}/3): {exc}",
                "recoverable": True,
            }
            if consecutive_errors >= 3:
                yield {"event": "end", "reason": "error"}
                return
            messages.append({"role": "assistant", "content": json.dumps(data)})
            messages.append({"role": "user",      "content": _CONTINUE["PARSE_ERROR"]})
            continue

        consecutive_errors = 0  # reset on successful parse

        # ── 4. Emit step event ─────────────────────────────────────────────────
        schema = response.type
        yield {"event": "step", "schema": schema, "data": response.model_dump()}

        # ── 5. Handle response type ────────────────────────────────────────────
        if isinstance(response, FunctionCall):

            # Gate: block tool call if a post-tool reasoning step is still owed
            if awaiting_post_tool_reason:
                messages.append({
                    "role": "assistant",
                    "content": json.dumps(response.model_dump(), ensure_ascii=False),
                })
                messages.append({
                    "role": "user",
                    "content": (
                        "STOP — you must interpret the previous tool result before "
                        "calling another tool. Emit a REASONING_STEP now "
                        "(reasoning_type='lookup' or 'analysis') that explains what "
                        "you learned from the last result and what you will do next."
                    ),
                })
                continue

            tool_calls_made += 1
            tool_result = dispatch_tool(response.tool_name, response.arguments)
            yield {
                "event":     "tool_result",
                "tool_name": response.tool_name,
                "result":    tool_result,
            }
            messages.append({
                "role":    "assistant",
                "content": json.dumps(response.model_dump(), ensure_ascii=False),
            })
            awaiting_post_tool_reason = True  # require reasoning before next tool

            # After compute_budget (last data tool): hard directive to analyse
            if response.tool_name == "compute_budget":
                messages.append({
                    "role": "user",
                    "content": (
                        f"TOOL_RESULT for compute_budget:\n"
                        + json.dumps(tool_result, indent=2, ensure_ascii=False)
                        + "\n\n"
                        "═══ DATA GATHERING COMPLETE ═══\n"
                        "Your ONLY valid next response is a REASONING_STEP with "
                        "reasoning_type='analysis'. DO NOT call more tools. "
                        "DO NOT emit FINAL_ANSWER yet.\n\n"
                        "In your thought, answer ALL of these:\n"
                        "1. Which hotel best fits the budget and party size?\n"
                        "2. Which attractions go on which day?\n"
                        "3. Does weather affect any activity?\n"
                        "4. Confirm the cost assumptions from your pre-budget "
                        "reasoning step: were the figures (accommodation proxy, "
                        "transport estimate, food rate) reasonable given the "
                        "compute_budget result? Flag any that look off.\n"
                        "5. Budget arithmetic: accommodation + transport + food "
                        "+ activities + 15% buffer = total. Does it fit?\n"
                        "6. Draft day-by-day titles and activity list.\n"
                        "Then emit SELF_CHECK, then FINAL_ANSWER."
                    ),
                })
            else:
                messages.append({
                    "role": "user",
                    "content": (
                        f"TOOL_RESULT for {response.tool_name}:\n"
                        + json.dumps(tool_result, indent=2, ensure_ascii=False)
                        + "\n\nYour NEXT response MUST be a REASONING_STEP "
                        "(reasoning_type='lookup' or 'analysis') to interpret this "
                        "result before calling any more tools. Explain what you found "
                        "and what it means for the plan. "
                        "REMINDER: after all tools, you MUST also emit "
                        "REASONING_STEP (analysis) then SELF_CHECK before FINAL_ANSWER."
                    ),
                })

        elif isinstance(response, FinalAnswer):
            # Guard: block premature FINAL_ANSWER if analysis or self-check missing
            missing = []
            if tool_calls_made > 0 and not has_analysis:
                missing.append("REASONING_STEP with reasoning_type='analysis'")
            if tool_calls_made > 0 and not has_self_check:
                missing.append("SELF_CHECK")
            if missing:
                messages.append({
                    "role": "assistant",
                    "content": json.dumps(response.model_dump(), ensure_ascii=False),
                })
                messages.append({
                    "role": "user",
                    "content": (
                        "STOP — you skipped mandatory reasoning steps. "
                        f"Before FINAL_ANSWER you must emit: {', '.join(missing)}. "
                        "Emit the first missing step now, then continue the sequence."
                    ),
                })
                continue  # loop again without yielding FINAL_ANSWER
            yield {"event": "end", "reason": "final_answer"}
            return

        elif isinstance(response, SelfCheck):
            has_self_check = True
            messages.append({
                "role":    "assistant",
                "content": json.dumps(response.model_dump(), ensure_ascii=False),
            })
            messages.append({
                "role":    "user",
                "content": _CONTINUE["SELF_CHECK"],
            })

        else:  # REASONING_STEP
            if isinstance(response, ReasoningStep):
                awaiting_post_tool_reason = False   # satisfied the post-tool gate
                if tool_calls_made > 0 and response.reasoning_type in _ANALYSIS_TYPES:
                    has_analysis = True
            messages.append({
                "role":    "assistant",
                "content": json.dumps(response.model_dump(), ensure_ascii=False),
            })
            messages.append({
                "role":    "user",
                "content": _CONTINUE.get(schema, _CONTINUE["REASONING_STEP"]),
            })

    # Exhausted max_steps without FINAL_ANSWER
    yield {
        "event":   "error",
        "message": f"Agent reached max_steps ({max_steps}) without producing FINAL_ANSWER.",
        "recoverable": False,
    }
    yield {"event": "end", "reason": "max_steps"}
