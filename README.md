# Olivia — AI Restaurant Finder

A minimal, AI-powered restaurant discovery app. Tell it what you want to eat and how far you're willing to walk; it finds the best nearby options with real review summaries and transit directions.

Built with **FastAPI + LangGraph** on the backend and a plain **WebSocket SPA** on the frontend. No framework, no bundler.

---

## Features

- **Multi-agent pipeline** — query parsing → geo-search → review analysis → final response, all streamed live via WebSocket
- **Google Maps integration** — Places Text Search, Geocoding, Distance Matrix
- **Transit line details** — shows exact metro/RER/bus lines and stop counts per restaurant *(requires Directions API — see below)*
- **Review scraping** — Playwright scrapes Google Maps reviews when the Places API has no recent ones; works across French, Persian, and English reviews
- **LLM review summaries** — GPT-4.1-mini condenses reviews into 1–2 factual sentences
- **Budget filter** — set once at setup; only restaurants within your price level are returned
- **Walk-time filter** — mention a walking limit in chat (e.g. *"sushi 20 min walk"*) and results are filtered automatically
- **Dark / Light theme** — switchable from the side panel, persisted in localStorage

---

## Architecture

```
User (browser)
    │  WebSocket
    ▼
FastAPI  (/ws/chat)
    │
    ▼
LangGraph pipeline
    ├── supervisor_entry   — parse criteria from query
    ├── geo_mapping        — geocode → Places search → Distance Matrix → transit lines
    ├── review_analyst     — Google API reviews → Playwright fallback → LLM summary
    └── supervisor_exit    — assemble final JSON response
```

```
OliviaMapAssistant/
├── .env.example               # Copy to .env and fill in keys
├── requirements.txt
├── backend/
│   ├── main.py                # FastAPI app, WebSocket handler
│   ├── config.py              # pydantic-settings config
│   ├── agents/
│   │   ├── state.py           # AgentState TypedDict
│   │   ├── graph.py           # LangGraph graph definition
│   │   ├── supervisor.py      # Entry (query parse) + Exit (response build)
│   │   ├── geo_mapping.py     # Geocode, Places search, distances, transit lines
│   │   └── review_analyst.py  # Review fetch, Playwright scrape, LLM summarise
│   └── tools/
│       ├── geocoding.py
│       ├── places.py          # Places Text Search + Places API (New) price range
│       ├── distance_matrix.py # Distance Matrix + Directions API transit lines
│       └── review_scraper.py  # Sync Playwright scraper (runs in thread pool)
└── frontend/
    ├── index.html
    ├── style.css              # CSS variable–based dark/light theme
    └── app.js                 # WebSocket client, 2-step setup modal, card rendering
```

---

## Setup

### 1. Clone and create `.env`

```bash
git clone <repo-url>
cd OliviaMapAssistant
cp .env.example .env
```

Edit `.env` and add your keys:

```env
GOOGLE_MAPS_API_KEY=...
OPENAI_API_KEY=...
```

### 2. Enable Google Cloud APIs

In [Google Cloud Console](https://console.cloud.google.com/) → **APIs & Services → Enable APIs**, enable:

| API | Used for |
|-----|----------|
| Geocoding API | Convert address → coordinates |
| Places API | Restaurant search + details |
| Distance Matrix API | Walking & transit travel times |
| Directions API | Metro/bus line details *(optional)* |
| Places API (New) | Text price range e.g. €10–20 *(optional)* |

The two optional APIs gracefully degrade — the app works without them, just without line names and text price ranges.

### 3. Install dependencies

```bash
python -m venv venv

# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
playwright install chromium
```

### 4. Run

```bash
uvicorn backend.main:app --reload
```

Open [http://localhost:8000](http://localhost:8000).

---

## Usage

1. **First visit** — a setup modal asks for your address, then your budget (Any / € / €€ / €€€ / €€€€).
2. **Chat** — type what you want and optionally a walking limit:
   - `sushi`
   - `iranian restaurant 25 min walk`
   - `cheap ramen`
3. **Cards** — each result shows address, walking time, transit lines (Metro 6 · 3 stops), and an AI review summary.
4. **Theme** — click 🌙 / ☀️ in the side panel to switch themes.
5. **Edit settings** — click the location bar in the header to change address or budget.

---

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GOOGLE_MAPS_API_KEY` | ✅ | — | Google Maps API key |
| `OPENAI_API_KEY` | ✅ | — | OpenAI API key |
| `DEFAULT_SEARCH_RADIUS` | | `1500` | Search radius in metres |
| `MAX_RESULTS` | | `3` | Number of restaurants returned |
| `REVIEW_SCRAPE_TIMEOUT` | | `30` | Playwright page load timeout (seconds) |
| `LLM_MODEL` | | `gpt-4.1-mini` | OpenAI model for summaries |

---

## Notes

- **Windows compatibility** — Playwright uses the sync API inside `asyncio.to_thread()` to avoid the Windows event-loop subprocess limitation.
- **Review language** — the scraper and LLM handle French, Persian, and English reviews; summaries are always written in English.
- **Price filtering** — budget is set once at setup and sent with every query; the LLM never guesses prices.
