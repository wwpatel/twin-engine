import json

import pandas as pd
import pytest


def load_trades(path: str) -> list[dict]:
    df = pd.read_csv(path)
    return df.to_dict("records")


def test_row_count_in_range():
    trades = load_trades("data/sample_trades.csv")
    assert 150 <= len(trades) <= 250


def test_all_dates_are_trading_days():
    trades = load_trades("data/sample_trades.csv")
    df = pd.DataFrame(trades)
    dates = pd.to_datetime(df["date"])

    # Check no weekends (but 2025-2026 might have holidays, so just check day of week)
    for date in dates:
        assert date.dayofweek < 5, f"{date} is a weekend"


def test_no_sell_without_position():
    trades = load_trades("data/sample_trades.csv")
    positions = {}

    for trade in trades:
        symbol = trade["symbol"]
        side = trade["side"]

        if side == "sell":
            assert symbol in positions, f"Sell {symbol} on {trade['date']} without position"
            assert positions[symbol]["qty"] >= trade["qty"], f"Selling more than owned for {symbol}"
            positions[symbol]["qty"] -= trade["qty"]
            if positions[symbol]["qty"] == 0:
                del positions[symbol]
        else:  # buy
            if symbol in positions:
                positions[symbol]["qty"] += trade["qty"]
            else:
                positions[symbol] = {"qty": trade["qty"]}


def test_exactly_12_exceptions_in_key():
    with open("data/answer_key.json") as f:
        answer_key = json.load(f)

    assert "exceptions" in answer_key
    assert len(answer_key["exceptions"]) == 12

    for exc in answer_key["exceptions"]:
        assert "date" in exc
        assert "symbol" in exc
        assert "move" in exc
        assert abs(exc["move"]) > 5, f"Exception move {exc['move']} is not > 5%"


def test_answer_key_has_habits_and_seed():
    with open("data/answer_key.json") as f:
        answer_key = json.load(f)

    assert "seed" in answer_key
    assert answer_key["seed"] == 42
    assert "habits" in answer_key
    assert len(answer_key["habits"]) == 3
