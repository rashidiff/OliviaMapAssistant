"""Geo-mapping agent node – geocoding, nearby search, and distance calculation.

This node is responsible for the full geo-spatial pipeline:
1. Geocode the user's textual location to coordinates.
2. Search for nearby places matching the criteria.
3. Calculate walking + transit distances from the user location.
4. Sort by walking distance and return the top-N results.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.agents.state import AgentState, PlaceInfo
from backend.config import settings
from backend.tools.geocoding import geocode_address
from backend.tools.places import search_nearby_places
from backend.tools.distance_matrix import calculate_distances, get_transit_route

logger = logging.getLogger(__name__)


def _format_duration(distances: dict) -> str:
    """Build a human-readable duration string from multi-mode distance data.

    Expected ``distances`` structure (per place, returned by
    ``calculate_distances``):
    ```
    {
        "walking": {"distance_text": "500 m", "duration_text": "6 mins", "distance_value": 500, "duration_value": 360},
        "transit": {"distance_text": "1.2 km", "duration_text": "3 mins", "distance_value": 1200, "duration_value": 180},
    }
    ```

    Returns a string like ``"6 mins walking / 3 mins metro"``.
    """
    parts: list[str] = []

    walking = distances.get("walking", {})
    if walking.get("duration_text"):
        parts.append(f"{walking['duration_text']} walking")

    transit = distances.get("transit", {})
    if transit.get("duration_text"):
        parts.append(f"{transit['duration_text']} metro")

    return " / ".join(parts) if parts else "N/A"


def _format_distance_text(distances: dict) -> str:
    """Return the shortest textual distance (walking preferred)."""
    walking = distances.get("walking", {})
    if walking.get("distance_text"):
        return walking["distance_text"]
    transit = distances.get("transit", {})
    if transit.get("distance_text"):
        return transit["distance_text"]
    return "N/A"


def _walking_sort_key(place: dict) -> int:
    """Extract walking distance value in metres for sorting (ascending)."""
    try:
        return int(
            place.get("distances", {})
            .get("walking", {})
            .get("distance_value", 999_999)
        )
    except (TypeError, ValueError):
        return 999_999


def geo_mapping_node(state: AgentState) -> dict:
    """Geocode → nearby search → distance matrix → top-N selection.

    On failure (e.g. geocoding error) the node sets ``error`` in the state so
    the graph can short-circuit to the supervisor exit.
    """
    logger.info("geo_mapping_node: starting")

    if state.get("error"):
        logger.info("geo_mapping_node: error already present in state – skipping")
        return state

    location_text: str = state.get("user_location_text", "")
    criteria: str = state.get("search_criteria", "restaurant")
    radius: int = state.get("search_radius", settings.DEFAULT_SEARCH_RADIUS)

    # ── 1. Geocode the textual location ─────────────────────────────────
    try:
        geo_result: dict[str, Any] = geocode_address(location_text)
    except Exception as exc:
        logger.exception("geo_mapping_node: geocoding failed")
        return {
            "error": f"Address '{location_text}' not found: {exc}",
            "status_updates": state.get("status_updates", [])
            + ["❌ Error resolving location address."],
        }

    if not geo_result or "lat" not in geo_result or "lng" not in geo_result:
        msg = f"Address '{location_text}' could not be resolved."
        logger.warning("geo_mapping_node: %s", msg)
        return {
            "error": msg,
            "status_updates": state.get("status_updates", [])
            + ["❌ Error resolving location address."],
        }

    lat: float = geo_result["lat"]
    lng: float = geo_result["lng"]
    user_coords = {"lat": lat, "lng": lng}

    logger.info("geo_mapping_node: geocoded to %s", user_coords)

    # ── 2. Search nearby places ─────────────────────────────────────────
    try:
        candidates: list[dict[str, Any]] = search_nearby_places(
            lat=lat,
            lng=lng,
            keyword=criteria,
            radius=radius,
        )
    except Exception as exc:
        logger.exception("geo_mapping_node: nearby search failed")
        return {
            "user_coordinates": user_coords,
            "error": f"Error searching for places: {exc}",
            "status_updates": state.get("status_updates", [])
            + ["❌ Error searching for places."],
        }

    expanded_radius = radius
    if not candidates:
        expanded_radius = radius * 2
        logger.info(
            "geo_mapping_node: 0 candidates at %dm — auto-expanding radius to %dm",
            radius,
            expanded_radius,
        )
        try:
            candidates = search_nearby_places(
                lat=lat,
                lng=lng,
                keyword=criteria,
                radius=expanded_radius,
            )
        except Exception:
            candidates = []

    if not candidates:
        return {
            "user_coordinates": user_coords,
            "error": (
                f"No places found within {expanded_radius}m "
                f"matching '{criteria}'."
            ),
            "status_updates": state.get("status_updates", [])
            + ["⚠️ No places found."],
        }

    logger.info(
        "geo_mapping_node: found %d candidates within %dm",
        len(candidates),
        radius,
    )

    # ── 3. Calculate distances (walking + transit) ──────────────────────
    destinations = [(p["lat"], p["lng"]) for p in candidates]

    try:
        distance_results: list[dict[str, Any]] = calculate_distances(
            origin=(lat, lng),
            destinations=destinations,
        )
    except Exception as exc:
        logger.exception("geo_mapping_node: distance matrix failed")
        # Continue without distance data – don't abort entirely
        distance_results = [{}] * len(candidates)

    # ── 4. Merge & format ───────────────────────────────────────────────
    enriched_places: list[PlaceInfo] = []

    for idx, candidate in enumerate(candidates):
        dist_info = (
            distance_results[idx] if idx < len(distance_results) else {}
        )
        place_id = candidate.get("place_id", "")
        dest_lat  = candidate.get("lat", lat)
        dest_lng  = candidate.get("lng", lng)

        coords = {"lat": dest_lat, "lng": dest_lng}

        # Use canonical URL from Places API if available; fall back to place_id
        google_maps_url = candidate.get("google_maps_url", "")
        if not google_maps_url and place_id:
            google_maps_url = (
                f"https://www.google.com/maps/place/?q=place_id:{place_id}"
            )

        # ── Fetch detailed transit route (line names, stops) ────────────
        transit_route = get_transit_route(
            origin=(lat, lng),
            destination=(dest_lat, dest_lng),
        )
        transit_lines: list[dict] = transit_route.get("lines", [])

        # If Directions API gave us a transit duration, prefer it over
        # Distance Matrix transit duration (which is the same data but less detail)
        transit_duration_text = transit_route.get("duration_text", "")
        if transit_duration_text:
            if "transit" not in dist_info:
                dist_info["transit"] = {}
            dist_info["transit"]["duration_text"] = transit_duration_text

        place: PlaceInfo = {
            "name": candidate.get("name", "Unknown"),
            "place_id": place_id,
            "coordinates": coords,
            "rating": candidate.get("rating", 0.0),
            "total_ratings": candidate.get("total_ratings", 0),
            "address": candidate.get("address", ""),
            "distances": dist_info,
            "distance_text": _format_distance_text(dist_info),
            "duration_text": _format_duration(dist_info),
            "transit_lines": transit_lines,
            "google_maps_url": google_maps_url,
            "price_level": candidate.get("price_level"),
            "price_range_text": candidate.get("price_range_text"),
            "api_reviews": candidate.get("api_reviews", []),
            "recent_reviews": [],
            "recent_reviews_summary": "",
            "review_source": "",
        }

        enriched_places.append(place)

    # ── 5. Sort by walking distance ─────────────────────────────────────
    enriched_places.sort(key=_walking_sort_key)

    # ── 6. Filter by price_level if the user specified a budget ─────────
    max_price_level: int | None = state.get("max_price_level")
    if max_price_level is not None:
        before = len(enriched_places)
        # Keep places where price_level is unknown OR within budget
        enriched_places = [
            p for p in enriched_places
            if p.get("price_level") is None or p["price_level"] <= max_price_level
        ]
        logger.info(
            "geo_mapping_node: price filter (max_level=%d) kept %d/%d places",
            max_price_level, len(enriched_places), before,
        )

    # ── 7. Filter by walking time if the user specified a limit ─────────
    max_walk_minutes: int | None = state.get("max_walk_minutes")
    if max_walk_minutes is not None:
        max_walk_seconds = max_walk_minutes * 60
        before = len(enriched_places)
        def _walk_seconds(place: dict) -> int | None:
            try:
                return int(
                    place.get("distances", {})
                    .get("walking", {})
                    .get("duration_value", 0)
                )
            except (TypeError, ValueError):
                return None

        enriched_places = [
            p for p in enriched_places
            if _walk_seconds(p) is None or _walk_seconds(p) <= max_walk_seconds
        ]
        logger.info(
            "geo_mapping_node: walk-time filter (max=%d min) kept %d/%d places",
            max_walk_minutes, len(enriched_places), before,
        )

    if not enriched_places:
        _PRICE_LABELS = {1: "€", 2: "€€", 3: "€€€", 4: "€€€€"}
        constraints = []
        if max_price_level is not None:
            constraints.append(f"price ≤ {_PRICE_LABELS.get(max_price_level, str(max_price_level))}")
        if max_walk_minutes is not None:
            constraints.append(f"walking ≤ {max_walk_minutes} min")
        constraint_str = " and ".join(constraints) if constraints else "your constraints"
        return {
            "user_coordinates": user_coords,
            "error": (
                f"No places found matching {constraint_str}. "
                "Try relaxing the budget or distance limit."
            ),
            "status_updates": state.get("status_updates", [])
            + ["⚠️ No places matched your constraints."],
        }

    # ── 8. Take top N ────────────────────────────────────────────────────
    max_results: int = getattr(settings, "MAX_RESULTS", 3)
    shortlisted = enriched_places[:max_results]

    logger.info(
        "geo_mapping_node: shortlisted %d places (out of %d)",
        len(shortlisted),
        len(enriched_places),
    )

    status_updates = list(state.get("status_updates", []))
    if expanded_radius > radius:
        status_updates.append(f"⚠️ Expanded search radius to {expanded_radius}m...")
    status_updates.append("📍 Nearby places found...")

    return {
        "user_coordinates": user_coords,
        "shortlisted_places": shortlisted,
        "status_updates": status_updates,
    }
