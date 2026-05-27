# TripMind v2 — AI Trip Planner

> Real-time travel planning powered by structured LLM reasoning, live tool data, and Pydantic-validated agent steps.

---

## Demo 
https://youtu.be/w4Qr3s0Li9g

## Prompt Evaluation

The system prompt was assessed against a structured reasoning rubric for LLM agents.

```json
{
  "explicit_reasoning":       true,
  "structured_output":        true,
  "tool_separation":          true,
  "conversation_loop":        true,
  "instructional_framing":    true,
  "internal_self_checks":     true,
  "reasoning_type_awareness": true,
  "fallbacks":                true,
  "overall_clarity": "Excellent — phased reasoning sequence, 7-type reasoning taxonomy, mandatory self-check, comprehensive fallback rules for tool failures, budget misses, ambiguous data, accessibility and weather constraints."
}
```

**All 9 criteria pass.** Key design decisions that earned each score:

| Criterion | Implementation |
|-----------|---------------|
| Explicit reasoning | `THINK STEP BY STEP BEFORE ACTING` at top; R7: every tool call requires a preceding `REASONING_STEP` |
| Structured output | 4 strict JSON schemas (A–D); no text allowed outside the object |
| Tool separation | 5 named phases: Understand → Gather → Analyse → Validate → Deliver |
| Conversation loop | `MULTI-TURN CONTEXT` section; agent reads injected `TOOL_RESULT` messages before next step |
| Instructional framing | Full example sequence with real JSON showing exact schema alternation |
| Internal self-checks | Phase 4: mandatory `SELF_CHECK` with 4 sub-checks; corrective reasoning step on failure |
| Reasoning type awareness | 7-value `reasoning_type` enum: `decomposition`, `assumption`, `analysis`, `arithmetic`, `lookup`, `constraint_check`, `synthesis` |
| Fallbacks | F1–F5 rules: tool errors, budget miss, ambiguous data, accessibility limits, weather substitution |
| Overall clarity | Phased sequence with step numbers; rules R1–R9; hotel price proxy; ≤16 step hard cap |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Browser (index.html)                         │
│                                                                       │
│  ┌──────────────────────┐      ┌────────────────────────────────┐   │
│  │   Chat Panel          │      │   Agent Reasoning Drawer        │   │
│  │  • User messages      │      │  • Compact timeline (32px/step) │   │
│  │  • Final answer card  │      │  • Click to expand step detail  │   │
│  │    (tabbed: Itinerary │      │  • Live badge + step counter    │   │
│  │     Budget, Cuisine,  │      │  • Auto-opens on stream start   │   │
│  │     Tips)             │      └────────────────────────────────┘   │
│  └──────────────────────┘                                             │
│              │  POST /chat (SSE stream)                               │
└──────────────┼──────────────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────────┐
│                    FastAPI Server  (server/api.py)                    │
│                                                                       │
│  GET  /           → web/index.html                                   │
│  GET  /health     → backend status + tool list                       │
│  GET  /providers  → LLM provider list for UI dropdown                │
│  POST /chat       → SSE stream (worker thread + asyncio.Queue)       │
│                                                                       │
│  Worker thread calls agent_steps() generator synchronously.          │
│  asyncio.Queue bridges sync generator → async SSE stream.            │
│  threading.Event cancels worker on client disconnect.                 │
└──────────────┬──────────────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────────┐
│               Agent Loop  (server/orchestrator.py)                   │
│                                                                       │
│  for turn in range(max_steps=18):                                    │
│    1. _call_llm(messages)          → raw text                        │
│    2. _extract_json(raw)           → dict  (json_repair fallback)    │
│    3. parse_llm_response(data)     → validated Pydantic model        │
│    4a. FUNCTION_CALL  → dispatch_tool() → inject TOOL_RESULT         │
│    4b. FINAL_ANSWER   → yield end event, return                      │
│    4c. REASONING_STEP / SELF_CHECK → inject continue prompt          │
│                                                                       │
│  JSON repair: json_repair lib fixes unescaped newlines,              │
│  trailing commas, missing delimiters before Pydantic validation.     │
└──────────────┬──────────────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────────┐
│              MCP Tools  (mcp_tools/)  — in-process dispatch          │
│                                                                       │
│  resolve_location   → Open-Meteo Geocoding API   (free, no key)     │
│  get_weather        → Open-Meteo Weather API     (free, no key)     │
│  search_attractions → OpenTripMap API            (free tier)         │
│  search_hotels      → OpenTripMap (accomodations kind)               │
│  get_local_cuisine  → TheMealDB API              (free, no key)     │
│  search_restaurants → OpenStreetMap Overpass     (free, no key)     │
│  get_route          → Open-Meteo / OSRM          (free, no key)     │
│  compute_budget     → pure Python arithmetic                         │
│  get_destination_info → Wikipedia REST API       (free, no key)     │
│                                                                       │
│  dispatch_tool(name, arguments) — single entry point used by loop   │
└─────────────────────────────────────────────────────────────────────┘
```

### LLM Backends

```
LLM_PROVIDER=external  →  LLM Gateway at EXTERNAL_BASE_URL
                           POST /v1/chat  { messages, system, model, max_tokens }

LLM_PROVIDER=ollama    →  Ollama at OLLAMA_BASE_URL
                           POST /api/chat  { model, messages, stream:false }
```

---

## Pydantic Schemas

All LLM output is validated by `server/schemas.py` before any action is taken.
The agent **must** emit exactly one of four schema types per turn.

### Schema A — `ReasoningStep`

Emitted before every tool call, after every tool result, and before the final answer. The `reasoning_type` field steers the LLM toward the correct cognitive mode for each phase.

```python
class ReasoningStep(BaseModel):
    type:           Literal["REASONING_STEP"]
    step_number:    int                          # ge=1
    reasoning_type: Literal[
        "decomposition",    # break down the user request into sub-problems
        "assumption",       # state what is being assumed and why
        "analysis",         # interpret tool results; pick best options
        "arithmetic",       # budget math / cost estimates step-by-step
        "lookup",           # interpret a single tool result; decide next tool
        "constraint_check", # verify a rule (budget limit, day count, etc.)
        "comparison",       # compare two or more options
        "validation",       # verify a prior claim or plan detail
        "synthesis",        # pull all findings into a coherent plan
    ]
    thought:        str = ""                     # free-form reasoning text
    next_action:    Literal["TOOL_CALL", "SELF_CHECK", "REASONING_STEP", "FINAL_ANSWER"]
```

### Schema B — `FunctionCall`

Tool invocation with typed arguments. Dispatched to `mcp_tools.dispatch_tool()`. Metadata fields are optional — only `tool_name` and `arguments` are required for dispatch.

```python
class FunctionCall(BaseModel):
    type:            Literal["FUNCTION_CALL"]
    step_number:     int
    tool_name:       str                         # must match a key in TOOL_MAP
    arguments:       dict[str, Any]              # forwarded as **kwargs to tool fn
    why_this_tool:   str = ""                    # optional — rationale for this call
    expected_output: str = ""                    # optional — what the agent expects back
```

### Schema C — `SelfCheck`

Mandatory validation gate before `FINAL_ANSWER`. If `passed=false`, the orchestrator requires a corrective `REASONING_STEP` before proceeding.

```python
class SelfCheck(BaseModel):
    type:                  Literal["SELF_CHECK"]
    step_number:           int
    claim_being_checked:   str                   # specific claim being verified
    verification_method:   Literal[
        "constraint_review",
        "order_of_magnitude",
        "assumption_review",
        "cross_validation",
        "accessibility_check",
    ]
    passed:  bool
    notes:   str = ""                            # finding — what passed or failed
```

### Schema D — `FinalAnswer`

Complete trip plan. Pydantic enforces budget math: `total` must equal the sum of all components within ±₹500.

```python
class Activity(BaseModel):
    time:          Optional[str]
    activity:      str
    duration:      Optional[str]
    cost_inr:      int                           # ge=0, default=0
    accessibility: Optional[Literal["easy", "moderate", "difficult"]]
    tip:           Optional[str]

class Meal(BaseModel):
    meal_type:    Literal["Breakfast", "Lunch", "Dinner"]
    suggestion:   str
    cuisine:      Optional[str]
    est_cost_inr: int                            # ge=0, default=0

class ItineraryDay(BaseModel):
    day:            int                          # ge=1
    title:          str
    activities:     list[Activity]
    meals:          list[Meal]
    stay:           Optional[str]
    transport_note: Optional[str]

class CostBreakdown(BaseModel):
    accommodation: int
    transport:     int
    food:          int
    activities:    int
    buffer:        int
    total:         int                           # validated: must = sum ± 500
    within_budget: bool

    @model_validator(mode="after")
    def total_check(self) -> "CostBreakdown":
        expected = accommodation + transport + food + activities + buffer
        if abs(self.total - expected) > 500:
            raise ValueError(...)

class FinalAnswer(BaseModel):
    type:                     Literal["FINAL_ANSWER"]
    destination:              str
    country:                  str
    confidence:               Literal["high", "medium", "low"]
    weather_summary:          str
    itinerary:                list[ItineraryDay]
    cost_breakdown:           CostBreakdown
    key_assumptions:          list[str]
    travel_tips:              list[str]
    local_cuisine_highlights: list[str]
    top_attractions:          list[str]
    caveats:                  list[str]
    fallback_advice:          str
```

### Type Dispatch

```python
LLMResponse = Union[ReasoningStep, FunctionCall, SelfCheck, FinalAnswer]

def parse_llm_response(data: dict) -> LLMResponse:
    cls = {"REASONING_STEP": ReasoningStep, "FUNCTION_CALL": FunctionCall,
           "SELF_CHECK": SelfCheck, "FINAL_ANSWER": FinalAnswer}[data["type"]]
    return cls.model_validate(data)
```

---

## Agent Reasoning Sequence

The orchestrator enforces two rules:
1. **Post-tool gate** — a `REASONING_STEP` must follow every tool result before the next tool can be called.
2. **Pre-final guard** — `FINAL_ANSWER` is blocked until both a post-gather `analysis` step and a `SELF_CHECK` have been emitted.

```
Phase 1 — UNDERSTAND
  #1   🧠 REASONING_STEP  decomposition
       Identify: destination · party · budget · days · origin · accessibility

Phase 2 — GATHER + INTERPRET  (interleaved tool calls and reasoning)
  #2   ⚡ FUNCTION_CALL   resolve_location
  #3   🧠 REASONING_STEP  lookup      "got lat/lon, proceeding to weather"
  #4   ⚡ FUNCTION_CALL   get_weather
  #5   🧠 REASONING_STEP  lookup      "June = SW monsoon; hill country safer"
  #6   ⚡ FUNCTION_CALL   search_attractions
  #7   🧠 REASONING_STEP  analysis    "top 3 adventure sites identified"
  #8   ⚡ FUNCTION_CALL   get_local_cuisine
  #9   🧠 REASONING_STEP  lookup      "hoppers, kottu, ambul thiyal noted"
  #10  ⚡ FUNCTION_CALL   search_hotels
  #11  🧠 REASONING_STEP  analysis    "Hotel X fits budget at ₹3k/night"
  #12  ⚡ FUNCTION_CALL   compute_budget
       ↳ orchestrator injects hard directive with 5 mandatory analysis questions

Phase 3 — ANALYSE
  #13  🧠 REASONING_STEP  analysis    (full plan synthesis — all 5 questions answered)

Phase 4 — VALIDATE
  #14  🔍 SELF_CHECK       cross_validation
       ✓ total ≤ budget  ✓ every day covered  ✓ no invented figures  ✓ weather-safe

Phase 5 — DELIVER
  #15  ✈  FINAL_ANSWER
```

### Orchestrator Enforcement

```python
# After every tool result (non-budget):
awaiting_post_tool_reason = True
# → next FunctionCall is blocked with "emit REASONING_STEP first"
# → cleared when any ReasoningStep is received

# After compute_budget:
# → hard directive injected: 5 mandatory analysis questions
# → agent must answer all before proceeding

# Before FinalAnswer is yielded:
if not has_analysis or not has_self_check:
    # → FINAL_ANSWER swallowed; agent told to emit missing steps first
```

---

## Setup

### Prerequisites

- Python ≥ 3.11
- [uv](https://github.com/astral-sh/uv)
- An LLM gateway at `EXTERNAL_BASE_URL` **or** [Ollama](https://ollama.ai) running locally

### Install

```bash
git clone <repo>
cd tripmind
uv sync
```

### Configure

```bash
cp .env.example .env
```

Edit `.env`:

```env
# LLM backend
LLM_PROVIDER=external          # or: ollama
EXTERNAL_BASE_URL=http://0.0.0.0:8100
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2

# Tool API keys
OPENTRIPMAP_API_KEY=your_key   # https://dev.opentripmap.org (free, 5k req/day)

# Server
TRIPMIND_PORT=8200
```

> **Free APIs with no key required:** Open-Meteo (geocoding + weather), OpenStreetMap Overpass (restaurants), TheMealDB (cuisine), Wikipedia (destination info).

### Run

```bash
uv run python -m server.api
# → http://localhost:8200
```

---

## Project Structure

```
tripmind/
├── server/
│   ├── api.py            # FastAPI routes, SSE bridge
│   ├── orchestrator.py   # Agent loop: LLM → JSON repair → Pydantic → tool dispatch
│   └── schemas.py        # Pydantic models for all 4 agent response types
├── mcp_tools/
│   ├── __init__.py       # dispatch_tool() entry point + TOOL_MAP
│   ├── geocoding.py      # resolve_location  — Open-Meteo, Indian city aliases
│   ├── weather.py        # get_weather       — Open-Meteo forecast
│   ├── attractions.py    # search_attractions — OpenTripMap
│   ├── hotels.py         # search_hotels     — OpenTripMap accommodations
│   ├── cuisine.py        # get_local_cuisine — TheMealDB + keyword fallback
│   ├── restaurants.py    # search_restaurants — OSM Overpass
│   ├── transport.py      # get_route         — OSRM
│   ├── budget.py         # compute_budget    — pure arithmetic
│   ├── destination_info.py # get_destination_info — Wikipedia
│   └── server.py         # MCP stdio server (for Claude Desktop integration)
├── prompts/
│   └── trip_planner.py   # System prompt — full reasoning mode
├── web/
│   └── index.html        # Single-file UI: chat + reasoning drawer
├── .env.example
└── pyproject.toml
```

---

## Key Engineering Decisions

| Decision | Rationale |
|----------|-----------|
| Sync generator + asyncio.Queue | `httpx` LLM calls are blocking; bridging to async SSE avoids `run_in_executor` complexity while keeping clean cancellation via `threading.Event` |
| `json_repair` fallback | LLMs emit unescaped newlines in long `thought` fields; strict `json.loads` fails ~20–30% of deep-reasoning steps — `json_repair` fixes silently |
| Pydantic `model_validator` on `CostBreakdown` | Catches hallucinated totals at parse time before the UI renders bad budget data |
| `reasoning_type` 9-value taxonomy | Each value maps to a distinct badge in the UI drawer; steers the LLM to the right cognitive mode (e.g. `arithmetic` for budget math, `lookup` for post-tool interpretation) |
| Two-layer reasoning enforcement | **Directive** (tool result message tells LLM what to do next) + **Gate** (orchestrator blocks next tool call if `awaiting_post_tool_reason=True`) — directive alone is ignored ~40% of the time |
| Post-`compute_budget` hard directive | After the last data tool, 5 specific questions are injected; the LLM cannot write a vague analysis — it must answer each question in the `thought` field |
| Optional metadata fields on `FunctionCall` / `SelfCheck` | LLMs omit `why_this_tool`, `notes` etc. on complex multi-country queries; making them optional prevents schema validation failures that would consume retry budget |
| Indian city alias map | Open-Meteo returns Pakistan for "Bangalore" and Japan for "Cochin"; 50+ aliases + forced `country_code=IN` filter fix all known collisions |
| `max_tokens=8192` | `FINAL_ANSWER` for a 3-day itinerary is ~2,000–3,500 tokens; 4096 caused mid-JSON truncation and parse failures |
