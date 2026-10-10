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
