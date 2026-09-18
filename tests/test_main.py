from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.main import ChatRequest


def test_chat_request_strips_text_fields() -> None:
    request = ChatRequest.model_validate(
        {
            "text": " sushi ",
            "userAddress": " Paris ",
            "userBudget": 2,
            "sessionId": " abc ",
        }
    )

    assert request.text == "sushi"
    assert request.userAddress == "Paris"
    assert request.sessionId == "abc"


def test_chat_request_rejects_invalid_budget() -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(
            {
                "text": "sushi",
                "userAddress": "Paris",
                "userBudget": 9,
            }
        )


def test_chat_request_rejects_invalid_session_id() -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(
            {
                "text": "sushi",
                "userAddress": "Paris",
                "sessionId": "../../bad",
            }
        )
