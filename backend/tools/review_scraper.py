"""Review scraper – extracts Google Maps reviews via Playwright (sync API).

On Windows, Playwright cannot launch a subprocess inside an already-running
asyncio event loop (FastAPI/uvicorn). We use the *synchronous* Playwright API
inside a thread executor (`asyncio.to_thread`) to avoid this restriction.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

from playwright.sync_api import sync_playwright, Page, BrowserContext
from playwright_stealth import Stealth

from backend.config import settings

logger = logging.getLogger(__name__)


def _human_sleep(low: float = 0.6, high: float = 1.8) -> None:
    time.sleep(random.uniform(low, high))


_EXTRACT_REVIEWS_JS = """
() => {
    const reviews = [];
    const blocks = document.querySelectorAll('[data-review-id]');

    blocks.forEach(block => {
        // Rating from aria-label
        let rating = 0;
        const ratingEl = block.querySelector('[role="img"][aria-label]');
        if (ratingEl) {
            const m = (ratingEl.getAttribute('aria-label') || '').match(/([1-5])/);
            if (m) rating = parseInt(m[1]);
        }

        // Date — look for a short span whose text matches a relative-date pattern
        let dateText = '';
        const dateKeywords = [
            'ago', 'week', 'month', 'year', 'day', 'hour',
            'semaine', 'mois', 'an ', 'jour', 'heure',
            'پیش', 'ساعت', 'روز',
            'هفته', 'ماه', 'سال',
            'hace', 'semana', 'mes',
            'woche', 'monat', 'jahr',
        ];
        for (const span of block.querySelectorAll('span')) {
            const t = (span.innerText || span.textContent || '').trim();
            if (t.length > 0 && t.length < 50 &&
                dateKeywords.some(k => t.toLowerCase().includes(k))) {
                dateText = t;
                break;
            }
        }

        // Review text — longest text node inside the block
        let reviewText = '';
        for (const span of block.querySelectorAll('span')) {
            const t = (span.innerText || span.textContent || '').trim();
            if (t.length > reviewText.length && t.length > 20) {
                reviewText = t;
            }
        }

        if (reviewText) {
            reviews.push({ rating, date: dateText, text: reviewText });
        }
    });

    return reviews;
}
"""


def _scrape_sync(google_maps_url: str, max_scrolls: int) -> list[dict[str, Any]]:
    """Blocking Playwright scrape — run this in a thread executor."""
    logger.info("_scrape_sync: starting for %s", google_maps_url)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context: BrowserContext = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1366, "height": 768},
            )
            page: Page = context.new_page()
            Stealth().apply_stealth_sync(page)

            timeout_ms = settings.REVIEW_SCRAPE_TIMEOUT * 1000
            page.goto(google_maps_url, wait_until="domcontentloaded", timeout=timeout_ms)
            _human_sleep(1.5, 3.0)

            # ── Click Reviews tab ──────────────────────────────────────
            tab_texts = ["Reviews", "Avis", "نظرات", "Bewertungen", "Recensioni"]
            for text in tab_texts:
                try:
                    btn = page.locator(f'button[role="tab"]:has-text("{text}")').first
                    if btn.is_visible(timeout=2000):
                        btn.click()
                        logger.info("_scrape_sync: clicked reviews tab (%s)", text)
                        break
                except Exception:
                    continue

            # Also try data-tab-index
            try:
                btn = page.locator('button[role="tab"][data-tab-index="1"]').first
                if btn.is_visible(timeout=1500):
                    btn.click()
            except Exception:
                pass

            _human_sleep(1.0, 2.0)

            # ── Sort by Newest ─────────────────────────────────────────
            sort_labels = [
                "Sort reviews", "Trier les avis", "مرتب‌سازی نظرات",
                "Ordina le recensioni", "Rezensionen sortieren",
            ]
            sorted_ok = False
            for label in sort_labels:
                try:
                    btn = page.locator(f'button[aria-label="{label}"]').first
                    if btn.is_visible(timeout=1500):
                        btn.click()
                        sorted_ok = True
                        break
                except Exception:
                    continue

            if not sorted_ok:
                for text in ["Most relevant", "Les plus pertinents", "مرتبط‌ترین"]:
                    try:
                        btn = page.locator(f'button:has-text("{text}")').first
                        if btn.is_visible(timeout=1500):
                            btn.click()
                            sorted_ok = True
                            break
                    except Exception:
                        continue

            if sorted_ok:
                _human_sleep(0.5, 1.0)
                for newest_text in ["Newest", "Les plus récents", "جدیدترین", "Più recenti"]:
                    try:
                        item = page.locator(f'[role="menuitemradio"]:has-text("{newest_text}")').first
                        if item.is_visible(timeout=1500):
                            item.click()
                            logger.info("_scrape_sync: sorted by newest")
                            break
                    except Exception:
                        continue

            _human_sleep(1.0, 2.0)

            # ── Scroll to load reviews ─────────────────────────────────
            for _ in range(max_scrolls):
                try:
                    page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
                    _human_sleep(0.8, 1.4)
                except Exception:
                    break

            # Try scrolling the reviews panel specifically
            try:
                panel = page.locator('div[role="main"]').first
                if panel.is_visible(timeout=1000):
                    for _ in range(max_scrolls):
                        panel.evaluate("el => el.scrollBy(0, el.scrollHeight)")
                        _human_sleep(0.7, 1.2)
            except Exception:
                pass

            # ── Expand "More" buttons ──────────────────────────────────
            for more_text in ["More", "Plus", "بیشتر", "Altro", "Mehr"]:
                try:
                    btns = page.locator(f'button:has-text("{more_text}")')
                    count = btns.count()
                    for i in range(min(count, 12)):
                        try:
                            btns.nth(i).click(timeout=500)
                            time.sleep(0.1)
                        except Exception:
                            continue
                except Exception:
                    continue

            _human_sleep(0.5, 1.0)

            # ── Extract via JavaScript ─────────────────────────────────
            raw: list[dict] = page.evaluate(_EXTRACT_REVIEWS_JS)
            logger.info("_scrape_sync: JS found %d review blocks", len(raw))

            seen: set[str] = set()
            reviews: list[dict[str, Any]] = []
            for item in raw:
                text = item.get("text", "").strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                reviews.append({
                    "reviewer": "—",
                    "rating": item.get("rating", 0),
                    "date": item.get("date", ""),
                    "text": text,
                })
                if len(reviews) >= 20:
                    break

            browser.close()
            logger.info("_scrape_sync: returning %d unique reviews", len(reviews))
            return reviews

    except Exception as exc:
        logger.exception("_scrape_sync: failed: %s", exc)
        return []


async def scrape_reviews(
    google_maps_url: str,
    max_scrolls: int = 6,
) -> list[dict[str, Any]]:
    """Async wrapper — runs the sync Playwright scraper in a thread pool.

    This avoids the Windows asyncio limitation where subprocesses cannot be
    created inside a running event loop.
    """
    if not google_maps_url:
        logger.warning("scrape_reviews: called with empty URL")
        return []

    return await asyncio.to_thread(_scrape_sync, google_maps_url, max_scrolls)
