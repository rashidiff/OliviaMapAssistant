"""Places search tool – finds nearby restaurants matching a keyword.

Uses the Google Maps Places Text Search API (gmaps.places) for accurate
cuisine-type matching, followed by Place Details for enriched data.
"""

from __future__ import annotations

import logging
from typing import Any

import googlemaps
import requests

from backend.config import settings

logger = logging.getLogger(__name__)

_CURRENCY_SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "JPY": "¥"}
_new_places_api_enabled: bool = True  # circuit breaker


def _fetch_price_range(place_id: str, api_key: str) -> str | None:
    """Fetch human-readable price range from the new Places API (v1).

    Falls back to None if the API isn't enabled or returns no data.
    Uses a module-level circuit breaker to avoid repeated 403 calls.
    """
    global _new_places_api_enabled
    if not _new_places_api_enabled:
        return None
    try:
        url = f"https://places.googleapis.com/v1/places/{place_id}"
        resp = requests.get(
            url,
            headers={
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": "priceRange",
            },
            timeout=5,
        )
        if resp.status_code == 403:
            _new_places_api_enabled = False
            logger.warning(
                "Places API (New) is disabled in this GCP project. "
                "Enable it at: Google Cloud Console → APIs & Services → Places API (New). "
                "Price range text will be unavailable until it's enabled."
            )
            return None
        if not resp.ok:
            return None
        data = resp.json()
        pr = data.get("priceRange")
        if not pr:
            return None
        start = pr.get("startPrice", {})
        end = pr.get("endPrice", {})
        currency = start.get("currencyCode", "EUR")
        sym = _CURRENCY_SYMBOLS.get(currency, currency)
        low = start.get("units", "")
        high = end.get("units", "")
        if low and high:
            return f"{sym}{low}–{high}"
        if low:
            return f"{sym}{low}+"
    except Exception as exc:
        logger.warning("New Places API exception: %s", exc)
    return None


def search_nearby_places(
    lat: float,
    lng: float,
    keyword: str,
    radius: int = 1500,
    place_type: str = "restaurant",
) -> list[dict[str, Any]]:
    """Search for restaurants near a location using Text Search.

    Uses gmaps.places() (Text Search API) rather than places_nearby(), so
    the query is matched against the place's *name and type* — not reviews.
    This prevents false positives where a non-Iranian restaurant appears
    because a reviewer happened to mention Iranian food.

    Returns up to 5 candidates sorted by rating (descending).
    """
    try:
        gmaps = googlemaps.Client(key=settings.GOOGLE_MAPS_API_KEY)

        # Build a natural-language query: "iranian restaurant" / "pizza" / etc.
        # Append "restaurant" only when the keyword doesn't already contain it.
        query_term = keyword.strip()
        kw_lower = query_term.lower()
        non_restaurant_terms = ["restaurant", "رستوران", "cafe", "کافه", "bar", "بار", "bakery", "قنادی", "coffee", "قهوه"]
        if not any(term in kw_lower for term in non_restaurant_terms):
            query_term = f"{query_term} restaurant"

        logger.info(
            "Text search: query=%r, location=(%s, %s), radius=%d",
            query_term, lat, lng, radius,
        )

        response: dict = gmaps.places(
            query=query_term,
            location=(lat, lng),
            radius=radius,
            type=place_type,
        )

        raw_results: list[dict] = response.get("results", [])

        # If text search returns nothing, fall back to nearby search
        if not raw_results:
            logger.info(
                "Text search returned 0 results for %r — trying nearby search", query_term
            )
            response = gmaps.places_nearby(
                location=(lat, lng),
                radius=radius,
                type=place_type,
                keyword=keyword,
            )
            raw_results = response.get("results", [])

        if not raw_results:
            logger.info("No places found for %r near (%s, %s)", query_term, lat, lng)
            return []

        logger.info("Found %d raw results, enriching with place details…", len(raw_results))

        places: list[dict[str, Any]] = []
        for result in raw_results[:10]:  # Enrich only first 10 to limit API calls
            place_id: str = result.get("place_id", "")
            if not place_id:
                continue

            try:
                detail_response: dict = gmaps.place(
                    place_id=place_id,
                    fields=[
                        "name",
                        "url",
                        "formatted_address",
                        "geometry",
                        "rating",
                        "user_ratings_total",
                        "place_id",
                        "reviews",
                        "price_level",
                    ],
                )
                detail: dict = detail_response.get("result", {})
            except Exception as detail_exc:
                logger.warning(
                    "Failed to fetch details for place_id=%s: %s", place_id, detail_exc
                )
                detail = result

            geometry = detail.get("geometry", result.get("geometry", {}))
            location_data = geometry.get("location", {})

            raw_price_detail = detail.get("price_level")
            raw_price_result = result.get("price_level")
            raw_price = raw_price_detail if raw_price_detail is not None else raw_price_result
            price_level = int(raw_price) if raw_price is not None else None

            name_for_log = detail.get("name", result.get("name", place_id))
            logger.info(
                "PRICE DEBUG %s: detail.price_level=%r  result.price_level=%r  → price_level=%r",
                name_for_log, raw_price_detail, raw_price_result, price_level,
            )

            # If old API has no price_level, try new Places API for priceRange
            price_range_text: str | None = None
            if price_level is None and place_id:
                price_range_text = _fetch_price_range(place_id, settings.GOOGLE_MAPS_API_KEY)
                logger.info(
                    "PRICE DEBUG %s: new API priceRange=%r", name_for_log, price_range_text
                )

            place_entry: dict[str, Any] = {
                "name": detail.get("name", result.get("name", "Unknown")),
                "place_id": place_id,
                "lat": location_data.get("lat", lat),
                "lng": location_data.get("lng", lng),
                "rating": float(detail.get("rating", result.get("rating", 0.0))),
                "total_ratings": int(
                    detail.get("user_ratings_total", result.get("user_ratings_total", 0))
                ),
                "address": detail.get("formatted_address", result.get("vicinity", "")),
                "google_maps_url": detail.get("url", ""),
                "api_reviews": detail.get("reviews", []),
                "price_level": price_level,
                "price_range_text": price_range_text,
            }
            places.append(place_entry)

        places.sort(key=lambda p: (p["rating"], p["total_ratings"]), reverse=True)
        top_places = places[:5]

        logger.info(
            "Returning top %d places (of %d total)", len(top_places), len(places)
        )
        return top_places

    except googlemaps.exceptions.ApiError as exc:
        logger.error("Google Maps API error during places search: %s", exc)
        return []
    except googlemaps.exceptions.TransportError as exc:
        logger.error("Network error during places search: %s", exc)
        return []
    except Exception as exc:
        logger.exception("Unexpected error during places search")
        return []
