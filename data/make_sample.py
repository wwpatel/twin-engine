import json
import random
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

SEED = 42
SYMBOLS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "XOM", "COST", "SPY"]
START_DATE = "2025-01-01"
END_DATE = "2026-06-30"
TARGET_TRADES = 200
NOISE_RATIO = 0.15
MIN_TRADES = 150
MAX_TRADES = 250
EXCEPTION_COUNT = 12
HABIT_FOLLOW_RATE = 0.75
DOWN_STREAK_THRESHOLD = 3
SELL_THRESHOLD = 0.08
SPY_DROP_THRESHOLD = 0.01
EXCEPTION_MOVE_THRESHOLD = 0.05

np.random.seed(SEED)
random.seed(SEED)


def fetch_prices():
    print("Fetching prices from yfinance...")
    prices = {}
    for symbol in SYMBOLS:
        print(f"  {symbol}...")
        ticker = yf.Ticker(symbol)
        hist = ticker.history(start=START_DATE, end=END_DATE, interval="1d", auto_adjust=True)
        if hist is not None and not hist.empty:
            prices[symbol] = hist["Close"]
    return prices


def down_streak(closes, idx):
    streak = 0
    for i in range(idx, 0, -1):
        if closes.iloc[i] < closes.iloc[i - 1]:
            streak += 1
        else:
            break
    return streak


def pct_change(closes, idx):
    if idx == 0:
        return 0.0
    return (closes.iloc[idx] - closes.iloc[idx - 1]) / closes.iloc[idx - 1]


def generate_trades(prices):
    print("Generating trades...")
    trades = []
    positions = {}
    spy = prices["SPY"]
    spy_dates = set(spy.index.normalize().strftime("%Y-%m-%d"))

    # Track exceptions to ensure exactly 12
    exceptions = []
    exception_candidates = []

    # First pass: find exception candidates
    for symbol in [s for s in SYMBOLS if s != "SPY"]:
        closes = prices[symbol]
        if closes is None or closes.empty:
            continue
        for i in range(1, len(closes)):
            move = pct_change(closes, i)
            if abs(move) > EXCEPTION_MOVE_THRESHOLD:
                if i + 1 < len(closes):
                    date_str = closes.index[i + 1].strftime("%Y-%m-%d")
                    exception_candidates.append({
                        "date": date_str,
                        "symbol": symbol,
                        "move": round(move * 100, 2),
                        "price": closes.iloc[i + 1],
                    })

    # Randomly select exactly 12 exceptions
    random.shuffle(exception_candidates)
    selected_exceptions = exception_candidates[:EXCEPTION_COUNT]
    exception_dates = set(e["date"] for e in selected_exceptions)

    # Main trade generation
    for symbol in SYMBOLS:
        if symbol == "SPY":
            continue
        closes = prices[symbol]
        if closes is None or closes.empty:
            continue

        for i, date in enumerate(closes.index):
            date_str = date.strftime("%Y-%m-%d")
            if date_str not in spy_dates:
                continue

            price = closes.iloc[i]

            # Habit 3: Never buy the day after SPY fell >1%
            spy_drop = 0.0
            if i > 0 and date in spy.index:
                spy_idx = spy.index.get_loc(date)
                if spy_idx > 0:
                    spy_drop = pct_change(spy, spy_idx)

            can_buy = spy_drop >= -SPY_DROP_THRESHOLD

            # Habit 1: Buy when down 3+ days in a row
            if i >= DOWN_STREAK_THRESHOLD and can_buy:
                streak = down_streak(closes, i)
                if streak >= DOWN_STREAK_THRESHOLD and symbol not in positions:
                    if random.random() < HABIT_FOLLOW_RATE:
                        qty = 10
                        trades.append({
                            "date": date_str,
                            "symbol": symbol,
                            "side": "buy",
                            "qty": qty,
                            "price": price,
                        })
                        positions[symbol] = {"qty": qty, "entry_price": price}

            # Habit 2: Sell when up 8%+ from entry
            if symbol in positions:
                pos = positions[symbol]
                gain = (price - pos["entry_price"]) / pos["entry_price"]
                if gain >= SELL_THRESHOLD:
                    if random.random() < HABIT_FOLLOW_RATE:
                        trades.append({
                            "date": date_str,
                            "symbol": symbol,
                            "side": "sell",
                            "qty": pos["qty"],
                            "price": price,
                        })
                        del positions[symbol]

    # Add noise trades (~15% of final target)
    noise_count = int(TARGET_TRADES * NOISE_RATIO)
    all_dates = sorted(set(t["date"] for t in trades))
    if not all_dates:
        all_dates = [d.strftime("%Y-%m-%d") for d in pd.date_range(START_DATE, END_DATE, freq="B") if d.strftime("%Y-%m-%d") in spy_dates]

    for _ in range(noise_count):
        date = random.choice(all_dates)
        symbol = random.choice([s for s in SYMBOLS if s != "SPY"])
        # Only allow buy for noise to avoid position tracking issues
        side = "buy"
        closes = prices[symbol]
        if closes is None or closes.empty:
            continue
        if date in closes.index:
            price = closes.loc[date]
            qty = 10
            trades.append({
                "date": date,
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "price": price,
            })
            if symbol in positions:
                positions[symbol]["qty"] += qty
            else:
                positions[symbol] = {"qty": qty, "entry_price": price}

    # Add exceptions (replace noise trades on same dates, or add new)
    for exc in selected_exceptions:
        # Remove any existing trade on same date/symbol
        trades = [t for t in trades if not (t["date"] == exc["date"] and t["symbol"] == exc["symbol"])]
        trades.append({
            "date": exc["date"],
            "symbol": exc["symbol"],
            "side": "buy",
            "qty": 10,
            "price": exc["price"],
        })
        exceptions.append({
            "date": exc["date"],
            "symbol": exc["symbol"],
            "move": exc["move"],
        })
        # Update positions for the exception buy
        if exc["symbol"] in positions:
            positions[exc["symbol"]]["qty"] += 10
        else:
            positions[exc["symbol"]] = {"qty": 10, "entry_price": exc["price"]}

    # Sort by date
    trades.sort(key=lambda t: t["date"])

    # Trim to target range
    if len(trades) > MAX_TRADES:
        trades = trades[:MAX_TRADES]

    # If too few, add more noise
    while len(trades) < MIN_TRADES:
        date = random.choice(all_dates)
        symbol = random.choice([s for s in SYMBOLS if s != "SPY"])
        # Only allow buy for noise to avoid position tracking issues
        side = "buy"
        closes = prices[symbol]
        if closes is None or closes.empty:
            continue
        if date in closes.index:
            price = closes.loc[date]
            qty = 10
            trades.append({
                "date": date,
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "price": price,
            })
            if symbol in positions:
                positions[symbol]["qty"] += qty
            else:
                positions[symbol] = {"qty": qty, "entry_price": price}

    return trades, exceptions


def main():
    prices = fetch_prices()
    trades, exceptions = generate_trades(prices)

    # Write CSV
    df = pd.DataFrame(trades)
    df.to_csv("data/sample_trades.csv", index=False)
    print(f"Wrote {len(trades)} trades to data/sample_trades.csv")

    # Write answer key
    answer_key = {
        "seed": SEED,
        "habits": [
            "Buy when a stock closed down 3 or more days in a row",
            "Sell the whole position once it is up 8% or more from entry",
            "Never buy the day after SPY fell more than 1%",
        ],
        "exceptions": exceptions,
    }
    with open("data/answer_key.json", "w") as f:
        json.dump(answer_key, f, indent=2)
    print(f"Wrote answer key to data/answer_key.json")


if __name__ == "__main__":
    main()
