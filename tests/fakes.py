"""In-process fakes for modules built in parallel (parser, features, sandbox) and for Anthropic."""
import types
from types import SimpleNamespace

import pandas as pd

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


def make_trade(date, symbol, side, price=100.0, **feature_values):
    """A trade dict carrying its own feature values; the fake parser strips them, the fake features restores them."""
    trade = {"date": date, "symbol": symbol, "side": side, "qty": 1.0, "price": float(price)}
    for col in FEATURE_COLUMNS:
        trade[col] = feature_values.get(col, 0.0)
    return trade


def make_modules(trades):
    """Return fake (parser, features, sandbox) modules backed by `trades` (see make_trade)."""
    by_key = {(t["date"], t["symbol"], t["side"]): t for t in trades}

    parser = types.ModuleType("parser")
    parser.calls = []

    def load_trades(path):
        parser.calls.append(path)
        return [{k: t[k] for k in ("date", "symbol", "side", "qty", "price")} for t in trades]

    parser.load_trades = load_trades

    features = types.ModuleType("features")

    def build_features(parsed, **kwargs):
        rows = []
        for t in parsed:
            src = by_key[(t["date"], t["symbol"], t["side"])]
            rows.append({"date": t["date"], "symbol": t["symbol"], "side": t["side"],
                         **{c: src[c] for c in FEATURE_COLUMNS}})
        return pd.DataFrame(rows, columns=["date", "symbol", "side"] + FEATURE_COLUMNS)

    features.build_features = build_features

    sandbox = types.ModuleType("sandbox")
    sandbox.SandboxError = FakeSandboxError
    sandbox.calls = []

    def run_rule(code, df):
        sandbox.calls.append((code, df.copy()))
        namespace = {}
        try:
            exec(code, namespace)
            return [namespace["rule"](row.to_dict()) for _, row in df.iterrows()]
        except Exception as e:
            raise FakeSandboxError(f"Rule execution failed: {type(e).__name__}: {e}") from e

    sandbox.run_rule = run_rule
    return parser, features, sandbox


class FakeSandboxError(Exception):
    pass


def rule_response(description, code):
    return f"<description>{description}</description>\n<code>\n{code.strip()}\n</code>"


class FakeAnthropic:
    """Mimics anthropic.Anthropic().messages.create; returns queued responses, repeating the last one."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        idx = min(len(self.calls) - 1, len(self._responses) - 1)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._responses[idx])])

    def prompts(self):
        parts = []
        for call in self.calls:
            parts.append(call.get("system", ""))
            parts.extend(m["content"] for m in call["messages"])
        return parts


class FakePrices:
    """Replacement for engine.fetch_close_after backed by {(symbol, date): close}."""

    def __init__(self, closes=None):
        self.closes = dict(closes or {})

    def __call__(self, symbol, date, days=5):
        return self.closes.get((symbol, date))
