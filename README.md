# Rule Engine API

FastAPI service for discovering trading rules from historical trade data using Anthropic Claude.

## Setup

```bash
pip install -r requirements.txt
```

Set required environment variables (see `.env.example`):
- `ANTHROPIC_API_KEY` - Anthropic API key for Claude
- `BRIGHTDATA_API_KEY` - Bright Data API key for news fetching (optional)
- `BRIGHTDATA_ZONE` - Bright Data zone (optional)
- `DAYTONA_API_KEY` - Daytona API key for sandbox execution (optional, falls back to local subprocess)

## Run locally

```bash
uvicorn main:app --reload
```

## Run with Docker

```bash
docker build -t rule-engine .
docker run -p 8000:8000 -e PORT=8000 rule-engine
```

## API Endpoints

- `POST /runs` - Start a new rule discovery run
  - Body: `{"dataset":"sample"}` to use `data/sample_trades.csv`
  - Body: `{"trades_csv":"<text>"}` to upload custom CSV data
  - Returns: `{"run_id": "..."}`
- `GET /runs/{run_id}` - Get run status and results
  - Returns full discovery result with hypotheses, exceptions, and summary
  - Never returns rule source (`rule_codes` is kept server-side only)
- `GET /gurus` - List precomputed gurus
  - Returns `[{id, name, style, bio, n_insights, holdout_match}]`
- `GET /gurus/{guru_id}` - Get a guru's public result (hypotheses, baseline, exceptions, summary, insights)
  - 404 if the guru does not exist; never returns rule source
- `POST /activate` - Activate an insight on follower trade data
  - Body: `{"run_id":"...","insight_id":"...","dataset":"follower_sample"}` or `{"guru_id":"...","insight_id":"...","dataset":"follower_sample"}`
  - Exactly one of `run_id` or `guru_id` is required (400 otherwise)
  - 404 for unknown run/guru/insight, 400 for insights without a rule or unknown dataset
- `GET /news?symbol=...&date=...` - Fetch news headlines (live Bright Data call, cached)
  - `symbol` is uppercased and must match `^[A-Z][A-Z0-9.\-]{0,9}$`; `date` must be `YYYY-MM-DD` (400 on invalid input)
  - Rate limited to 10 requests/minute per process; returns 429 when exceeded
- `GET /health` - Liveness check, returns `{"ok": true}`

## Discovery Process

The service:
1. Parses the trade CSV (columns: date, symbol, side, qty, price)
2. Builds historical features with no-lookahead guarantees
3. Splits data into discovery (70%) and holdout (30%) sets
4. Uses Claude to propose and test trading rules iteratively
5. Scores rules on both discovery and holdout data
6. Fills exception context from cached news headlines
7. Returns the discovered rules, exceptions, and performance summary

## Run tests

```bash
pytest
```

## News Caching

News headlines are fetched using Bright Data SERP API and cached in `data/news_cache.json`. The cache is read at request time to fill exception context without network calls. Run `python precompute_news.py` to pre-populate the cache for a dataset.

## Precomputed gurus

Run `python precompute_gurus.py` locally with `ANTHROPIC_API_KEY` set (never in CI). It uses the existing news cache only and writes `data/gurus/index.json`, `data/gurus/<id>.json` (public result served by the API), and `data/gurus/<id>.rules.json` (rule source, server-side only — used by `POST /activate` but never returned by any endpoint).
