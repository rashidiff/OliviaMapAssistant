"""FastAPI application for the multi-agent restaurant discovery system.

Endpoints:
    WS  /ws/chat   – WebSocket endpoint with streaming status updates.
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
from pydantic import BaseModel, Field, ValidationError, field_validator

from backend.agents.graph import graph
from backend.config import settings

logger = logging.getLogger(__name__)

# ── Paths ───────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"


class ChatRequest(BaseModel):
    """Validated browser payload for the chat WebSocket."""

    text: str = Field(min_length=1, max_length=500)
    userAddress: str = Field(min_length=1, max_length=500)
    userBudget: int | None = Field(default=None, ge=1, le=4)
    sessionId: str = Field(default="default_session", min_length=1, max_length=80)

    @field_validator("text", "userAddress", "sessionId")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be empty")
        return stripped


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
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)




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
            try:
                data: dict[str, Any] = json.loads(raw)
                request = ChatRequest.model_validate(data)
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                await ws.send_json(
                    {"type": "error", "message": f"Invalid request: {exc}"}
                )
                continue

            logger.info(
                "WebSocket: received query – %s | address – %s | budget – %s",
                request.text[:80],
                request.userAddress[:80],
                request.userBudget,
            )

            config = {"configurable": {"thread_id": request.sessionId}}

            initial_state = {
                "user_query": request.text,
                "user_location_text": request.userAddress,
                "max_price_level": request.userBudget,
                "error": "",
                "status_updates": [],
                "messages": [("user", request.text)],
            }

            # Track already-sent status messages to avoid duplicates
            sent_statuses: set[str] = set()

            try:
                async for event in graph.astream(
                    initial_state,
                    config=config,
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




# ── Reverse Geocoding Endpoint ──────────────────────────────────────────

@app.get("/api/geocode/reverse")
async def api_reverse_geocode(lat: float, lng: float) -> JSONResponse:
    """Reverse geocode latitude & longitude into a human-readable address."""
    from backend.tools.geocoding import reverse_geocode_coordinates
    res = reverse_geocode_coordinates(lat, lng)
    if "error" in res:
        return JSONResponse(status_code=400, content=res)
    return JSONResponse(content=res)


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


@app.get("/health")
async def health() -> JSONResponse:
    """Lightweight health check for deployment platforms."""
    return JSONResponse(content={"status": "ok", "service": "olivia-map-assistant"})


# Mount static files *after* explicit routes so they don't shadow them
if FRONTEND_DIR.exists():
    app.mount(
        "/static",
        StaticFiles(directory=str(FRONTEND_DIR)),
        name="static",
    )
