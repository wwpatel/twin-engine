import tempfile

import pytest

from parser import load_trades


def test_good_file():
    content = """date,symbol,side,qty,price
2026-01-15,NVDA,buy,10,150.5
2026-01-16,AAPL,sell,5,175.25
2026-01-17,TSLA,buy,20,210.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(content)
        path = f.name

    trades = load_trades(path)
    assert len(trades) == 3
    assert trades[0] == {
        "date": "2026-01-15",
        "symbol": "NVDA",
        "side": "buy",
        "qty": 10.0,
        "price": 150.5,
    }
    assert trades[1] == {
        "date": "2026-01-16",
        "symbol": "AAPL",
        "side": "sell",
        "qty": 5.0,
        "price": 175.25,
    }
    assert trades[2] == {
        "date": "2026-01-17",
        "symbol": "TSLA",
        "side": "buy",
        "qty": 20.0,
        "price": 210.0,
    }


def test_bad_file_missing_column():
    content = """date,symbol,side,qty
2026-01-15,NVDA,buy,10
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(content)
        path = f.name

    with pytest.raises(ValueError, match="Missing required columns"):
        load_trades(path)


def test_bad_file_invalid_date():
    content = """date,symbol,side,qty,price
invalid-date,NVDA,buy,10,150.5
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(content)
        path = f.name

    with pytest.raises(ValueError, match="Row 2: Invalid date format"):
        load_trades(path)


def test_bad_file_invalid_side():
    content = """date,symbol,side,qty,price
2026-01-15,NVDA,hold,10,150.5
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(content)
        path = f.name

    with pytest.raises(ValueError, match="Row 2: Invalid side"):
        load_trades(path)
