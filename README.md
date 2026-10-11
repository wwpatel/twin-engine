# Twin Engine — Phase 3

Twin is an AI-powered trading-behavior discovery product. This backend accepts a trade CSV, creates an asynchronous run, and performs deterministic Decision DNA analysis with real aggregate charts. It also exposes opt-in, provider-configured public fictional-Twin chat and speech endpoints. It does not place trades, call brokerages, or make claims about a trader's intent.

## Architecture

`POST /runs` validates and chronologically sorts an uploaded CSV, then adds a process-local job to FastAPI's background-task runner. `RunManager` protects the in-memory run map with a thread lock. The job uses FIFO matching per symbol, including partial exits, to calculate only supported realized P&L and holding periods. It returns patterns plus chart datasets for cumulative realized P&L, P&L by symbol, win/loss distribution, and holding-duration buckets.

State is temporary: a restart clears all runs. Run one Uvicorn worker only; multiple workers do not share the in-memory store.

## Local setup

```bash
cd /path/to/twin/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Set `ALLOWED_ORIGINS` to a comma-separated allowlist, for example `https://your-app.base44.app,http://localhost:3000`. CORS is disabled unless an origin is explicitly configured.

Run tests with `pytest`.

## API

`GET /health` returns `{"status":"ok","service":"twin-engine"}`.

`POST /runs` accepts multipart form field `file`. CSVs must be UTF-8, at most 5 MB, nonempty, and contain `date,symbol,side,qty,price`; side is `BUY` or `SELL`, and quantity and price must be finite positive numbers.

```bash
curl -F 'file=@trades.csv' http://localhost:8000/runs
curl http://localhost:8000/runs/RUN_ID
```

Responses expose `run_id`, `status`, `progress`, `current_stage`, `result`, and `error`. Pending runs have `result: null`; missing IDs return 404. A completed `result.summary` includes realized P&L, realized return percentage, win rate, and average winning/losing matched lot. `hypotheses`, `patterns`, and `exceptions` contain only computed observations and references such as `T003`, not raw CSV rows.

`result.charts.cumulative_pnl` is cumulative **realized** P&L from matched exits only. It is not a portfolio equity curve; it excludes open lots, unrealized P&L, and unmatched quantities. See [FRONTEND_INTEGRATION.md](FRONTEND_INTEGRATION.md) for exact chart schemas and UI labels.

## Public fictional-Twin chat and speech

`POST /twins/{twin_id}/chat` is available for the fictional public demo Twins `alex-demo` and `maya-demo`. It requires `OPENAI_API_KEY`, returns only deterministic selected public playbook evidence, and never reads private run output. If the key is absent, it returns a clear 503 configuration error.

`POST /twins/{twin_id}/speak` requires an `answer_id` returned by chat. It does not accept arbitrary text, preventing an unrestricted TTS proxy. It uses Fish Audio only when `FISH_AUDIO_API_KEY` and the approved synthetic `FISH_AUDIO_REFERENCE_ID` are configured. Fish Audio is optional; chat remains independent of it.

Never use a real person's voice without explicit consent. Label public profiles and voices as fictional/synthetic demo data.

Use [demo_trades.csv](backend/examples/demo_trades.csv) for a meaningful local example:

```bash
curl -F 'file=@examples/demo_trades.csv' http://localhost:8000/runs
```

Every pattern is retrieval-ready for a future public AI Twin: it includes a structured explanation, private supporting trade IDs, exceptions, and limitations. Pattern data is an internal evidence record, not a public playbook. Any future assistant must use verified historical evidence, avoid inferring intent, and never claim to be the trader.

## Docker and deployment

```bash
cd backend
docker build -t twin-engine .
docker run -p 8000:8000 -e PORT=8000 -e ALLOWED_ORIGINS=https://your-app.base44.app twin-engine
```

The production command is `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (one worker).

On Render, create a Docker Web Service from this repo, set `PORT` (Render supplies it in many configurations), and set `ALLOWED_ORIGINS` to the Base44 app URL. On Railway, deploy this Dockerfile, expose the generated service domain, and add the same `ALLOWED_ORIGINS` variable. Do not add a second Uvicorn worker while using this in-memory MVP.

## Known limitations and next phases

State is still in memory and disappears on restart; run one Uvicorn worker only. FIFO matching cannot assign cost basis to a SELL that exceeds prior uploaded BUY quantity, so that quantity is clearly flagged and excluded from realized P&L. Open lots are not treated as completed outcomes. The analysis contains no market-condition triggers and `news_context` remains empty until Bright Data is integrated.

Later phases can add normalized persistent storage, historical-market and Bright Data enrichment, a configurable LLM proposal layer that is validated deterministically, and separately consented public playbooks. Marketplace, public chat, creator profiles, authentication, and payments are explicitly out of scope.
