"""Distance Matrix tool – calculates travel distances and durations.

Uses the Google Maps Distance Matrix API to compute walking and transit
distances from a single origin to multiple destinations.
"""

from __future__ import annotations

import logging
from typing import Any

import googlemaps

from backend.config import settings

logger = logging.getLogger(__name__)

# Circuit breaker — set to False on first REQUEST_DENIED so we stop retrying
_directions_api_enabled: bool = True

# Vehicle type → human-readable label
_VEHICLE_LABELS: dict[str, str] = {
    "SUBWAY":          "Metro",
    "HEAVY_RAIL":      "RER",
    "COMMUTER_TRAIN":  "Train",
    "BUS":             "Bus",
    "TRAM":            "Tram",
    "FERRY":           "Ferry",
    "CABLE_CAR":       "Cable car",
    "GONDOLA_LIFT":    "Gondola",
    "FUNICULAR":       "Funicular",
}


def get_transit_route(
    origin: tuple[float, float],
    destination: tuple[float, float],
) -> dict:
    """Fetch transit directions with line details (Directions API).

    Returns empty dict if the API is disabled or the call fails.
    Uses a module-level circuit breaker to avoid repeated failed calls.
    """
    global _directions_api_enabled
    if not _directions_api_enabled:
        return {}

    try:
        gmaps = googlemaps.Client(key=settings.GOOGLE_MAPS_API_KEY)
        results = gmaps.directions(
            origin=origin,
            destination=destination,
            mode="transit",
            language="en",
        )
        if not results:
            return {}

        leg = results[0]["legs"][0]
        duration = leg.get("duration", {})

        lines: list[dict] = []
        for step in leg.get("steps", []):
            if step.get("travel_mode") != "TRANSIT":
                continue
            td = step.get("transit_details", {})
            line_data = td.get("line", {})
            vehicle = line_data.get("vehicle", {})
            v_type = vehicle.get("type", "")
            v_name = vehicle.get("name", "")
            v_label = _VEHICLE_LABELS.get(v_type, v_name or "Transit")
            line_name = line_data.get("short_name") or line_data.get("name", "")
            num_stops = td.get("num_stops", 0)
            if line_name:
                lines.append({"name": line_name, "vehicle": v_label, "stops": num_stops})

        logger.info("Transit route: %s — lines=%s", duration.get("text", "?"), lines)
        return {
            "duration_text":  duration.get("text", ""),
            "duration_value": duration.get("value", 0),
            "lines":          lines,
        }

    except googlemaps.exceptions.ApiError as exc:
        err_str = str(exc)
        if "REQUEST_DENIED" in err_str or "legacy API" in err_str:
            _directions_api_enabled = False
            logger.warning(
                "Directions API is disabled in this GCP project. "
                "Enable it at: Google Cloud Console → APIs & Services → Directions API. "
                "Transit line details will be unavailable until it's enabled."
            )
        else:
            logger.warning("Directions API error: %s", exc)
        return {}
    except Exception as exc:
        logger.warning("get_transit_route failed: %s", exc)
        return {}


def calculate_distances(
    origin: tuple[float, float],
    destinations: list[tuple[float, float]],
    modes: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Calculate travel distance and duration from an origin to each destination.

    Parameters
    ----------
    origin:
        ``(lat, lng)`` of the starting point.
    destinations:
        List of ``(lat, lng)`` tuples for each destination.
    modes:
        Travel modes to query, e.g. ``["walking", "transit"]``.
        Defaults to ``settings.DEFAULT_TRAVEL_MODES``.

    Returns
    -------
    list[dict]
        One dict per destination.  Each dict is keyed by travel mode::

            {
                "walking": {
                    "distance_text": "500 m",
                    "duration_text": "6 mins",
                    "distance_value": 500,
                    "duration_value": 360,
                },
                "transit": { ... },
            }

        If a particular mode/destination combination fails, that mode key
        will contain ``{"error": "<message>"}``.
    """
    if modes is None:
        modes = list(settings.DEFAULT_TRAVEL_MODES)

    if not destinations:
        logger.warning("calculate_distances called with empty destinations list")
        return []

    try:
        gmaps = googlemaps.Client(key=settings.GOOGLE_MAPS_API_KEY)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to initialise Google Maps client: %s", exc)
        return [{"error": f"Client init failed: {exc}"} for _ in destinations]

    # Pre-fill results: one entry per destination
    results: list[dict[str, Any]] = [{} for _ in destinations]

    for mode in modes:
        try:
            logger.info(
                "Querying distance_matrix: origin=%s, destinations=%s, mode=%s",
                origin,
                destinations,
                mode,
            )

            response: dict = gmaps.distance_matrix(
                origins=[origin],
                destinations=destinations,
                mode=mode,
            )

            rows: list[dict] = response.get("rows", [])
            if not rows:
                logger.warning("Empty rows in distance_matrix response for mode=%s", mode)
                for idx in range(len(destinations)):
                    results[idx][mode] = {"error": "No rows returned from API"}
                continue

            elements: list[dict] = rows[0].get("elements", [])

            for idx, element in enumerate(elements):
                if idx >= len(destinations):
                    break

                status = element.get("status", "UNKNOWN")
                if status != "OK":
                    logger.warning(
                        "distance_matrix element status=%s for destination index %d, mode=%s",
                        status,
                        idx,
                        mode,
                    )
                    results[idx][mode] = {"error": f"API status: {status}"}
                    continue

                distance_info: dict = element.get("distance", {})
                duration_info: dict = element.get("duration", {})

                results[idx][mode] = {
                    "distance_text": distance_info.get("text", "N/A"),
                    "duration_text": duration_info.get("text", "N/A"),
                    "distance_value": distance_info.get("value", 0),
                    "duration_value": duration_info.get("value", 0),
                }

        except googlemaps.exceptions.ApiError as exc:
            logger.error("Google Maps API error for mode=%s: %s", mode, exc)
            for idx in range(len(destinations)):
                results[idx][mode] = {"error": f"API error: {exc}"}
        except googlemaps.exceptions.TransportError as exc:
            logger.error("Network error for mode=%s: %s", mode, exc)
            for idx in range(len(destinations)):
                results[idx][mode] = {"error": f"Network error: {exc}"}
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error for mode=%s", mode)
            for idx in range(len(destinations)):
                results[idx][mode] = {"error": f"Unexpected error: {exc}"}

    logger.info("Distance calculations complete for %d destinations", len(destinations))
    return results
