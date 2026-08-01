# Production Notes

## Required controls

- Set `CORS_ALLOWED_ORIGINS` to the exact production origin list.
- Keep `.env` out of git and rotate exposed Google/OpenAI keys immediately.
- Enable request logging at the platform edge and keep application logs structured.
- Run `python -m pytest` before deploy.

## Recommended platform setup

- Health check path: `/health`
- Start command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
- Required services: Google Maps APIs, OpenAI API, outbound HTTPS access.
- Docker: build with `docker build -t olivia-map-assistant .` and run with env vars mounted at runtime.

## Cost and latency controls

- Keep API caching enabled for geocoding, place search, transit routes, and distance matrix.
- Keep `MAX_RESULTS` conservative unless you also add rate limiting.
- Prefer API reviews first; Playwright scraping should remain a fallback because it is slower.

## Future hardening

- Add user authentication before storing favorites or history.
- Add per-session rate limits for WebSocket requests.
- Move cache storage to Redis if the app runs across multiple processes.
