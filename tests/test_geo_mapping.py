from __future__ import annotations

from backend.agents.geo_mapping import _format_duration, rank_place


def test_format_duration_prefers_available_modes() -> None:
    distances = {
        "walking": {"duration_text": "8 mins"},
        "transit": {"duration_text": "4 mins"},
    }

    assert _format_duration(distances) == "8 mins walking / 4 mins metro"


def test_rank_place_rewards_rating_reviews_open_and_price() -> None:
    strong = {
        "rating": 4.8,
        "total_ratings": 500,
        "open_now": True,
        "price_level": 2,
        "distances": {"walking": {"distance_value": 400}},
    }
    weak = {
        "rating": 3.9,
        "total_ratings": 20,
        "open_now": False,
        "price_level": None,
        "distances": {"walking": {"distance_value": 1800}},
    }

    assert rank_place(strong) > rank_place(weak)
