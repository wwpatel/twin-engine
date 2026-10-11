"""Deterministic, evidence-first trade analysis for the Twin MVP.

This module deliberately makes no claim about a trader's intent or market
conditions.  It only describes behavior observable in the uploaded ledger.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Iterable


@dataclass(frozen=True)
class Trade:
    trade_id: str
    date: datetime
    symbol: str
    side: str
    qty: float
    price: float
    source_index: int


@dataclass
class OpenLot:
    trade: Trade
    remaining_qty: float


@dataclass(frozen=True)
class ClosedLot:
    buy_trade_id: str
    sell_trade_id: str
    symbol: str
    qty: float
    realized_pnl: float
    return_pct: float
    holding_days: float
    exit_date: datetime


def _round(value: float, digits: int = 2) -> float:
    return round(value, digits)


def _strength(sample_size: int, concentration: float | None = None) -> str:
    if sample_size >= 10 and (concentration is None or concentration >= 0.75):
        return "strong"
    if sample_size >= 5:
        return "moderate"
    return "limited"


def _pattern(
    *,
    pattern_id: str,
    title: str,
    statement: str,
    sample_size: int,
    supporting_ids: list[str],
    exception_ids: list[str],
    limitations: list[str],
    concentration: float | None = None,
) -> dict:
    """Return a retrieval-ready pattern without exposing raw private trades."""
    evidence_strength = _strength(sample_size, concentration)
    unique_support = list(dict.fromkeys(supporting_ids))
    unique_exceptions = list(dict.fromkeys(exception_ids))
    return {
        "id": pattern_id,
        "title": title,
        "statement": statement,
        "description": statement,
        "sample_size": sample_size,
        "evidence_trade_ids": unique_support,
        "supporting_trade_ids": unique_support,
        "contradicting_trade_ids": unique_exceptions,
        "exceptions": unique_exceptions,
        "evidence_strength": evidence_strength,
        "confidence_label": f"{evidence_strength.title()} evidence from {sample_size} observed trade records",
        "limitations": limitations,
        "structured_explanation": {
            "claim": statement,
            "methodology": "Computed solely from uploaded transactions using chronological FIFO lot matching.",
            "supporting_trade_ids": unique_support,
            "exception_trade_ids": unique_exceptions,
            "limitations": limitations,
            "public_playbook_eligible": False,
        },
    }


def match_fifo(trades: Iterable[Trade]) -> tuple[list[ClosedLot], list[dict]]:
    """Match sells to prior buys per symbol and report any unmatched remainder."""
    lots: dict[str, deque[OpenLot]] = defaultdict(deque)
    closed: list[ClosedLot] = []
    unmatched: list[dict] = []
    for trade in sorted(trades, key=lambda item: (item.date, item.source_index)):
        if trade.side == "BUY":
            lots[trade.symbol].append(OpenLot(trade, trade.qty))
            continue
        remaining = trade.qty
        symbol_lots = lots[trade.symbol]
        while remaining > 1e-10 and symbol_lots:
            lot = symbol_lots[0]
            quantity = min(remaining, lot.remaining_qty)
            cost = quantity * lot.trade.price
            proceeds = quantity * trade.price
            closed.append(
                ClosedLot(
                    buy_trade_id=lot.trade.trade_id,
                    sell_trade_id=trade.trade_id,
                    symbol=trade.symbol,
                    qty=quantity,
                    realized_pnl=proceeds - cost,
                    return_pct=(proceeds - cost) / cost,
                    holding_days=max(0.0, (trade.date - lot.trade.date).total_seconds() / 86400),
                    exit_date=trade.date,
                )
            )
            lot.remaining_qty -= quantity
            remaining -= quantity
            if lot.remaining_qty <= 1e-10:
                symbol_lots.popleft()
        if remaining > 1e-10:
            unmatched.append(
                {
                    "trade_id": trade.trade_id,
                    "symbol": trade.symbol,
                    "unmatched_qty": _round(remaining, 8),
                    "reason": "Sell quantity has no prior BUY cost basis in the uploaded CSV.",
                }
            )
    return closed, unmatched


def chart_data(closed: list[ClosedLot]) -> dict:
    """Return aggregate chart datasets based exclusively on matched FIFO lots.

    A completed position is one matched BUY-lot to SELL-lot quantity.  A single
    SELL may therefore create multiple completed positions when it consumes
    multiple prior lots.
    """
    pnl_by_date: dict[str, float] = defaultdict(float)
    pnl_by_symbol: dict[str, float] = defaultdict(float)
    exits_by_symbol: Counter[str] = Counter()
    outcomes: Counter[str] = Counter()
    duration_buckets = {
        "0–1 days": 0,  # [0, 2) days
        "2–3 days": 0,  # [2, 4) days
        "4–7 days": 0,  # [4, 8) days
        "8+ days": 0,   # [8, infinity) days
    }
    for item in closed:
        pnl_by_date[item.exit_date.date().isoformat()] += item.realized_pnl
        pnl_by_symbol[item.symbol] += item.realized_pnl
        exits_by_symbol[item.symbol] += 1
        outcome = "win" if item.realized_pnl > 0 else "loss" if item.realized_pnl < 0 else "breakeven"
        outcomes[outcome] += 1
        if item.holding_days < 2:
            duration_buckets["0–1 days"] += 1
        elif item.holding_days < 4:
            duration_buckets["2–3 days"] += 1
        elif item.holding_days < 8:
            duration_buckets["4–7 days"] += 1
        else:
            duration_buckets["8+ days"] += 1

    cumulative = 0.0
    cumulative_pnl = []
    for date, pnl in sorted(pnl_by_date.items()):
        cumulative += pnl
        cumulative_pnl.append({
            "date": date,
            "realized_pnl": _round(pnl),
            "cumulative_pnl": _round(cumulative),
        })
    return {
        "unit": "Each count represents a matched FIFO BUY-lot to SELL-lot quantity; partial exits can create multiple units.",
        "cumulative_pnl": cumulative_pnl,
        "pnl_by_symbol": [
            {
                "symbol": symbol,
                "realized_pnl": _round(pnl),
                "completed_exits": exits_by_symbol[symbol],
            }
            for symbol, pnl in sorted(pnl_by_symbol.items())
        ],
        "win_loss": [
            {"outcome": outcome, "count": outcomes[outcome]}
            for outcome in ("win", "loss", "breakeven")
        ],
        "holding_duration": [
            {"bucket": bucket, "count": count}
            for bucket, count in duration_buckets.items()
        ],
        "limitations": [
            "Cumulative realized P&L is not a portfolio equity curve.",
            "Open lots and unmatched sell quantities are excluded.",
        ],
    }


def analyze(trades: list[Trade]) -> dict:
    """Build a transparent analysis result from validated CSV trades."""
    ordered = sorted(trades, key=lambda item: (item.date, item.source_index))
    closed, unmatched = match_fifo(ordered)
    warnings = [
        "News context is empty until Bright Data enrichment is integrated.",
        "Patterns describe observed transactions only; they do not establish intent, market triggers, or future performance.",
        "Trade-level evidence remains private. Any future public AI Twin must cite verified evidence and avoid representing the trader as a real person.",
    ]
    if unmatched:
        warnings.append("Some SELL quantities were excluded from realized P&L because no prior BUY cost basis was available.")

    realized_pnl = sum(item.realized_pnl for item in closed)
    cost_by_buy = {trade.trade_id: trade.price for trade in ordered if trade.side == "BUY"}
    realized_cost = sum(item.qty * cost_by_buy[item.buy_trade_id] for item in closed)
    winners = [item for item in closed if item.realized_pnl > 0]
    losers = [item for item in closed if item.realized_pnl < 0]
    summary = {
        "total_trades": len(ordered),
        "buy_trades": sum(item.side == "BUY" for item in ordered),
        "sell_trades": sum(item.side == "SELL" for item in ordered),
        "completed_positions": len(closed),
        "matched_exit_lots": len(closed),
        "unmatched_sell_count": len(unmatched),
        "realized_pnl": _round(realized_pnl),
        "realized_return_pct": _round(realized_pnl / realized_cost, 4) if realized_cost else None,
        "win_rate": _round(len(winners) / len(closed), 4) if closed else None,
        "average_winning_trade": _round(sum(item.realized_pnl for item in winners) / len(winners)) if winners else None,
        "average_losing_trade": _round(sum(item.realized_pnl for item in losers) / len(losers)) if losers else None,
    }
    patterns: list[dict] = []
    exceptions: list[dict] = [
        {
            "trade_id": item["trade_id"],
            "type": "unmatched_sell",
            "description": item["reason"],
            "outcome": "Realized P&L was not calculated for the unmatched quantity.",
            "unmatched_qty": item["unmatched_qty"],
        }
        for item in unmatched
    ]
    pnl_by_trade: dict[str, float] = defaultdict(float)
    for item in closed:
        pnl_by_trade[item.buy_trade_id] += item.realized_pnl
        pnl_by_trade[item.sell_trade_id] += item.realized_pnl

    def outcome_for(trade_id: str) -> str:
        if trade_id not in pnl_by_trade:
            return "No matched realized outcome is available for this trade."
        return f"Matched realized P&L associated with this trade: ${_round(pnl_by_trade[trade_id])}."

    # Holding behavior is based only on matched lots, never invented positions.
    if len(closed) >= 3:
        durations = [item.holding_days for item in closed]
        typical_days = median(durations)
        label = "intraday" if typical_days == 0 else "short-term" if typical_days <= 7 else "multi-week" if typical_days <= 30 else "longer-term"
        outliers = [item for item in closed if (item.holding_days > max(typical_days * 2, typical_days + 2) or (typical_days >= 2 and item.holding_days < typical_days / 2))]
        patterns.append(_pattern(
            pattern_id="holding_duration",
            title="Observed holding duration",
            statement=f"Matched lots have a median holding period of {_round(typical_days, 1)} days, consistent with {label} holding behavior in this sample.",
            sample_size=len(closed),
            supporting_ids=[item.sell_trade_id for item in closed],
            exception_ids=[item.sell_trade_id for item in outliers],
            limitations=["Only matched BUY-to-SELL quantities are included.", "Open lots are excluded."],
        ))
        for item in outliers:
            exceptions.append({"trade_id": item.sell_trade_id, "type": "holding_duration_outlier", "description": f"Held {_round(item.holding_days, 1)} days versus a {_round(typical_days, 1)}-day median.", "outcome": f"Realized P&L: {_round(item.realized_pnl)}."})
    else:
        warnings.append("Insufficient matched exits (need 3) to infer holding-duration behavior.")

    symbol_counts = Counter(item.symbol for item in ordered)
    top_symbol, top_count = symbol_counts.most_common(1)[0]
    symbol_share = top_count / len(ordered)
    if len(ordered) >= 3 and top_count >= 3 and symbol_share >= 0.6:
        patterns.append(_pattern(
            pattern_id="preferred_symbol",
            title="Concentrated symbol activity",
            statement=f"{top_symbol} accounts for {top_count} of {len(ordered)} uploaded transactions ({_round(symbol_share * 100, 1)}%).",
            sample_size=len(ordered),
            supporting_ids=[item.trade_id for item in ordered if item.symbol == top_symbol],
            exception_ids=[item.trade_id for item in ordered if item.symbol != top_symbol],
            limitations=["This measures transaction count, not portfolio allocation or conviction."],
            concentration=symbol_share,
        ))
        for item in ordered:
            if item.symbol != top_symbol:
                exceptions.append({
                    "trade_id": item.trade_id,
                    "type": "symbol_concentration_deviation",
                    "description": f"{item.symbol} falls outside the most frequently traded symbol ({top_symbol}).",
                    "outcome": outcome_for(item.trade_id),
                })
    elif len(ordered) < 3:
        warnings.append("Insufficient trades (need 3) to infer symbol preference.")

    buys = [item for item in ordered if item.side == "BUY"]
    if len(buys) >= 3:
        values = [item.qty * item.price for item in buys]
        typical_value = median(values)
        typical = [trade for trade in buys if typical_value * 0.5 <= trade.qty * trade.price <= typical_value * 1.5]
        share = len(typical) / len(buys)
        if share >= 0.6:
            patterns.append(_pattern(
                pattern_id="position_sizing",
                title="Observed entry sizing",
                statement=f"{len(typical)} of {len(buys)} BUY entries fall within 50% to 150% of the median entry value (${_round(typical_value)}).",
                sample_size=len(buys),
                supporting_ids=[item.trade_id for item in typical],
                exception_ids=[item.trade_id for item in buys if item not in typical],
                limitations=["Entry value is quantity × entry price; account size and buying power are unknown."],
                concentration=share,
            ))
            for item in buys:
                if item not in typical:
                    exceptions.append({
                        "trade_id": item.trade_id,
                        "type": "position_size_outlier",
                        "description": f"Entry value was ${_round(item.qty * item.price)} versus a ${_round(typical_value)} median.",
                        "outcome": outcome_for(item.trade_id),
                    })
    else:
        warnings.append("Insufficient BUY entries (need 3) to infer position-sizing behavior.")

    if len(closed) >= 3:
        gain_share = len(winners) / len(closed)
        if gain_share >= 0.6:
            patterns.append(_pattern(
                pattern_id="profit_taking",
                title="Observed profitable exits",
                statement=f"{len(winners)} of {len(closed)} matched exit lots realized gains ({_round(gain_share * 100, 1)}%).",
                sample_size=len(closed),
                supporting_ids=[item.sell_trade_id for item in winners],
                exception_ids=[item.sell_trade_id for item in losers],
                limitations=["A profitable exit does not prove a profit-taking rule or target.", "Unmatched sell quantities are excluded."],
                concentration=gain_share,
            ))
            for item in losers:
                exceptions.append({
                    "trade_id": item.sell_trade_id,
                    "type": "loss_among_mostly_profitable_exits",
                    "description": "This matched exit realized a loss while most matched exits realized gains.",
                    "outcome": outcome_for(item.sell_trade_id),
                })
        if len(losers) >= 3:
            loss_days = median(item.holding_days for item in losers)
            patterns.append(_pattern(
                pattern_id="loss_cutting",
                title="Observed losing exits",
                statement=f"{len(losers)} matched exit lots realized losses; their median holding period was {_round(loss_days, 1)} days.",
                sample_size=len(losers),
                supporting_ids=[item.sell_trade_id for item in losers],
                exception_ids=[item.sell_trade_id for item in winners],
                limitations=["This does not establish that losses were intentionally cut at a rule or threshold."],
            ))
            for item in winners:
                exceptions.append({
                    "trade_id": item.sell_trade_id,
                    "type": "gain_among_losing_exits",
                    "description": "This matched exit realized a gain while evaluating the losing-exit sample.",
                    "outcome": outcome_for(item.sell_trade_id),
                })
        else:
            warnings.append("Insufficient losing matched exits (need 3) to infer loss-cutting behavior.")
    else:
        warnings.append("Insufficient matched exits (need 3) to infer profit-taking or loss-cutting behavior.")

    hypotheses = [
        {
            "id": pattern["id"],
            "statement": pattern["statement"],
            "status": "supported_by_uploaded_history",
            "sample_size": pattern["sample_size"],
            "evidence_trade_ids": pattern["evidence_trade_ids"],
            "limitations": pattern["limitations"],
        }
        for pattern in patterns
    ]
    return {
        "summary": summary,
        "charts": chart_data(closed),
        "hypotheses": hypotheses,
        "patterns": patterns,
        "exceptions": exceptions,
        "news_context": [],
        "warnings": warnings,
    }
