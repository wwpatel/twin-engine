import json
import os
import re
import uuid
from collections.abc import Callable

import pandas as pd

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
MAX_ROUNDS = 5
DISCOVERY_FRACTION = 0.7
MIN_MATCH = 0.65
MIN_COVERAGE = 0.10
OUTCOME_HORIZON_DAYS = 5
ANTHROPIC_TIMEOUT_SECONDS = 30
PRICE_DIR = "data/prices"

FEATURE_COLUMNS = [
    "ret_1d",
    "ret_3d",
    "ret_5d",
    "down_day_streak",
    "dist_from_ma20",
    "spy_ret_1d",
    "spy_ret_5d",
    "days_to_next_earnings",
]
RULE_INPUT_COLUMNS = ["date", "symbol"] + FEATURE_COLUMNS
VALID_ACTIONS = {"buy", "sell", None}

BASELINE_TEXT = "Buys after any down day (ret_1d < 0)"
BASELINE_CODE = """
def rule(row):
    ret = row.get("ret_1d")
    if ret is not None and ret < 0:
        return "buy"
    return None
"""

SYSTEM_PROMPT = (
    "You reverse-engineer the implicit trading rules of a single trader from "
    "summary statistics of their past trades. You propose one testable rule at a time."
)


def _make_client():
    import anthropic

    return anthropic.Anthropic()


def fetch_close_after(symbol: str, date: str, days: int = OUTCOME_HORIZON_DAYS) -> float | None:
    """Close `days` trading days after `date` (the trade date is day 0), or None if not cached.

    Reads only data/prices/<SYMBOL>.close.csv (see data/build_price_cache.py); never the network.
    """
    try:
        closes = _close_history(symbol)
    except Exception:
        return None
    if closes is None or closes.empty:
        return None
    pos = closes.index.searchsorted(pd.Timestamp(date).normalize()) + days
    if pos >= len(closes):
        return None
    return float(closes.iloc[pos])


_CLOSE_CACHE: dict = {}


def _close_history(symbol: str) -> pd.Series | None:
    if symbol not in _CLOSE_CACHE:
        path = os.path.join(PRICE_DIR, f"{symbol}.close.csv")
        if not os.path.exists(path):
            return None
        closes = pd.read_csv(path, index_col="date", parse_dates=["date"])["close"]
        _CLOSE_CACHE[symbol] = closes.sort_index()
    return _CLOSE_CACHE[symbol]


def run_discovery(trades_csv_path: str, on_progress: Callable[[dict], None]) -> dict:
    import features
    import parser
    import sandbox

    trades = parser.load_trades(trades_csv_path)
    order = sorted(range(len(trades)), key=lambda i: pd.Timestamp(trades[i]["date"]))
    trades = [trades[i] for i in order]

    df = features.build_features(trades, allow_fetch=False).reset_index(drop=True)
    if len(df) != len(trades):
        raise ValueError(f"build_features returned {len(df)} rows for {len(trades)} trades")
    sides = [t["side"] for t in trades]

    n_discovery = int(len(trades) * DISCOVERY_FRACTION)
    discovery_df = df.iloc[:n_discovery].reset_index(drop=True)
    holdout_df = df.iloc[n_discovery:].reset_index(drop=True)
    discovery_sides = sides[:n_discovery]
    holdout_sides = sides[n_discovery:]

    client = _make_client()
    feature_summary = summarize_features(discovery_df)

    hypotheses: list[dict] = []
    kept: list[dict] = []
    rule_codes: dict[str, str] = {}
    rule_index = 0
    round_num = 0
    for round_num in range(1, MAX_ROUNDS + 1):
        prompt = build_prompt(feature_summary, hypotheses)
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            timeout=ANTHROPIC_TIMEOUT_SECONDS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        hypothesis, actions = _evaluate_response(
            _response_text(response), sandbox, discovery_df, discovery_sides, holdout_df, holdout_sides
        )
        hypotheses.append(hypothesis)
        if hypothesis["status"] == "kept":
            rule_index += 1
            rule_code_id = f"r{rule_index}"
            rule_codes[rule_code_id] = hypothesis["code"]
            kept.append({
                "text": hypothesis["text"],
                "coverage": actions["coverage"],
                "actions": actions["all"],
                "rule_code_id": rule_code_id,
            })
        on_progress({"round": round_num, "hypotheses": [dict(h) for h in hypotheses]})

    baseline_actions = _run_rule_safely(sandbox, BASELINE_CODE, holdout_df)
    baseline_match = score(baseline_actions, holdout_sides)[0] if baseline_actions is not None else None
    baseline = {"text": BASELINE_TEXT, "holdout_match": baseline_match}

    exceptions, summary = _exceptions_and_summary(trades, kept)

    # Remove code from hypotheses before returning (stored in rule_codes instead)
    for h in hypotheses:
        h.pop("code", None)

    return {
        "run_id": uuid.uuid4().hex,
        "status": "done",
        "round": round_num,
        "hypotheses": hypotheses,
        "baseline": baseline,
        "exceptions": exceptions,
        "summary": summary,
        "rule_codes": rule_codes,
    }


def score(actions: list, sides: list) -> tuple[float | None, float]:
    """Return (match, coverage): match is the share of fired actions equal to the real side."""
    fired = [(a, s) for a, s in zip(actions, sides) if a is not None]
    coverage = len(fired) / len(sides) if sides else 0.0
    if not fired:
        return None, coverage
    return sum(a == s for a, s in fired) / len(fired), coverage


def summarize_features(df: pd.DataFrame) -> str:
    cols = [c for c in FEATURE_COLUMNS if c in df.columns]
    counts = df["side"].value_counts().to_dict()
    dates = pd.to_datetime(df["date"])
    lines = [
        f"Trades: {len(df)} (buys: {counts.get('buy', 0)}, sells: {counts.get('sell', 0)})",
        f"Date range: {dates.min().date()} to {dates.max().date()}" if len(df) else "Date range: n/a",
        "Most traded symbols: "
        + ", ".join(f"{s} ({n})" for s, n in df["symbol"].value_counts().head(10).items()),
        "",
        "Feature statistics by side:",
    ]
    if len(df) and cols:
        stats = df.groupby("side")[cols].describe(percentiles=[0.25, 0.5, 0.75])
        lines.append(stats.T.to_string(float_format=lambda v: f"{v:.4f}"))
    return "\n".join(lines)


def build_prompt(feature_summary: str, hypotheses: list[dict]) -> str:
    def fmt(status: str) -> str:
        rows = [f"- {h['text']} ({h['reason']})" for h in hypotheses if h["status"] == status]
        return "\n".join(rows) if rows else "- (none)"

    return f"""Summary of this trader's trades (discovery set):

{feature_summary}

Rules already kept:
{fmt("kept")}

Rules already rejected:
{fmt("rejected")}

Propose ONE new rule that is different from the rules above and predicts the trader's side.
The rule receives `row`, a dict with keys: {", ".join(RULE_INPUT_COLUMNS)}.
It must return "buy", "sell", or None (None means the rule does not apply to this trade).
A rule is kept only if it fires on at least {MIN_COVERAGE:.0%} of trades and its action matches
the real side in at least {MIN_MATCH:.0%} of the trades where it fires.

Respond in exactly this format:
<description>one-line plain-English description of the rule</description>
<code>
def rule(row):
    ...
</code>"""


def _response_text(response) -> str:
    return "".join(getattr(block, "text", "") for block in response.content)


def parse_rule_response(text: str) -> tuple[str | None, str | None]:
    desc = re.search(r"<description>(.*?)</description>", text, re.DOTALL)
    code = re.search(r"<code>(.*?)</code>", text, re.DOTALL)
    if code is None:
        code = re.search(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
    description = " ".join(desc.group(1).split()) if desc else None
    source = code.group(1) if code else None
    if source is not None:
        source = re.sub(r"^\s*```(?:python)?\s*\n|```\s*$", "", source.strip("\n"))
    return description, source


def _run_rule_safely(sandbox, code: str, df: pd.DataFrame) -> list | None:
    try:
        return sandbox.run_rule(code, _rule_input(df))
    except Exception:
        return None


def _rule_input(df: pd.DataFrame) -> pd.DataFrame:
    return df[[c for c in RULE_INPUT_COLUMNS if c in df.columns]]


def _evaluate_response(text, sandbox, discovery_df, discovery_sides, holdout_df, holdout_sides):
    description, code = parse_rule_response(text)
    hypothesis = {
        "text": description or "(unparseable rule)",
        "status": "rejected",
        "reason": "",
        "discovery_match": None,
        "holdout_match": None,
        "code": code,
    }
    if not description or not code or "def rule" not in code:
        hypothesis["reason"] = "Could not parse a description and a def rule(row) from the model response"
        return hypothesis, None

    try:
        discovery_actions = _validate_actions(sandbox.run_rule(code, _rule_input(discovery_df)), len(discovery_df))
    except Exception as e:
        hypothesis["reason"] = f"Rule raised an error on discovery data: {type(e).__name__}: {e}"[:500]
        return hypothesis, None

    match, coverage = score(discovery_actions, discovery_sides)
    hypothesis["discovery_match"] = match
    if coverage < MIN_COVERAGE:
        hypothesis["reason"] = f"Fired on only {coverage:.0%} of discovery trades (needs {MIN_COVERAGE:.0%})"
        return hypothesis, None
    if match < MIN_MATCH:
        hypothesis["reason"] = f"Matched {match:.0%} of discovery trades where it fired (needs {MIN_MATCH:.0%})"
        return hypothesis, None

    try:
        holdout_actions = _validate_actions(sandbox.run_rule(code, _rule_input(holdout_df)), len(holdout_df))
    except Exception as e:
        hypothesis["reason"] = f"Rule raised an error on holdout data: {type(e).__name__}: {e}"[:500]
        return hypothesis, None

    hypothesis["status"] = "kept"
    hypothesis["reason"] = (
        f"Matched {match:.0%} of discovery trades where it fired (fired on {coverage:.0%})"
    )
    hypothesis["holdout_match"] = score(holdout_actions, holdout_sides)[0]
    return hypothesis, {"coverage": coverage, "all": discovery_actions + holdout_actions}


def _validate_actions(actions, expected_len: int) -> list:
    actions = list(actions)
    if len(actions) != expected_len:
        raise ValueError(f"rule returned {len(actions)} results for {expected_len} rows")
    bad = {a for a in actions if a not in VALID_ACTIONS}
    if bad:
        raise ValueError(f"rule returned invalid actions: {sorted(map(repr, bad))}")
    return actions


def _outcome_pct(trade: dict) -> float | None:
    close = fetch_close_after(trade["symbol"], trade["date"])
    price = float(trade["price"])
    if close is None or price <= 0:
        return None
    pct = (close / price - 1.0) * 100.0
    return round(pct if trade["side"] == "buy" else -pct, 2)


def _mean(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 2) if values else None


def _load_news_cache() -> dict:
    """The precomputed news cache; never touches the network."""
    import news

    try:
        with open(news.CACHE_PATH) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _exceptions_and_summary(trades: list[dict], kept: list[dict]) -> tuple[list[dict], dict]:
    if not kept:
        # Without a kept rule nothing can be "broken": do not label every trade an exception.
        return [], {
            "followed_pct": 0.0,
            "return_when_followed": None,
            "return_when_broken": None,
            "note": "No rule met the match and coverage thresholds, so there are no exceptions to report.",
        }

    news_cache = _load_news_cache()
    broke_rule = max(kept, key=lambda k: k["coverage"])["text"]
    exceptions = []
    followed_returns, broken_returns = [], []
    for i, trade in enumerate(trades):
        explained = any(k["actions"][i] == trade["side"] for k in kept)
        outcome = _outcome_pct(trade)
        if explained:
            followed_returns.append(outcome)
            continue
        broken_returns.append(outcome)

        # Fill context from the news cache only: a miss must never trigger a live request
        headlines = news_cache.get(f"{trade['symbol']}|{trade['date']}")
        context = [h["title"] for h in headlines] if headlines else ["No clear cause in the news"]

        exceptions.append({
            "date": trade["date"],
            "symbol": trade["symbol"],
            "side": trade["side"],
            "broke_rule": broke_rule,
            "context": context,
            "outcome_pct": outcome,
        })
    summary = {
        "followed_pct": (len(trades) - len(exceptions)) / len(trades) if trades else 0.0,
        "return_when_followed": _mean(followed_returns),
        "return_when_broken": _mean(broken_returns),
    }
    return exceptions, summary
