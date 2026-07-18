"""Supervisor agent nodes – entry (query parsing) and exit (final response).

The supervisor is responsible for:
1. Parsing the user's natural-language query (Persian or English) into
   structured fields (location, criteria, radius).
2. Assembling the final user-facing response once all data has been gathered.
"""

from __future__ import annotations

import logging
from typing import Optional

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from backend.agents.state import AgentState
from backend.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic model used with `with_structured_output`
# ---------------------------------------------------------------------------

class ParsedQuery(BaseModel):
    """Structured representation of the user's restaurant-search query."""

    location: str = Field(
        ...,
        description="The location or address the user wants to search near. "
                    "Extract the street name, landmark, or neighbourhood.",
    )
    criteria: str = Field(
        ...,
        description="The type of food, cuisine, or restaurant the user is "
                    "looking for. Use a concise keyword (e.g. 'pizza', 'sushi', "
                    "'kebab', 'cafe').",
    )
    radius: Optional[int] = Field(
        default=None,
        description="Search radius in metres if explicitly mentioned by the "
                    "user. Return None / null when no distance constraint is "
                    "stated.",
    )
    max_price_level: Optional[int] = Field(
        default=None,
        description=(
            "Maximum Google Maps price level the user will accept. "
            "Map user's price intent to 1, 2, 3, or 4:\n"
            "  1 = cheap / budget / inexpensive / under ~10 EUR per person\n"
            "  2 = moderate / mid-range / 10-30 EUR per person\n"
            "  3 = expensive / upscale / 30-60 EUR per person\n"
            "  4 = very expensive / fine dining / 60+ EUR per person\n"
            "Return null if the user did not mention a price constraint."
        ),
    )
    max_walk_minutes: Optional[int] = Field(
        default=None,
        description=(
            "Maximum walking time in minutes the user will accept. "
            "Extract only if the user explicitly mentions a walking/foot time constraint "
            "(e.g. '15 min walk', '25 minutes on foot', 'walking distance'). "
            "Return null otherwise."
        ),
    )


class ParsedCriteria(BaseModel):
    """Parsed criteria when the user's location and budget are already known."""

    criteria: str = Field(
        ...,
        description="The type of food, cuisine, or restaurant the user is "
                    "looking for. Use a concise English keyword (e.g. 'pizza', "
                    "'sushi', 'kebab', 'cafe').",
    )
    radius: Optional[int] = Field(
        default=None,
        description="Search radius in metres if explicitly mentioned. "
                    "Return None / null otherwise.",
    )
    max_walk_minutes: Optional[int] = Field(
        default=None,
        description=(
            "Maximum walking time in minutes the user will accept. "
            "Extract only if the user explicitly mentions a walking/foot time constraint "
            "(e.g. '15 min walk', '20 minutes on foot'). Return null otherwise."
        ),
    )


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_PARSE_SYSTEM_PROMPT = """\
You are a multilingual query parser for a restaurant discovery assistant.
The user will send a natural-language query in **Persian (فارسی)** or **English**.

Your job:
1. Extract the **location** (street, landmark, neighbourhood, or address).
2. Extract the **search criteria** – what kind of food or place the user wants \
   (e.g. pizza, kebab, café, seafood). Use a short English keyword suitable for \
   Google Maps search.
3. Extract the **radius** in metres *only* if the user explicitly mentions a \
   distance constraint (e.g. "within 500 metres", "نزدیک‌ترین در ۱ کیلومتری"). \
   Otherwise leave it as null.

Always reply with valid JSON matching the expected schema.
"""

_PARSE_CRITERIA_SYSTEM_PROMPT = """\
You are a multilingual query parser for a restaurant discovery assistant.
The user's location and budget are already set — you do NOT need to extract them.
The user will send a natural-language query in **Persian (فارسی)** or **English**.

Your job:
1. Extract the **search criteria** – what kind of food or place the user wants \
   (e.g. pizza, kebab, café, seafood). Use a short English keyword suitable for \
   Google Maps search.
2. Extract the **radius** in metres *only* if the user explicitly mentions a \
   distance constraint (e.g. "within 500 metres"). Otherwise leave it as null.
3. Extract **max_walk_minutes** *only* if the user mentions a walking time limit \
   (e.g. "20 min walk", "30 minutes on foot"). Otherwise leave it as null.

Always reply with valid JSON matching the expected schema.
"""

_FINAL_RESPONSE_SYSTEM_PROMPT = """\
You are a restaurant recommendation assistant. Always reply in English.

You receive structured data from Google Maps. Use ONLY what is in this data.

RULES:
- Do NOT add, guess, or infer anything not in the data.
- Do NOT mention prices unless the price_level field is present.
- Do NOT mention walking time unless duration_text is present.
- If review_summary is empty or says "No reviews", skip it entirely.
- 2 sentences max. Be concise and factual.

Reply with plain text only.
"""


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------

def supervisor_entry(state: AgentState) -> dict:
    """Parse the user query into location, criteria and radius.

    If the user's location is already set in state (pre-populated from the
    frontend address prompt), only criteria and radius are extracted from the
    query — the saved address is always used as the search origin.
    """
    logger.info("supervisor_entry: parsing user query")

    user_query: str = state.get("user_query", "")
    pre_set_location: str = state.get("user_location_text", "").strip()

    if not user_query.strip():
        return {
            "error": "Query is empty. Please tell me what type of food or restaurant you are looking for.",
            "status_updates": state.get("status_updates", [])
            + ["❌ Query is empty."],
        }

    llm = ChatOpenAI(
        model=settings.LLM_MODEL,
        temperature=0,
        api_key=settings.OPENAI_API_KEY,
    )

    # ── Path A: location already known — only extract criteria ───────────
    if pre_set_location:
        logger.info(
            "supervisor_entry: location pre-set to %r — only extracting criteria",
            pre_set_location,
        )
        structured_llm = llm.with_structured_output(ParsedCriteria)
        try:
            parsed_c: ParsedCriteria = structured_llm.invoke(
                [
                    {"role": "system", "content": _PARSE_CRITERIA_SYSTEM_PROMPT},
                    {"role": "user", "content": user_query},
                ]
            )
        except Exception as exc:
            logger.exception("supervisor_entry: LLM criteria parsing failed")
            return {
                "error": f"Error parsing query: {exc}",
                "status_updates": state.get("status_updates", [])
                + ["❌ Error parsing query."],
            }

        if not parsed_c.criteria.strip():
            return {
                "error": "Please tell me what type of food or restaurant you are looking for (e.g. 'pizza', 'sushi', 'kebab').",
                "status_updates": state.get("status_updates", [])
                + ["❌ Missing search criteria."],
            }

        radius = (
            parsed_c.radius
            if parsed_c.radius is not None
            else settings.DEFAULT_SEARCH_RADIUS
        )

        # max_price_level comes from the frontend setup (not parsed from query)
        pre_set_budget: int | None = state.get("max_price_level")

        logger.info(
            "supervisor_entry: location=%s  criteria=%s  radius=%d  budget=%s  walk=%s",
            pre_set_location,
            parsed_c.criteria,
            radius,
            pre_set_budget,
            parsed_c.max_walk_minutes,
        )

        return {
            "user_location_text": pre_set_location,
            "search_criteria": parsed_c.criteria,
            "search_radius": radius,
            "max_price_level": pre_set_budget,
            "max_walk_minutes": parsed_c.max_walk_minutes,
            "status_updates": state.get("status_updates", [])
            + [f"🔍 Searching near {pre_set_location}..."],
        }

    # ── Path B: no pre-set location — extract both from query ────────────
    structured_llm = llm.with_structured_output(ParsedQuery)
    try:
        parsed: ParsedQuery = structured_llm.invoke(
            [
                {"role": "system", "content": _PARSE_SYSTEM_PROMPT},
                {"role": "user", "content": user_query},
            ]
        )
    except Exception as exc:
        logger.exception("supervisor_entry: LLM parsing failed")
        return {
            "error": f"Error parsing query: {exc}",
            "status_updates": state.get("status_updates", [])
            + ["❌ Error parsing query."],
        }

    if not parsed.location.strip() or not parsed.criteria.strip():
        logger.warning("supervisor_entry: missing location or criteria in query")
        return {
            "error": "Please specify a location and the type of food or place you are looking for (e.g., 'pizza near Times Square').",
            "status_updates": state.get("status_updates", [])
            + ["❌ Missing location or search criteria."],
        }

    radius = (
        parsed.radius
        if parsed.radius is not None
        else settings.DEFAULT_SEARCH_RADIUS
    )

    logger.info(
        "supervisor_entry: location=%s  criteria=%s  radius=%d",
        parsed.location,
        parsed.criteria,
        radius,
    )

    logger.info(
        "supervisor_entry: max_price_level=%s  max_walk_minutes=%s",
        parsed.max_price_level,
        parsed.max_walk_minutes,
    )

    return {
        "user_location_text": parsed.location,
        "search_criteria": parsed.criteria,
        "search_radius": radius,
        "max_price_level": parsed.max_price_level,
        "max_walk_minutes": parsed.max_walk_minutes,
        "status_updates": state.get("status_updates", [])
        + ["🔍 Analyzing your query..."],
    }


def supervisor_exit(state: AgentState) -> dict:
    """Assemble the final JSON response with a Persian chat message.

    If an error was set by an earlier node, propagates the error in a
    user-friendly response.
    """
    logger.info("supervisor_exit: building final response")

    places: list[dict] = state.get("shortlisted_places", [])
    error: str | None = state.get("error")

    # ── Handle error / empty results ────────────────────────────────────
    if error:
        return {
            "final_response": {
                "chat_message": f"Unfortunately, an error occurred: {error}",
                "places": [],
            },
            "status_updates": state.get("status_updates", [])
            + ["✅ Results are ready!"],
        }

    if not places:
        return {
            "final_response": {
                "chat_message": (
                    "No places matching your search were found. "
                    "Please try increasing the search radius or trying a different keyword."
                ),
                "places": [],
            },
            "status_updates": state.get("status_updates", [])
            + ["✅ Results are ready!"],
        }

    # ── Build a textual summary for the LLM ─────────────────────────────
    _PRICE_LABELS = {0: "Free", 1: "€", 2: "€€", 3: "€€€", 4: "€€€€"}

    summary_lines: list[str] = []
    for idx, place in enumerate(places, start=1):
        price_level = place.get("price_level")
        price_str = (
            _PRICE_LABELS.get(price_level, "Unknown")
            if price_level is not None
            else "Not available in Google data"
        )
        review_summary = place.get("recent_reviews_summary") or "No reviews available."
        summary_lines.append(
            f"{idx}. {place.get('name', 'N/A')}\n"
            f"   Distance: {place.get('distance_text', 'N/A')}\n"
            f"   Travel time: {place.get('duration_text', 'N/A')}\n"
            f"   Rating: {place.get('rating', 'N/A')}\n"
            f"   Price level (from Google): {price_str}\n"
            f"   Review summary: {review_summary}"
        )

    places_summary = "\n\n".join(summary_lines)

    llm = ChatOpenAI(
        model=settings.LLM_MODEL,
        temperature=0,
        api_key=settings.OPENAI_API_KEY,
    )

    try:
        ai_message = llm.invoke(
            [
                {"role": "system", "content": _FINAL_RESPONSE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Number of results: {len(places)}\n\n"
                        f"DATA (use only this, add nothing):\n{places_summary}"
                    ),
                },
            ]
        )
        chat_message: str = ai_message.content.strip()
    except Exception as exc:
        logger.exception("supervisor_exit: LLM response generation failed")
        chat_message = (
            f"I found {len(places)} places for you. "
            "Check the cards below for details."
        )

    # ── Build the places payload (only the fields the frontend needs) ───
    _PRICE_SYMBOLS = {0: "Free", 1: "€", 2: "€€", 3: "€€€", 4: "€€€€"}
    user_asked_price = state.get("max_price_level") is not None

    response_places: list[dict] = []
    for place in places:
        price_level = place.get("price_level")
        price_range_text = place.get("price_range_text")
        if price_level is not None:
            price_label = _PRICE_SYMBOLS.get(price_level, str(price_level))
        elif price_range_text:
            # New Places API returned a text range like "€10–20"
            price_label = price_range_text
        elif user_asked_price:
            price_label = "no price on Google"
        else:
            price_label = None

        response_places.append(
            {
                "name": place.get("name", ""),
                "address": place.get("address", ""),
                "coordinates": place.get("coordinates", {}),
                "rating": place.get("rating", 0.0),
                "distance_text": place.get("distance_text", ""),
                "duration_text": place.get("duration_text", ""),
                "price_level": price_level,
                "price_range_text": price_range_text,
                "price_label": price_label,
                "transit_lines": place.get("transit_lines", []),
                "recent_reviews_summary": place.get("recent_reviews_summary", ""),
                "review_source": place.get("review_source", ""),
                "google_maps_url": place.get("google_maps_url", ""),
            }
        )

    return {
        "final_response": {
            "chat_message": chat_message,
            "places": response_places,
        },
        "status_updates": state.get("status_updates", [])
        + ["✅ Results are ready!"],
    }
