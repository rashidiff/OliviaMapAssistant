# Production Notes

## Required controls

- Set `CORS_ALLOWED_ORIGINS` to the exact production origin list.
- Keep `.env` out of git and rotate exposed Google/OpenAI keys immediately.
- Keep API keys in the deployment platform's secret manager; never bake them into the image.
- Enable request logging at the platform edge and keep application logs structured.
- Run `python -m pytest` before deploy.

## Recommended platform setup

- Health check path: `/health`
- Start command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
- Required services: Google Maps APIs, OpenAI API, outbound HTTPS access.
- Docker: build with `docker build -t olivia-map-assistant .` and run with env vars mounted at runtime.
- Mount persistent storage for `CHECKPOINT_DB_PATH` if conversation history should survive container restarts.

## Cost and latency controls

- Keep API caching enabled for geocoding, place search, transit routes, and distance matrix.
- Keep `MAX_RESULTS`, `WS_RATE_LIMIT_MESSAGES`, and `REVIEW_ANALYSIS_CONCURRENCY` conservative unless quotas are raised.
- Prefer API reviews first; Playwright scraping should remain a fallback because it is slower.

## Future hardening

- Add user authentication before storing favorites or history.
- Move checkpoint and cache storage to Redis/Postgres if the app runs across multiple processes.
