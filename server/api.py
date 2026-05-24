"""
TripMind FastAPI server.

Routes
──────
GET  /          → web/index.html
GET  /health    → backend status
GET  /providers → available LLM providers
POST /chat      → SSE stream of agent events
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from server.orchestrator import agent_steps  # noqa: E402

GATEWAY_URL  = os.getenv("EXTERNAL_BASE_URL", "http://localhost:8100")
OLLAMA_URL   = os.getenv("OLLAMA_BASE_URL",   "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL",       "llama3.2")
LLM_PROVIDER = os.getenv("LLM_PROVIDER",       "external").lower()
PORT         = int(os.getenv("TRIPMIND_PORT",  "8200"))

app = FastAPI(title="TripMind", version="2.0")

# ── Static files ──────────────────────────────────────────────────────────────

@app.get("/")
async def index() -> FileResponse:
    return FileResponse(str(_ROOT / "web" / "index.html"))


# ── Health & info ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    status = {
        "status":    "ok",
        "backend":   LLM_PROVIDER,
        "tools": [
            "resolve_location", "get_weather", "get_destination_info",
            "search_attractions", "get_local_cuisine", "search_restaurants",
            "get_route", "search_hotels", "compute_budget",
        ],
    }
    if LLM_PROVIDER == "external":
        status["gateway_url"] = GATEWAY_URL
    else:
        status["ollama_url"]  = OLLAMA_URL
        status["ollama_model"] = OLLAMA_MODEL
    return status


@app.get("/providers")
async def providers() -> dict:
    """
    Returns provider list for the UI dropdown.
    When using the external gateway, proxies its /v1/providers endpoint
    and appends 'ollama' as an additional option.
    """
    result: dict = {
        "order":          [],
        "providers":      {},
        "shortcuts":      {},
        "active_backend": LLM_PROVIDER,
    }

    # Try to fetch gateway providers
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{GATEWAY_URL}/v1/providers")
            r.raise_for_status()
            gw = r.json()
            result["order"]     = list(gw.get("order") or [])
            result["providers"] = dict(gw.get("providers") or {})
            result["shortcuts"] = dict(gw.get("shortcuts") or {})
    except Exception:
        pass

    # Always include ollama
    if "ollama" not in result["order"]:
        result["order"].append("ollama")
    result["providers"]["ollama"] = {
        "type":          "local",
        "base_url":      OLLAMA_URL,
        "default_model": OLLAMA_MODEL,
    }

    return result


# ── Chat SSE endpoint ─────────────────────────────────────────────────────────

class ChatBody(BaseModel):
    message:   str
    history:   Optional[list] = None
    provider:  Optional[str]  = None   # "ollama" → local, else → gateway sub-provider
    model:     Optional[str]  = None
    max_steps: int             = 24


@app.post("/chat")
async def chat(body: ChatBody) -> StreamingResponse:
    """
    Bridge synchronous agent_steps() generator to an async SSE stream.

    Pattern:
      Worker thread runs the blocking generator, pushes each event onto
      an asyncio.Queue via run_coroutine_threadsafe.
      Async SSE generator drains the queue and yields SSE frames.
      Client disconnect sets a threading.Event to stop the worker.
    """
    # Determine provider to pass to orchestrator
    gw_provider: Optional[str] = body.provider
    if body.provider == "ollama":
        # Signal orchestrator to use ollama via env — don't pass as gw_provider
        gw_provider = None

    loop       = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    stop_event = threading.Event()
    _SENTINEL  = object()

    def worker() -> None:
        try:
            for evt in agent_steps(
                body.message,
                history   = body.history or [],
                provider  = gw_provider,
                model     = body.model,
                max_steps = body.max_steps,
            ):
                if stop_event.is_set():
                    break
                asyncio.run_coroutine_threadsafe(queue.put(evt), loop)
        except Exception as exc:
            asyncio.run_coroutine_threadsafe(
                queue.put({"event": "error", "message": str(exc), "recoverable": False}),
                loop,
            )
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(_SENTINEL), loop)

    async def sse_stream():
        loop.run_in_executor(None, worker)
        try:
            while True:
                evt = await queue.get()
                if evt is _SENTINEL:
                    break
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'event': 'end'})}\n\n"
        except asyncio.CancelledError:
            stop_event.set()
            raise

    return StreamingResponse(
        sse_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print(f"TripMind v2  backend={LLM_PROVIDER}  port={PORT}")
    uvicorn.run("server.api:app", host="0.0.0.0", port=PORT, reload=False)
