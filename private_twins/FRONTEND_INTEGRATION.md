# Twin frontend integration

## Base URL and privacy

Set your Base44 server-side integration's `TWIN_ENGINE_API_BASE_URL` to the HTTPS backend URL (for example a temporary Cloudflare Tunnel URL while developing). Do not hard-code `localhost` into a deployed Base44 app. Keep the upload and private-analysis views private; never copy `/runs` output into public Twin profiles.

If a browser calls the backend directly, add the exact Base44 origin to `ALLOWED_ORIGINS`. Prefer Base44 server-side functions as a proxy for uploads, chat, and speech.

## Upload and polling

Upload a CSV as `multipart/form-data` with the field name `file`:

```text
POST {BASE_URL}/runs
```

The accepted response is HTTP 202:

```json
{"run_id":"uuid","status":"queued","progress":0}
```

Poll until terminal status:

```text
GET {BASE_URL}/runs/{run_id}
```

Show `queued`, `matching_lots`, `discovering_patterns`, then `complete`. For `completed`, save the returned run object as the latest private analysis. For `failed`, show `error`; do not silently substitute demo data.

## Completed result and charts

`result.charts` contains real aggregates from matched FIFO BUY-lot to SELL-lot quantities. A partial exit can therefore create several completed-exit units.

```json
{
  "charts": {
    "unit": "Each count represents a matched FIFO BUY-lot to SELL-lot quantity; partial exits can create multiple units.",
    "cumulative_pnl": [
      {"date":"2025-01-04","realized_pnl":80.0,"cumulative_pnl":80.0}
    ],
    "pnl_by_symbol": [
      {"symbol":"AAPL","realized_pnl":438.0,"completed_exits":5}
    ],
    "win_loss": [
      {"outcome":"win","count":5},
      {"outcome":"loss","count":1},
      {"outcome":"breakeven","count":0}
    ],
    "holding_duration": [
      {"bucket":"0–1 days","count":1},
      {"bucket":"2–3 days","count":3},
      {"bucket":"4–7 days","count":2},
      {"bucket":"8+ days","count":0}
    ],
    "limitations":["Cumulative realized P&L is not a portfolio equity curve."]
  }
}
```

Render charts only from these fields:

- `cumulative_pnl`: line/area chart. Label it **Cumulative realized P&L**, not portfolio value or equity curve.
- `pnl_by_symbol`: bar chart.
- `win_loss`: three-part bar or donut chart; label the unit as matched exit lots.
- `holding_duration`: bar chart; bucket boundaries are 0–<2, 2–<4, 4–<8, and 8+ days.

When `cumulative_pnl` is empty, display: “No matched exits are available for charting.” Never render fake points.

## Public demo Twin chat

Only fictional, public synthetic playbooks are available: `alex-demo` and `maya-demo`.

```text
POST {BASE_URL}/twins/alex-demo/chat
Content-Type: application/json
```

```json
{"message":"What is this Twin's typical holding period?"}
```

Successful response:

```json
{
  "twin_id":"alex-demo",
  "answer":"The published demo evidence shows a median holding period of three days.",
  "answer_id":"opaque-uuid-for-speech-only",
  "evidence":[
    {"pattern_id":"holding_duration","description":"Published demo evidence shows a median holding period of three days.","sample_size":6}
  ],
  "limitations":["Historical behavior does not predict future decisions."],
  "disclaimer":"This is an AI-generated interpretation of published historical evidence, not the real trader or financial advice."
}
```

Render the answer, evidence, limitations, and disclaimer together. A 503 response means `ANTHROPIC_API_KEY` is not configured; show “Public Twin chat is temporarily unavailable.” A 502 response means the provider failed; offer retry. Do not show a mock answer in either case.

## Fish Audio speech

Speech is intentionally bound to a previous server-generated chat answer. Do **not** send arbitrary text to speech.

```text
POST {BASE_URL}/twins/alex-demo/speak
Content-Type: application/json

{"answer_id":"the-answer_id-from-chat"}
```

The response body is browser-playable `audio/mpeg`. Create an object URL and play it:

```javascript
const response = await fetch(`${BASE_URL}/twins/alex-demo/speak`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ answer_id }),
});
if (!response.ok) throw new Error(await response.text());
const url = URL.createObjectURL(await response.blob());
new Audio(url).play();
```

Show “Demo synthetic voice — not the real creator’s voice.” A 503 means Fish Audio is not configured; keep text chat usable and hide/disable the play button with an explanation. A 400 means the answer ID is expired, invalid, or belongs to a different Twin.

## Base44 flow pseudocode

```javascript
const run = await twinUpload(file); // POST /runs, returns run_id
while (true) {
  const current = await twinGetRun(run.run_id);
  setRun(current);
  if (current.status === "completed") {
    localStorage.setItem("twin_latest_analysis", JSON.stringify(current));
    navigate(`/analysis/${current.run_id}`);
    break;
  }
  if (current.status === "failed") throw new Error(current.error);
  await new Promise(resolve => setTimeout(resolve, 1000));
}
```

Loading states: disable duplicate uploads while a run is pending. Empty states: show a clear upload call-to-action for no private analysis and a no-matched-exits message for empty charts. Error states: show backend `detail`/`error`, retain the selected file name, and offer retry.

All public creator profiles must be labeled **fictional demo data**. Do not send uploaded CSV rows, private patterns, or private evidence IDs into public creator chat.
