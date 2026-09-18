from __future__ import annotations

from backend.agents.supervisor import build_recommendation_reason


def test_build_recommendation_reason_uses_factual_signals() -> None:
    reason = build_recommendation_reason(
        {
            "rating": 4.7,
            "total_ratings": 250,
            "duration_text": "8 mins walking",
            "open_now": True,
            "price_level": 2,
        }
    )

    assert reason == "4.7 rating from 250 reviews · 8 mins walking · open now"


def test_build_recommendation_reason_skips_missing_signals() -> None:
    assert build_recommendation_reason({"rating": 4.1}) == ""
