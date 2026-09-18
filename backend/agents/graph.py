"""LangGraph state-graph definition for the restaurant discovery pipeline.

Nodes:
    supervisor_entry  → parse the user's natural-language query
    geo_mapping       → geocode, nearby search, distance matrix
    review_analyst    → scrape & summarise recent reviews
    supervisor_exit   → build the final Persian response

Conditional edge:
    If ``geo_mapping`` sets ``error`` in the state, the graph skips directly
    to ``supervisor_exit`` (bypassing the review analyst).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from backend.agents.state import AgentState
from backend.agents.supervisor import supervisor_entry, supervisor_exit
from backend.agents.geo_mapping import geo_mapping_node
from backend.agents.review_analyst import review_analyst_node
from backend.config import settings

logger = logging.getLogger(__name__)
_sqlite_connection: sqlite3.Connection | None = None


def _build_checkpointer():
    """Build the configured LangGraph checkpointer.

    SQLite keeps chat state across process restarts. If the optional package is
    unavailable, fall back to in-memory state so local development still works.
    """
    global _sqlite_connection

    checkpoint_path = settings.CHECKPOINT_DB_PATH.strip()
    if not checkpoint_path:
        logger.warning("CHECKPOINT_DB_PATH is empty; using in-memory checkpoints")
        return MemorySaver()

    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError:
        logger.warning(
            "langgraph-checkpoint-sqlite is not installed; using in-memory checkpoints"
        )
        return MemorySaver()

    db_path = Path(checkpoint_path)
    if not db_path.is_absolute():
        db_path = Path(__file__).resolve().parents[2] / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    _sqlite_connection = sqlite3.connect(str(db_path), check_same_thread=False)
    checkpointer = SqliteSaver(_sqlite_connection)
    checkpointer.setup()
    logger.info("Using SQLite LangGraph checkpoint store at %s", db_path)
    return checkpointer


def _route_after_geo(state: AgentState) -> str:
    """Decide the next node after geo_mapping.

    If the geo-mapping step recorded an error (e.g. geocoding failure, no
    results) we skip the review analyst entirely and jump straight to the
    supervisor exit so the user gets a fast, informative error response.
    """
    if state.get("error"):
        logger.info("_route_after_geo: error detected – skipping to exit")
        return "supervisor_exit"
    return "review_analyst"


def build_graph() -> StateGraph:
    """Construct and compile the LangGraph pipeline.

    Returns:
        A compiled ``StateGraph`` ready for ``ainvoke`` / ``astream``.
    """
    builder = StateGraph(AgentState)

    # ── Register nodes ──────────────────────────────────────────────────
    builder.add_node("supervisor_entry", supervisor_entry)
    builder.add_node("geo_mapping", geo_mapping_node)
    builder.add_node("review_analyst", review_analyst_node)
    builder.add_node("supervisor_exit", supervisor_exit)

    # ── Define edges ────────────────────────────────────────────────────
    builder.set_entry_point("supervisor_entry")

    builder.add_edge("supervisor_entry", "geo_mapping")

    # Conditional: skip review_analyst if geo_mapping encountered an error
    builder.add_conditional_edges(
        "geo_mapping",
        _route_after_geo,
        {
            "review_analyst": "review_analyst",
            "supervisor_exit": "supervisor_exit",
        },
    )

    builder.add_edge("review_analyst", "supervisor_exit")
    builder.add_edge("supervisor_exit", END)

    return builder.compile(checkpointer=_build_checkpointer())


# ── Singleton compiled graph ────────────────────────────────────────────
graph = build_graph()
