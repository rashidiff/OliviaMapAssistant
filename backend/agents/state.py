"""Shared LangGraph state definitions for the restaurant discovery agent system.

This module defines the typed state dictionaries that flow through the LangGraph
pipeline. Every node reads from and writes to this shared state, ensuring a
consistent contract between agents.
"""

from __future__ import annotations

from typing import TypedDict, Optional, Annotated
from langgraph.graph.message import add_messages


class PlaceInfo(TypedDict, total=False):
    """Detailed information about a single restaurant / place candidate."""

    name: str
    place_id: str
    coordinates: dict          # {"lat": float, "lng": float}
    rating: float
    total_ratings: int
    address: str
    distance_text: str         # e.g. "500m"
    duration_text: str         # e.g. "6 mins walking / 3 mins metro"
    distances: dict            # Full distance info per travel mode
    google_maps_url: str
    price_level: Optional[int]      # 0=Free, 1=€, 2=€€, 3=€€€, 4=€€€€, None=unknown
    price_range_text: Optional[str] # e.g. "€10–20" from new Places API
    transit_lines: list             # e.g. [{"name":"13","vehicle":"Metro","stops":4}]
    api_reviews: list           # Raw reviews from Google Places API
    recent_reviews: list       # Raw scraped reviews
    recent_reviews_summary: str  # English summary produced by the LLM
    review_source: str          # Where reviews came from


class AgentState(TypedDict, total=False):
    """Top-level state flowing through the LangGraph pipeline."""

    user_query: str
    user_location_text: str
    search_criteria: str
    search_radius: int
    max_price_level: Optional[int]   # 1=€ 2=€€ 3=€€€ 4=€€€€, None=no constraint
    max_walk_minutes: Optional[int]  # None=no constraint
    user_coordinates: dict
    shortlisted_places: list[PlaceInfo]
    final_response: dict
    error: str
    status_updates: list[str]
    messages: Annotated[list, add_messages]
