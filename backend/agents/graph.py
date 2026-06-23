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

from langgraph.graph import StateGraph, END

from backend.agents.state import AgentState
from backend.agents.supervisor import supervisor_entry, supervisor_exit
from backend.agents.geo_mapping import geo_mapping_node
from backend.agents.review_analyst import review_analyst_node

logger = logging.getLogger(__name__)


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

    return builder.compile()


# ── Singleton compiled graph ────────────────────────────────────────────
graph = build_graph()
