"""Backend tools package – re-exports every tool for convenient access.

Usage::

    from backend.tools import geocode_address, search_nearby_places
    from backend.tools import calculate_distances, scrape_reviews
"""

from backend.tools.geocoding import geocode_address
from backend.tools.places import search_nearby_places
from backend.tools.distance_matrix import calculate_distances
from backend.tools.review_scraper import scrape_reviews

__all__: list[str] = [
    "geocode_address",
    "search_nearby_places",
    "calculate_distances",
    "scrape_reviews",
]
