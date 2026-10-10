"""Build insights from rule discovery results."""

import re
from collections import defaultdict
from typing import Any


def build_insights(result: dict) -> list[dict]:
    """Build insights from a rule discovery result.

    Returns a list with:
    - One insight per kept rule (kind "rule")
    - One insight per cluster of exceptions sharing a feature (kind "exception_pattern")

    Each insight has:
    - id: unique identifier
    - title: short title
    - plain: one plain-English sentence
    - kind: "rule" or "exception_pattern"
    - evidence: {n_trades, discovery_match, holdout_match, baseline_holdout_match}
    - rule_code_id: rule code ID (null for exception patterns)
    """
    insights = []

    # Add insights for kept rules
    rule_index = 0
    for hypothesis in result.get("hypotheses", []):
        if hypothesis.get("status") == "kept":
            rule_index += 1
            rule_code_id = f"r{rule_index}"
            insights.append({
                "id": f"rule_{rule_index}",
                "title": hypothesis["text"],
                "plain": hypothesis["text"],
                "kind": "rule",
                "evidence": {
                    "n_trades": _estimate_trades_from_coverage(hypothesis.get("coverage", 0)),
                    "discovery_match": hypothesis.get("discovery_match"),
                    "holdout_match": hypothesis.get("holdout_match"),
                    "baseline_holdout_match": result.get("baseline", {}).get("holdout_match"),
                },
                "rule_code_id": rule_code_id,
            })

    # Add insights for exception patterns
    exceptions = result.get("exceptions", [])
    if exceptions:
        exception_patterns = _cluster_exceptions(exceptions)
        for idx, pattern in enumerate(exception_patterns, 1):
            insights.append({
                "id": f"exception_{idx}",
                "title": pattern["title"],
                "plain": pattern["plain"],
                "kind": "exception_pattern",
                "evidence": {
                    "n_trades": pattern["count"],
                    "discovery_match": None,
                    "holdout_match": None,
                    "baseline_holdout_match": result.get("baseline", {}).get("holdout_match"),
                },
                "rule_code_id": None,
            })

    return insights


def _estimate_trades_from_coverage(coverage: float) -> int:
    """Estimate number of trades from coverage percentage.

    This is a rough estimate since we don't have the total trade count in the result.
    For now, return None to indicate we don't have this data.
    """
    return None


def _cluster_exceptions(exceptions: list[dict]) -> list[dict]:
    """Cluster exceptions by shared features.

    Groups exceptions by:
    - Symbol
    - Side
    - Context keywords

    Returns a list of pattern dicts with title, plain, and count.
    """
    patterns = []

    # Cluster by symbol
    symbol_clusters = defaultdict(list)
    for exc in exceptions:
        symbol_clusters[exc["symbol"]].append(exc)

    for symbol, excs in symbol_clusters.items():
        if len(excs) >= 2:
            patterns.append({
                "title": f"Exceptions in {symbol}",
                "plain": f"The trader broke their rules in {len(excs)} trades of {symbol}.",
                "count": len(excs),
            })

    # Cluster by side
    side_clusters = defaultdict(list)
    for exc in exceptions:
        side_clusters[exc["side"]].append(exc)

    for side, excs in side_clusters.items():
        if len(excs) >= 2:
            patterns.append({
                "title": f"Exceptions on {side} trades",
                "plain": f"The trader broke their rules in {len(excs)} {side} trades.",
                "count": len(excs),
            })

    # Cluster by broke_rule
    rule_clusters = defaultdict(list)
    for exc in exceptions:
        rule_clusters[exc.get("broke_rule", "unknown")].append(exc)

    for rule, excs in rule_clusters.items():
        if len(excs) >= 2 and rule != "unknown":
            patterns.append({
                "title": f"Exceptions breaking '{rule}'",
                "plain": f"The trader broke the rule '{rule}' in {len(excs)} trades.",
                "count": len(excs),
            })

    # Cluster by context keywords
    context_patterns = _cluster_by_context(exceptions)
    patterns.extend(context_patterns)

    return patterns


def _cluster_by_context(exceptions: list[dict]) -> list[dict]:
    """Cluster exceptions by keywords in their context headlines."""
    patterns = []

    # Common keywords in financial news
    keywords = ["earnings", "report", "beat", "miss", "guidance", "outlook", "merger", "acquisition", "split", "dividend"]

    keyword_counts = defaultdict(int)
    for exc in exceptions:
        context = exc.get("context", [])
        for headline in context:
            headline_lower = headline.lower()
            for keyword in keywords:
                if keyword in headline_lower:
                    keyword_counts[keyword] += 1

    for keyword, count in keyword_counts.items():
        if count >= 2:
            patterns.append({
                "title": f"Exceptions related to {keyword}",
                "plain": f"The trader broke their rules in {count} trades where news mentioned {keyword}.",
                "count": count,
            })

    return patterns
