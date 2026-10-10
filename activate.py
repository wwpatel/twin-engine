"""Activate insights on follower trade data."""

import tempfile
from typing import Any

import pandas as pd

import features
import sandbox


OUTCOME_HORIZON_DAYS = 5


class NotFoundError(ValueError):
    """A run, guru, or insight that does not exist."""


def activate(run_store: dict, run_id: str, insight_id: str, dataset: str) -> dict:
    """Activate an insight on follower trade data.

    Args:
        run_store: The runs dictionary from main.py
        run_id: The run ID to load the rule from
        insight_id: The insight ID to activate
        dataset: The dataset to apply the rule to (e.g., "follower_sample")

    Returns:
        A dict with:
        - n_rule_applies: number of trades where the rule fired
        - already_follows_pct: percentage where rule action equals follower's side
        - avg_outcome_when_followed: average 5-day return when followed
        - avg_outcome_when_not: average 5-day return when not followed
        - caveat: "Based on N of your M trades"

    Raises:
        ValueError: If the insight has no rule code or the run is not found
    """
    # Get the run result
    run = run_store.get(run_id)
    if not run:
        raise NotFoundError(f"Run {run_id} not found")

    rule_code = _resolve_rule_code(run.get("insights", []), run.get("rule_codes", {}), insight_id, f"run {run_id}")
    return _apply_rule(rule_code, dataset)


def activate_guru(guru_public: dict, guru_rules: dict, guru_id: str, insight_id: str, dataset: str) -> dict:
    """Activate an insight from a precomputed guru. Same return shape as activate()."""
    if guru_id not in guru_public:
        raise NotFoundError(f"Guru {guru_id} not found")

    rule_code = _resolve_rule_code(guru_public[guru_id].get("insights", []), guru_rules.get(guru_id, {}), insight_id, f"guru {guru_id}")
    return _apply_rule(rule_code, dataset)


def _resolve_rule_code(insights: list, rule_codes: dict, insight_id: str, owner: str) -> str:
    insight = None
    for ins in insights:
        if ins.get("id") == insight_id:
            insight = ins
            break

    if not insight:
        raise NotFoundError(f"Insight {insight_id} not found")

    rule_code_id = insight.get("rule_code_id")
    if not rule_code_id:
        raise ValueError(f"Insight {insight_id} has no rule code")

    rule_code = rule_codes.get(rule_code_id)
    if not rule_code:
        raise ValueError(f"Rule code {rule_code_id} not found in {owner}")

    return rule_code


def _apply_rule(rule_code: str, dataset: str) -> dict:
    # Load the follower data
    if dataset == "follower_sample":
        csv_path = "data/follower_sample.csv"
    else:
        raise ValueError(f"Unknown dataset: {dataset}")

    # Load trades from CSV
    df_input = pd.read_csv(csv_path)
    trades = df_input.to_dict("records")
    df = features.build_features(trades).reset_index(drop=True)

    if len(df) != len(trades):
        raise ValueError(f"build_features returned {len(df)} rows for {len(trades)} trades")

    sides = [t["side"] for t in trades]

    # Run the rule on the data
    rule_input = df[[c for c in features.FEATURE_COLUMNS if c in df.columns]]
    rule_input["date"] = df["date"]
    rule_input["symbol"] = df["symbol"]

    actions = sandbox.run_rule(rule_code, rule_input)

    # Compute metrics
    n_rule_applies = sum(1 for a in actions if a is not None)
    total_trades = len(actions)

    # Count matches where rule action equals follower's side
    matches = sum(1 for a, s in zip(actions, sides) if a is not None and a == s)
    already_follows_pct = matches / n_rule_applies if n_rule_applies > 0 else 0.0

    # Compute outcomes
    outcomes_when_followed = []
    outcomes_when_not = []

    for trade, action in zip(trades, actions):
        if action is None:
            continue

        outcome = _outcome_pct(trade)
        if outcome is None:
            continue

        if action == trade["side"]:
            outcomes_when_followed.append(outcome)
        else:
            outcomes_when_not.append(outcome)

    avg_outcome_when_followed = _mean(outcomes_when_followed)
    avg_outcome_when_not = _mean(outcomes_when_not)

    caveat = f"Based on {n_rule_applies} of your {total_trades} trades"

    return {
        "n_rule_applies": n_rule_applies,
        "already_follows_pct": round(already_follows_pct, 4),
        "avg_outcome_when_followed": avg_outcome_when_followed,
        "avg_outcome_when_not": avg_outcome_when_not,
        "caveat": caveat,
    }


def _outcome_pct(trade: dict) -> float | None:
    """Compute the 5-day forward return percentage for a trade."""
    try:
        import yfinance as yf

        symbol = trade["symbol"]
        date = trade["date"]
        price = float(trade["price"])

        hist = yf.Ticker(symbol).history(period="max", auto_adjust=False)
        if hist.empty:
            return None

        closes = hist["Close"]
        if getattr(closes.index, "tz", None) is not None:
            closes.index = closes.index.tz_localize(None)
        closes.index = closes.index.normalize()

        pos = closes.index.searchsorted(pd.Timestamp(date).normalize()) + OUTCOME_HORIZON_DAYS
        if pos >= len(closes):
            return None

        close = float(closes.iloc[pos])
        if close <= 0 or price <= 0:
            return None

        pct = (close / price - 1.0) * 100.0
        return round(pct if trade["side"] == "buy" else -pct, 2)
    except Exception:
        return None


def _mean(values: list) -> float | None:
    """Compute the mean of a list, ignoring None values."""
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 2) if values else None
