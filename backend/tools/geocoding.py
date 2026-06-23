"""Geocoding tool – converts a human-readable address into coordinates.

Uses the Google Maps Geocoding API via the ``googlemaps`` client library.
"""

from __future__ import annotations

import logging
from typing import Any

import googlemaps

from backend.config import settings

logger = logging.getLogger(__name__)


def geocode_address(address: str) -> dict[str, Any]:
    """Geocode a free-text address to latitude / longitude.

    Parameters
    ----------
    address:
        Human-readable address string, e.g. ``"Vali-Asr Ave, Tehran"``.

    Returns
    -------
    dict
        On success::

            {"lat": float, "lng": float, "formatted_address": str}

        On failure::

            {"error": str}
    """
    if not address or not address.strip():
        logger.warning("geocode_address called with empty address")
        return {"error": "Address must not be empty."}

    try:
        gmaps = googlemaps.Client(key=settings.GOOGLE_MAPS_API_KEY)
        results: list[dict] = gmaps.geocode(address)

        if not results:
            logger.info("No geocoding results for address: %s", address)
            return {"error": f"No results found for address: {address}"}

        top_result = results[0]
        location = top_result["geometry"]["location"]
        formatted_address: str = top_result.get("formatted_address", address)

        logger.info(
            "Geocoded '%s' → (%s, %s) [%s]",
            address,
            location["lat"],
            location["lng"],
            formatted_address,
        )

        return {
            "lat": location["lat"],
            "lng": location["lng"],
            "formatted_address": formatted_address,
        }

    except googlemaps.exceptions.ApiError as exc:
        logger.error("Google Maps API error during geocoding: %s", exc)
        return {"error": f"Google Maps API error: {exc}"}
    except googlemaps.exceptions.TransportError as exc:
        logger.error("Network error during geocoding: %s", exc)
        return {"error": f"Network error: {exc}"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error during geocoding")
        return {"error": f"Unexpected error: {exc}"}
