"""FastAPI application for the multi-agent restaurant discovery system.

Endpoints:
    WS  /ws/chat   – WebSocket endpoint with streaming status updates.
    POST /api/chat – REST fallback for non-WebSocket clients.
    GET  /         – Serves the frontend SPA (index.html).
    /*             – Static file serving from ``frontend/``.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.agents.graph import graph

logger = logging.getLogger(__name__)

# ── Paths ───────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"


# ── Lifespan (startup / shutdown) ──────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan – runs once on startup and shutdown."""
    # ── Startup ─────────────────────────────────────────────────────────
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    logger.info("🚀 Restaurant Discovery API is starting up …")

    # Validate critical environment configuration
    try:
        from backend.config import settings  # noqa: WPS433

        missing: list[str] = []
        if not getattr(settings, "GOOGLE_MAPS_API_KEY", None):
            missing.append("GOOGLE_MAPS_API_KEY")
        if not getattr(settings, "OPENAI_API_KEY", None):
            missing.append("OPENAI_API_KEY")

        if missing:
            logger.warning(
                "⚠️  Missing environment variables: %s – "
                "some features may not work.",
                ", ".join(missing),
            )
        else:
            logger.info("✅ All required environment variables are set.")
    except Exception as exc:
        logger.warning("⚠️  Could not validate config: %s", exc)

    logger.info("✅ Server is ready to accept requests.")

    yield  # ── Application runs ────────────────────────────────────────

    # ── Shutdown ────────────────────────────────────────────────────────
    logger.info("👋 Server is shutting down …")


# ── FastAPI app ─────────────────────────────────────────────────────────

app = FastAPI(
    title="Restaurant Discovery API",
    version="1.0.0",
    description="Multi-agent restaurant discovery system powered by LangGraph",
    lifespan=lifespan,
)

# ── CORS (permissive for local development) ─────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / response models ──────────────────────────────────────────

class ChatRequest(BaseModel):
    """JSON body for the REST chat endpoint."""
    text: str


# ── WebSocket endpoint ──────────────────────────────────────────────────

@app.websocket("/ws/chat")
async def websocket_chat(ws: WebSocket) -> None:
    """Stream status updates and the final result over a WebSocket.

    Protocol:
        Client → ``{"text": "user query"}``
        Server → ``{"type": "status", "message": "…"}`` (one per node)
        Server → ``{"type": "result", "data": {…}}``  (final)
        Server → ``{"type": "error", "message": "…"}``  (on failure)
    """
    await ws.accept()
    logger.info("WebSocket connection accepted")

    try:
        while True:
            raw = await ws.receive_text()
            data: dict[str, Any] = json.loads(raw)
            user_text: str = data.get("text", "").strip()
            user_address: str = data.get("userAddress", "").strip()

            # userBudget: null (no limit) or integer 1–4 sent from frontend
            raw_budget = data.get("userBudget")
            user_budget: int | None = int(raw_budget) if raw_budget is not None else None

            if not user_text:
                await ws.send_json(
                    {"type": "error", "message": "Please enter a query."}
                )
                continue

            if not user_address:
                await ws.send_json(
                    {"type": "error", "message": "Please set your location first."}
                )
                continue

            logger.info(
                "WebSocket: received query – %s | address – %s | budget – %s",
                user_text[:80],
                user_address[:80],
                user_budget,
            )

            initial_state = {
                "user_query": user_text,
                "user_location_text": user_address,
                "max_price_level": user_budget,
                "status_updates": [],
            }

            # Track already-sent status messages to avoid duplicates
            sent_statuses: set[str] = set()

            try:
                async for event in graph.astream(
                    initial_state,
                    stream_mode="updates",
                ):
                    # ``event`` is a dict  {node_name: node_output_dict}
                    for _node_name, node_output in event.items():
                        if not isinstance(node_output, dict):
                            continue

                        # Send any new status updates
                        for status_msg in node_output.get("status_updates", []):
                            if status_msg not in sent_statuses:
                                sent_statuses.add(status_msg)
                                await ws.send_json(
                                    {"type": "status", "message": status_msg}
                                )

                        # If this node produced the final response, send it
                        final = node_output.get("final_response")
                        if final is not None:
                            await ws.send_json({"type": "result", "data": final})
            except Exception as graph_exc:
                logger.exception("WebSocket: graph execution error")
                await ws.send_json(
                    {"type": "error", "message": f"Processing error: {graph_exc}"}
                )

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except json.JSONDecodeError:
        logger.warning("WebSocket: received invalid JSON")
        try:
            await ws.send_json(
                {"type": "error", "message": "Invalid message format."}
            )
        except Exception:
            pass
    except Exception as exc:
        logger.exception("WebSocket: unhandled error")
        try:
            await ws.send_json(
                {"type": "error", "message": f"Server error: {exc}"}
            )
        except Exception:
            pass


# ── REST endpoint ───────────────────────────────────────────────────────

@app.post("/api/chat")
async def rest_chat(request: ChatRequest) -> JSONResponse:
    """Run the agent graph synchronously and return the final response.

    This is a simpler alternative for clients that don't support WebSockets.
    """
    user_text = request.text.strip()
    if not user_text:
        return JSONResponse(
            status_code=400,
            content={"error": "Please enter a query."},
        )

    logger.info("REST /api/chat: received query – %s", user_text[:80])

    try:
        result = await graph.ainvoke(
            {"user_query": user_text, "status_updates": []}
        )
        final_response = result.get("final_response", {})
        return JSONResponse(content=final_response)
    except Exception as exc:
        logger.exception("REST /api/chat: graph execution failed")
        return JSONResponse(
            status_code=500,
            content={"error": f"Server error: {exc}"},
        )


# ── Static file serving & SPA fallback ─────────────────────────────────

@app.get("/")
async def serve_index() -> FileResponse:
    """Serve the frontend SPA entry point."""
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        return JSONResponse(
            status_code=404,
            content={"detail": "frontend/index.html not found"},
        )
    return FileResponse(str(index_path))


# Mount static files *after* explicit routes so they don't shadow them
if FRONTEND_DIR.exists():
    app.mount(
        "/static",
        StaticFiles(directory=str(FRONTEND_DIR)),
        name="static",
    )
