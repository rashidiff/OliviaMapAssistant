"""Review analyst agent node – analyse reviews and check user conditions.

For every shortlisted place this node:
1. Uses reviews fetched from the Google Places API (reliable).
2. Falls back to Playwright scraping only if API reviews are empty.
3. Sends the reviews to GPT-4.1 mini for:
   - A concise English summary (sentiment, quality, service).
   - A check on whether user-specified conditions/preferences
     (e.g. AC, outdoor seating, vegan options) are mentioned in reviews.
4. Stores the summary back into the shared state.
"""

from __future__ import annotations

import asyncio
import logging
import time
from copy import deepcopy

from langchain_openai import ChatOpenAI

from backend.agents.state import AgentState
from backend.config import settings
from backend.tools.review_scraper import scrape_reviews

logger = logging.getLogger(__name__)

_REVIEW_ANALYSIS_SYSTEM_PROMPT = """\
You are a restaurant review analyst. Reviews may be in any language \
(French, Persian, English, etc.) — read them all and write your summary in English.

STRICT RULES:
- Only report what is explicitly written in the review texts provided.
- Do NOT mention prices, hours, or distance — those come from other data sources.
- Do NOT infer or guess. No "likely", "probably", "seems", "typically".
- If reviews are positive, say so briefly. If complaints exist, state them.
- Write exactly 1–2 sentences. Be direct and factual.

Output: one plain paragraph, no labels, no bullets.
"""

_NO_REVIEWS_MESSAGE = "No reviews available for analysis."

# Reviews older than this many seconds are excluded (30 days)
_MAX_REVIEW_AGE_SECONDS = 30 * 24 * 60 * 60


def _filter_recent_api_reviews(api_reviews: list[dict]) -> list[dict]:
    """Filter Google Places API reviews to only those from the last 30 days."""
    if not api_reviews:
        return []

    now = time.time()
    recent = []
    for rev in api_reviews:
        review_time = rev.get("time", 0)
        if now - review_time <= _MAX_REVIEW_AGE_SECONDS:
            recent.append(rev)

    return recent


def _format_api_reviews(api_reviews: list[dict]) -> list[str]:
    """Convert Google Places API review dicts into readable text lines."""
    lines = []
    for rev in api_reviews:
        author = rev.get("author_name", "Anonymous")
        rating = rev.get("rating", "?")
        text = rev.get("text", "").strip()
        time_desc = rev.get("relative_time_description", "")
        if text:
            lines.append(f"- [{rating}⭐] {author} ({time_desc}): {text}")
    return lines


async def _analyse_single_place(
    place: dict,
    llm: ChatOpenAI,
    user_query: str,
) -> dict:
    """Analyse reviews for a single place.

    Strategy:
    1. Use recent reviews from the Google Places API (most reliable).
    2. If no recent API reviews, fall back to ALL API reviews (may be older).
    3. If still empty, try Playwright scraping as last resort.
    4. Send combined reviews to the LLM for summary + condition matching.
    5. Record the review source so the frontend can display it.
    """
    place = deepcopy(place)
    name = place.get("name", "Unknown")
    url = place.get("google_maps_url", "")
    review_source = ""

    # ── Step 1: Try recent API reviews ──────────────────────────────
    api_reviews = place.get("api_reviews", [])
    recent_api = _filter_recent_api_reviews(api_reviews)
    review_lines = _format_api_reviews(recent_api)

    if review_lines:
        review_source = f"Google API · {len(recent_api)} recent"
        logger.info(
            "review_analyst: %s — using %d recent API reviews", name, len(recent_api)
        )
    elif api_reviews:
        # Fall back to all API reviews even if older
        review_lines = _format_api_reviews(api_reviews)
        review_source = f"Google API · {len(api_reviews)} (older)"
        logger.info(
            "review_analyst: %s — no recent API reviews; using %d older API reviews",
            name, len(api_reviews),
        )

    # ── Step 2: Fallback to Playwright scraping ──────────────────────
    if not review_lines and url:
        logger.info(
            "review_analyst: %s — no API reviews; attempting Playwright scrape", name
        )
        try:
            scraped: list[dict] = await scrape_reviews(url)
            # Scraper returns all reviews without a recency filter;
            # use all of them (up to 15) for the summary.
            usable = [r for r in scraped if r.get("text", "").strip()]
            for rev in usable[:15]:
                text = rev.get("text", "").strip()
                rating = rev.get("rating", "")
                date = rev.get("date", "")
                line = f"- [{rating}⭐]"
                if date:
                    line += f" ({date})"
                line += f": {text}"
                review_lines.append(line)
            if review_lines:
                review_source = f"Web scrape · {len(usable)} reviews"
                logger.info(
                    "review_analyst: %s — scraped %d reviews", name, len(usable)
                )
            else:
                logger.warning(
                    "review_analyst: %s — scrape returned 0 usable reviews", name
                )
        except Exception as exc:
            logger.warning(
                "review_analyst: scraping fallback failed for %s: %s", name, exc
            )

    # ── Step 3: Store metadata ───────────────────────────────────────
    place["recent_reviews"] = recent_api or api_reviews
    place["review_source"] = review_source

    # ── Step 4: Summarise with LLM ───────────────────────────────────
    if not review_lines:
        logger.warning("review_analyst: %s — no reviews available from any source", name)
        place["recent_reviews_summary"] = _NO_REVIEWS_MESSAGE
        place["review_source"] = "No reviews found"
        return place

    combined = "\n".join(review_lines[:20])  # Cap to avoid token overflow

    try:
        ai_msg = await llm.ainvoke(
            [
                {"role": "system", "content": _REVIEW_ANALYSIS_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Restaurant: {name}\n"
                        f"User's search query: \"{user_query}\"\n\n"
                        f"Reviews:\n{combined}"
                    ),
                },
            ]
        )
        place["recent_reviews_summary"] = ai_msg.content.strip()
    except Exception as exc:
        logger.exception(
            "review_analyst: LLM summarisation failed for %s", name
        )
        place["recent_reviews_summary"] = _NO_REVIEWS_MESSAGE

    return place


async def review_analyst_node(state: AgentState) -> dict:
    """Analyse reviews for every shortlisted place concurrently.

    Uses Google Places API reviews as the primary source and Playwright
    scraping as a fallback. Also checks user-specific conditions in
    the reviews (RAG-style relevance matching).
    """
    logger.info("review_analyst_node: starting")

    places: list[dict] = state.get("shortlisted_places", [])
    user_query: str = state.get("user_query", "")

    if not places:
        logger.info("review_analyst_node: no places to analyse")
        return {
            "shortlisted_places": [],
            "status_updates": state.get("status_updates", [])
            + ["📝 Review analysis completed..."],
        }

    llm = ChatOpenAI(
        model=settings.LLM_MODEL,
        temperature=0,
        api_key=settings.OPENAI_API_KEY,
    )

    # Run all analyse tasks concurrently
    tasks = [
        _analyse_single_place(place, llm, user_query)
        for place in places
    ]
    updated_places: list[dict] = await asyncio.gather(*tasks)

    logger.info(
        "review_analyst_node: analysed reviews for %d places",
        len(updated_places),
    )

    return {
        "shortlisted_places": updated_places,
        "status_updates": state.get("status_updates", [])
        + ["📝 Review analysis completed..."],
    }
