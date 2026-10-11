# Integration: one service, one URL

`main.py` (Backend A, the engine) mounts Backend B (`private_twins/backend`, private Twins) under **`/private`**.
A's paths are unchanged. B's `/health` is `/private/health`, `/twins` is `/private/twins`, and so on.
Interactive docs: `/docs` (A) and `/private/docs` (B). Paper only, not investment advice.

`BASE` below is your deployed URL, e.g. `https://twin.example.com`.

## Auth (only matters for `/private`; A has none)

| Mode | How the user is identified | No identity |
|---|---|---|
| `AUTH_MODE=development` (**default for this demo**) | header `X-Dev-User-Id: <any string>` | `/private/me/*` returns 401 `{"detail":"Sign in is required for private portfolios and conversations."}` |
| `DEMO_AUTH=1` (off by default), additionally | header `X-Demo-User: <id>` (1-100 chars of `A-Za-z0-9_.:@-`, else 400) | same 401 |
| `AUTH_MODE=clerk` | `Authorization: Bearer <Clerk session JWT>`, needs `CLERK_JWT_ISSUER` + `CLERK_JWKS_URL` (else 503) | 401 |

**Development mode is not secure.** The id is whatever the caller sends: anyone who knows or guesses another user's id
can read that user's portfolio, conversations and analysis. Different ids do not see each other's data (checked: a
second id gets 404 for the first's portfolio and conversation). `GET /private/runs/{run_id}` needs no identity at all;
the random run UUID is the only secret. Use synthetic data only, and switch to `AUTH_MODE=clerk` for anything real.
A Base44 app cannot produce a Clerk JWT, which is why the header modes exist.

## Environment variables (all optional; names only in `.env.example`)

| Variable | Default | If missing |
|---|---|---|
| `ANTHROPIC_API_KEY` | none | `POST /runs` runs end in `status:"error"`; `/private` twin chat returns 503 JSON |
| `ANTHROPIC_MODEL` | `claude-sonnet-5-5` | |
| `BRIGHTDATA_API_KEY`, `BRIGHTDATA_ZONE` | none | `GET /news` returns `source:"error"` (or cached items with `fallback=cache`) |
| `DAYTONA_API_KEY`, `DAYTONA_API_URL` | none | rule execution falls back as before |
| `ALLOWED_ORIGINS` | `*` | comma-separated list or `*`; the only CORS layer |
| `AUTH_MODE` | `development` | see Auth |
| `DEMO_AUTH` | unset (off) | `1` enables `X-Demo-User` |
| `CLERK_JWT_ISSUER`, `CLERK_JWKS_URL` | none | only used when `AUTH_MODE=clerk` |
| `DATABASE_PATH` | `/tmp/twin.sqlite3` | data resets on restart |
| `FISH_AUDIO_API_KEY`, `FISH_AUDIO_MODEL` (`s2.1-pro`) | none | `/speak` returns 503; text chat unaffected |
| `FISH_AUDIO_REFERENCE_ID`, `FISH_AUDIO_REFERENCE_ID_{ALEX,MAYA,JACK,LENA,DANIEL,SOFIA}_DEMO` | none | Fish Audio default voice. Use authorized synthetic voices only, never a real person's |
| `PORT` | `8000` | read by the Docker CMD |

B's own `ALLOWED_ORIGINS` handling and `PORT` are ignored. Storage: B uses SQLite at `DATABASE_PATH` plus in-memory run
and answer stores; A keeps runs in memory and writes `data/news_cache.json` on a live `/news` call. Run **one** worker.
The six demo twins are defined in code, so `/private/twins` is never empty after a restart. Only twins published
through `/private/me/creator-twin` are lost on restart.

## Backend A (paths unchanged)

| Method + path | Request | Response |
|---|---|---|
| `GET /health` | | `{"ok":true}` |
| `GET /gurus` | | `[{"id","name","style","bio","n_insights","holdout_match"}]` |
| `GET /gurus/{id}` | | the guru's public report (404 if unknown) |
| `POST /runs` | `{"dataset":"sample"}` or `{"trades_csv":"<csv text>"}` | `{"run_id":"..."}` |
| `GET /runs/{run_id}` | | `{"status":"running"\|"done"\|"error","run_id",...}`; done adds `hypotheses`, `exceptions`, `summary`, `insights` |
| `POST /activate` | `{"run_id" or "guru_id","insight_id","dataset"}` (exactly one of run_id/guru_id) | activation result (400/404 on bad input) |
| `GET /news?symbol=NVDA&date=2026-03-14[&fallback=cache]` | | `{"symbol","date","items":[{"title","source","published"}],"source":"live"\|"cache"\|"error"}`; 10 calls/minute |

```bash
curl $BASE/health
curl $BASE/gurus
curl $BASE/gurus/GURU_ID
curl -X POST $BASE/runs -H 'content-type: application/json' -d '{"dataset":"sample"}'
curl $BASE/runs/RUN_ID
curl -X POST $BASE/activate -H 'content-type: application/json' -d '{"guru_id":"GURU_ID","insight_id":"INSIGHT_ID","dataset":"sample"}'
curl "$BASE/news?symbol=NVDA&date=2026-03-14&fallback=cache"
```
A static example of a finished run is `data/sample_report.json` (no endpoint serves it).

## Backend B (under `/private`)

| Method + path | Auth | Request | Response |
|---|---|---|---|
| `GET /private/health` | no | | `{"status":"ok","service":"twin-engine"}` |
| `POST /private/runs` | optional | multipart `file` (`.csv`, <=5 MB, columns `date,symbol,side,qty,price`) | 202 `{"run_id","status":"queued","progress":0}`; with an identity it is saved as that user's private portfolio |
| `GET /private/runs/{run_id}` | no | | `{"run_id","status":"queued"\|"running"\|"completed"\|"failed","progress","current_stage","result","error"}`; `result` has `summary`, `patterns`, `exceptions`, `charts` |
| `GET /private/twins` | no | | `{"twins":[profile,...]}` |
| `GET /private/twins/{twin_id}` | no | | profile with `patterns`, `limitations`, `disclaimer` (404 unknown) |
| `POST /private/twins/{twin_id}/chat` | no | `{"message":"..."}` (1-1000 chars) | `{"twin_id","answer","answer_id","evidence":[{"pattern_id","description","sample_size"}],"limitations","disclaimer"}`; 503 `{"detail":...}` if no model key, 502 if the provider fails |
| `POST /private/twins/{twin_id}/speak` | no | `{"answer_id":"<from chat>"}` | `audio/mpeg`; 400 bad/expired id (10 min), 503 `{"detail":"Fish Audio is not configured. Set FISH_AUDIO_API_KEY."}` |
| `GET /private/me/portfolios/latest` | yes | | `{"run_id","analysis","created_at","updated_at"}` (404 if none) |
| `POST /private/me/creator-twin` | yes | `{"public_id","display_name","bio","communication_style","opening_message","explicit_publication_consent":true}` | 201 public profile built from the latest analysis |
| `POST /private/me/conversations` | yes | `{"twin_id","title"?}` | 201 `{"id","twin_id","title",...}` |
| `GET /private/me/conversations` | yes | | `{"conversations":[...]}` |
| `GET /private/me/conversations/{id}` | yes | | conversation with `messages` |
| `POST /private/me/conversations/{id}/messages` | yes | `{"message","include_my_portfolio":false}` | `{"conversation_id","user_message","assistant_message","portfolio_context_used","limitations","disclaimer"}` |

Demo twin ids: `alex-demo`, `maya-demo`, `jack-demo`, `lena-demo`, `daniel-demo`, `sofia-demo` (all fictional).
Speech needs a **previous chat answer**: it speaks only text the server generated, never arbitrary text.

```bash
H='X-Dev-User-Id: demo-user-1'   # or X-Demo-User when DEMO_AUTH=1
curl $BASE/private/health
curl $BASE/private/twins
curl -X POST $BASE/private/twins/alex-demo/chat -H 'content-type: application/json' -d '{"message":"How long do you hold?"}'
curl -X POST $BASE/private/twins/alex-demo/speak -H 'content-type: application/json' -d '{"answer_id":"ANSWER_ID"}' -o answer.mp3
curl -H "$H" -F file=@trades.csv $BASE/private/runs
curl $BASE/private/runs/RUN_ID
curl -H "$H" $BASE/private/me/portfolios/latest
curl -X POST -H "$H" $BASE/private/me/conversations -H 'content-type: application/json' -d '{"twin_id":"alex-demo"}'
curl -X POST -H "$H" $BASE/private/me/conversations/CONV_ID/messages -H 'content-type: application/json' -d '{"message":"Compare with me","include_my_portfolio":true}'
curl -X POST -H "$H" $BASE/private/me/creator-twin -H 'content-type: application/json' -d '{"public_id":"my-twin","display_name":"My Twin","bio":"Synthetic demo creator.","communication_style":"Calm and concise.","opening_message":"Hi, ask me about my published history.","explicit_publication_consent":true}'
```

## Chat provider

Twin chat uses the Anthropic SDK with `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL`. No key: 503 JSON `{"detail":"ANTHROPIC_API_KEY is not configured..."}`; provider failure: 502.
The system prompt already says "Never give investment advice" and restricts answers to the approved evidence; private-data
questions get a fixed refusal. Every response carries a disclaimer.

## Wording check

No "guaranteed" or "you should buy" in B. B's analysis labels a pattern "Observed profitable exits" (it counts past gains,
with a limitation note). It is left as is because the title and `type` id are part of B's response shape. Flagged.
