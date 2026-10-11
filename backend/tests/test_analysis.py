from datetime import datetime

from app.services.analysis import Trade, analyze, match_fifo


def trade(trade_id: str, date: str, side: str, qty: float, price: float, symbol: str = "AAPL") -> Trade:
    return Trade(trade_id, datetime.fromisoformat(date), symbol, side, qty, price, int(trade_id[1:]))


def test_fifo_matching_uses_oldest_buy_lot() -> None:
    closed, unmatched = match_fifo([
        trade("T001", "2025-01-01", "BUY", 2, 10),
        trade("T002", "2025-01-02", "BUY", 2, 20),
        trade("T003", "2025-01-03", "SELL", 3, 30),
    ])
    assert unmatched == []
    assert [(item.buy_trade_id, item.qty, item.realized_pnl) for item in closed] == [
        ("T001", 2, 40), ("T002", 1, 10)
    ]


def test_partial_exit_leaves_remaining_buy_lot_for_later_sell() -> None:
    closed, unmatched = match_fifo([
        trade("T001", "2025-01-01", "BUY", 10, 10),
        trade("T002", "2025-01-02", "SELL", 4, 12),
        trade("T003", "2025-01-03", "SELL", 6, 8),
    ])
    assert unmatched == []
    assert [(item.qty, item.realized_pnl) for item in closed] == [(4, 8), (6, -12)]


def test_unmatched_sell_is_flagged_without_fabricated_pnl() -> None:
    result = analyze([trade("T001", "2025-01-01", "SELL", 2, 10)])
    assert result["summary"]["completed_positions"] == 0
    assert result["summary"]["realized_pnl"] == 0
    assert result["exceptions"][0]["type"] == "unmatched_sell"
    assert result["exceptions"][0]["trade_id"] == "T001"


def test_insufficient_data_does_not_invent_patterns() -> None:
    result = analyze([
        trade("T001", "2025-01-01", "BUY", 1, 10),
        trade("T002", "2025-01-02", "SELL", 1, 12),
    ])
    assert result["patterns"] == []
    assert any("Insufficient" in warning for warning in result["warnings"])


def test_charts_reconcile_to_realized_pnl_and_handle_partial_exits() -> None:
    result = analyze([
        trade("T001", "2025-01-01", "BUY", 2, 10, "AAPL"),
        trade("T002", "2025-01-02", "BUY", 2, 20, "AAPL"),
        trade("T003", "2025-01-03", "SELL", 3, 30, "AAPL"),
        trade("T004", "2025-01-04", "SELL", 1, 10, "AAPL"),
    ])
    charts = result["charts"]
    assert charts["cumulative_pnl"][-1]["cumulative_pnl"] == result["summary"]["realized_pnl"] == 40
    assert charts["pnl_by_symbol"] == [{"symbol": "AAPL", "realized_pnl": 40, "completed_exits": 3}]
    assert charts["win_loss"] == [
        {"outcome": "win", "count": 2},
        {"outcome": "loss", "count": 1},
        {"outcome": "breakeven", "count": 0},
    ]


def test_charts_are_empty_or_zero_without_matched_exits() -> None:
    charts = analyze([trade("T001", "2025-01-01", "SELL", 2, 10)])["charts"]
    assert charts["cumulative_pnl"] == []
    assert charts["pnl_by_symbol"] == []
    assert all(item["count"] == 0 for item in charts["win_loss"])
