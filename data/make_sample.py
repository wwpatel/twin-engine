import argparse
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


def generate_guru_dip(prices):
    """Dip-buyer habits: existing dip strategy"""
    return generate_trades(prices)


def generate_guru_breakout(prices):
    """Buys when stock closes at 20-day high, sells on 5% drop from entry, ~70% followed. 10 exceptions: buys after earnings gap."""
    print("Generating guru_breakout trades...")
    trades = []
    positions = {}
    spy = prices["SPY"]
    spy_dates = set(spy.index.normalize().strftime("%Y-%m-%d"))

    # Track exceptions to ensure exactly 10
    exceptions = []
    exception_candidates = []

    # First pass: find exception candidates (earnings gaps - large moves)
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

    # Randomly select exactly 10 exceptions
    random.shuffle(exception_candidates)
    selected_exceptions = exception_candidates[:10]
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

            # Buy when stock closes at 20-day high
            if i >= 20 and symbol not in positions:
                recent_high = max(closes.iloc[i-20:i])
                if price >= recent_high:
                    if random.random() < 0.70:  # ~70% followed
                        qty = 10
                        trades.append({
                            "date": date_str,
                            "symbol": symbol,
                            "side": "buy",
                            "qty": qty,
                            "price": price,
                        })
                        positions[symbol] = {"qty": qty, "entry_price": price}

            # Sell when down 5% from entry
            if symbol in positions:
                pos = positions[symbol]
                loss = (price - pos["entry_price"]) / pos["entry_price"]
                if loss <= -0.05:
                    if random.random() < 0.70:
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


def generate_guru_defensive(prices):
    """Trims all positions when SPY falls >1.5%, favors XOM JPM COST, ~75% followed. 8 exceptions: adds to tech on market drops."""
    print("Generating guru_defensive trades...")
    trades = []
    positions = {}
    spy = prices["SPY"]
    spy_dates = set(spy.index.normalize().strftime("%Y-%m-%d"))

    # Track exceptions to ensure exactly 8
    exceptions = []
    exception_candidates = []

    # First pass: find exception candidates (market drops with tech opportunities)
    for i in range(1, len(spy)):
        spy_drop = pct_change(spy, i)
        if spy_drop <= -0.015:  # SPY fell >1.5%
            date_str = spy.index[i].strftime("%Y-%m-%d")
            for symbol in ["AAPL", "MSFT", "NVDA", "GOOGL", "META"]:  # Tech stocks
                if symbol in prices and prices[symbol] is not None and not prices[symbol].empty:
                    if date_str in prices[symbol].index:
                        exception_candidates.append({
                            "date": date_str,
                            "symbol": symbol,
                            "move": round(spy_drop * 100, 2),
                            "price": prices[symbol].loc[date_str],
                        })

    # Randomly select exactly 8 exceptions
    random.shuffle(exception_candidates)
    selected_exceptions = exception_candidates[:8]
    exception_dates = set(e["date"] for e in selected_exceptions)

    # Main trade generation
    processed_spy_drops = set()  # Track dates where we've already processed SPY drops

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

            # Check SPY drop
            spy_drop = 0.0
            if i > 0 and date in spy.index:
                spy_idx = spy.index.get_loc(date)
                if spy_idx > 0:
                    spy_drop = pct_change(spy, spy_idx)

            # Habit: Trim all positions when SPY falls >1.5% (only process once per date)
            if spy_drop <= -0.015 and date_str not in processed_spy_drops:
                processed_spy_drops.add(date_str)
                for pos_symbol in list(positions.keys()):
                    if random.random() < 0.75:  # ~75% followed
                        pos = positions[pos_symbol]
                        pos_closes = prices[pos_symbol]
                        if pos_closes is not None and not pos_closes.empty and date_str in pos_closes.index:
                            pos_price = pos_closes.loc[date_str]
                            trades.append({
                                "date": date_str,
                                "symbol": pos_symbol,
                                "side": "sell",
                                "qty": pos["qty"],
                                "price": pos_price,
                            })
                            del positions[pos_symbol]

            # Habit: Favor XOM, JPM, COST for new positions
            favored_symbols = ["XOM", "JPM", "COST"]
            if symbol in favored_symbols and symbol not in positions:
                if random.random() < 0.75:  # ~75% followed
                    qty = 10
                    trades.append({
                        "date": date_str,
                        "symbol": symbol,
                        "side": "buy",
                        "qty": qty,
                        "price": price,
                    })
                    positions[symbol] = {"qty": qty, "entry_price": price}

    # Add noise trades (~15% of final target)
    noise_count = int(TARGET_TRADES * NOISE_RATIO)
    all_dates = sorted(set(t["date"] for t in trades))
    if not all_dates:
        all_dates = [d.strftime("%Y-%m-%d") for d in pd.date_range(START_DATE, END_DATE, freq="B") if d.strftime("%Y-%m-%d") in spy_dates]

    for _ in range(noise_count):
        date = random.choice(all_dates)
        symbol = random.choice([s for s in SYMBOLS if s != "SPY"])
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

    # Add exceptions (add to tech on market drops)
    for exc in selected_exceptions:
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


def generate_follower_sample(prices):
    """About 70 trades, buys after down days ~30% of time, otherwise random."""
    print("Generating follower_sample trades...")
    trades = []
    positions = {}
    spy = prices["SPY"]
    spy_dates = set(spy.index.normalize().strftime("%Y-%m-%d"))

    TARGET_TRADES_FOLLOWER = 70
    MIN_TRADES_FOLLOWER = 60
    MAX_TRADES_FOLLOWER = 80

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

            # Check if previous day was down
            prev_down = False
            if i > 0:
                prev_down = closes.iloc[i] < closes.iloc[i - 1]

            # Buy after down days ~30% of time, otherwise random
            if symbol not in positions:
                if prev_down and random.random() < 0.30:
                    qty = 10
                    trades.append({
                        "date": date_str,
                        "symbol": symbol,
                        "side": "buy",
                        "qty": qty,
                        "price": price,
                    })
                    positions[symbol] = {"qty": qty, "entry_price": price}
                elif random.random() < 0.05:  # Random buys
                    qty = 10
                    trades.append({
                        "date": date_str,
                        "symbol": symbol,
                        "side": "buy",
                        "qty": qty,
                        "price": price,
                    })
                    positions[symbol] = {"qty": qty, "entry_price": price}

            # Random sells
            if symbol in positions and random.random() < 0.03:
                pos = positions[symbol]
                trades.append({
                    "date": date_str,
                    "symbol": symbol,
                    "side": "sell",
                    "qty": pos["qty"],
                    "price": price,
                })
                del positions[symbol]

    # Sort by date
    trades.sort(key=lambda t: t["date"])

    # Trim to target range
    if len(trades) > MAX_TRADES_FOLLOWER:
        trades = trades[:MAX_TRADES_FOLLOWER]

    # If too few, add more random trades
    all_dates = sorted(set(t["date"] for t in trades))
    if not all_dates:
        all_dates = [d.strftime("%Y-%m-%d") for d in pd.date_range(START_DATE, END_DATE, freq="B") if d.strftime("%Y-%m-%d") in spy_dates]

    while len(trades) < MIN_TRADES_FOLLOWER:
        date = random.choice(all_dates)
        symbol = random.choice([s for s in SYMBOLS if s != "SPY"])
        closes = prices[symbol]
        if closes is None or closes.empty:
            continue
        if date in closes.index:
            price = closes.loc[date]
            if symbol not in positions:
                qty = 10
                trades.append({
                    "date": date,
                    "symbol": symbol,
                    "side": "buy",
                    "qty": qty,
                    "price": price,
                })
                positions[symbol] = {"qty": qty, "entry_price": price}
            elif random.random() < 0.5:
                pos = positions[symbol]
                trades.append({
                    "date": date,
                    "symbol": symbol,
                    "side": "sell",
                    "qty": pos["qty"],
                    "price": price,
                })
                del positions[symbol]

    return trades, []


def main():
    parser = argparse.ArgumentParser(description="Generate sample trading data")
    parser.add_argument("--style", type=str, default="original",
                        choices=["original", "guru_dip", "guru_breakout", "guru_defensive", "follower_sample"],
                        help="Trading style to generate")
    args = parser.parse_args()

    prices = fetch_prices()

    if args.style == "original":
        trades, exceptions = generate_trades(prices)
        output_csv = "data/sample_trades.csv"
        output_key = "data/answer_key.json"
        habits = [
            "Buy when a stock closed down 3 or more days in a row",
            "Sell the whole position once it is up 8% or more from entry",
            "Never buy the day after SPY fell more than 1%",
        ]
    elif args.style == "guru_dip":
        trades, exceptions = generate_guru_dip(prices)
        output_csv = "data/guru_dip.csv"
        output_key = "data/guru_dip_answer_key.json"
        habits = [
            "Buy when a stock closed down 3 or more days in a row",
            "Sell the whole position once it is up 8% or more from entry",
            "Never buy the day after SPY fell more than 1%",
        ]
    elif args.style == "guru_breakout":
        trades, exceptions = generate_guru_breakout(prices)
        output_csv = "data/guru_breakout.csv"
        output_key = "data/guru_breakout_answer_key.json"
        habits = [
            "Buy when a stock closes at a 20-day high",
            "Sell when position is down 5% from entry",
            "About 70% of trades follow these rules",
        ]
    elif args.style == "guru_defensive":
        trades, exceptions = generate_guru_defensive(prices)
        output_csv = "data/guru_defensive.csv"
        output_key = "data/guru_defensive_answer_key.json"
        habits = [
            "Trim all positions when SPY falls more than 1.5%",
            "Favor XOM, JPM, COST for new positions",
            "About 75% of trades follow these rules",
        ]
    elif args.style == "follower_sample":
        trades, exceptions = generate_follower_sample(prices)
        output_csv = "data/follower_sample.csv"
        output_key = "data/follower_sample_answer_key.json"
        habits = [
            "Buy after down days about 30% of the time",
            "Otherwise random trading",
            "About 70 total trades",
        ]

    # Write CSV
    df = pd.DataFrame(trades)
    df.to_csv(output_csv, index=False)
    print(f"Wrote {len(trades)} trades to {output_csv}")

    # Write answer key
    answer_key = {
        "seed": SEED,
        "habits": habits,
        "exceptions": exceptions,
    }
    with open(output_key, "w") as f:
        json.dump(answer_key, f, indent=2)
    print(f"Wrote answer key to {output_key}")


if __name__ == "__main__":
    main()
