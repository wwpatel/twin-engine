# Rule Engine API

FastAPI service for running trading rule evaluations.

## Setup

```bash
pip install -r requirements.txt
```

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

- `POST /runs` - Start a new run (body: `{"dataset":"sample"}` or `{"trades_csv":"<text>"}`)
- `GET /runs/{run_id}` - Get run status and results

## Run tests

```bash
pytest
```
