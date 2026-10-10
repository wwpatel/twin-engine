import os

import pandas as pd
import yfinance as yf

from news import get_headlines
from parser import load_trades


def precompute_news():
    trades = load_trades("data/sample_trades.csv")

    symbols = set(trade["symbol"] for trade in trades)

    for symbol in symbols:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1mo")

        for trade in trades:
            if trade["symbol"] != symbol or trade["side"] != "buy":
                continue

            trade_date = pd.to_datetime(trade["date"])
            prev_date = trade_date - pd.Timedelta(days=1)

            if prev_date not in hist.index:
                continue

            prev_close = hist.loc[prev_date, "Close"]
            prev_prev_close = hist.loc[prev_date - pd.Timedelta(days=1), "Close"] if (prev_date - pd.Timedelta(days=1)) in hist.index else prev_close

            if prev_prev_close == 0:
                continue

            pct_change = abs((prev_close - prev_prev_close) / prev_prev_close * 100)

            if pct_change > 5:
                get_headlines(symbol, trade["date"])


if __name__ == "__main__":
    precompute_news()
