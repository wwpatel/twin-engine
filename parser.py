import csv
from datetime import datetime


def load_trades(path: str) -> list[dict]:
    required_columns = {"date", "symbol", "side", "qty", "price"}

    with open(path) as f:
        reader = csv.DictReader(f)

        if not required_columns.issubset(set(reader.fieldnames or [])):
            missing = required_columns - set(reader.fieldnames or [])
            raise ValueError(f"Missing required columns: {missing}")

        trades = []
        for row_num, row in enumerate(reader, start=2):
            try:
                date_str = row["date"].strip()
                try:
                    datetime.fromisoformat(date_str)
                except ValueError:
                    raise ValueError(f"Invalid date format: {date_str}")

                symbol = row["symbol"].strip()
                if not symbol:
                    raise ValueError("Symbol cannot be empty")

                side = row["side"].strip().lower()
                if side not in ("buy", "sell"):
                    raise ValueError(f"Invalid side: {side}")

                qty = float(row["qty"])
                if qty <= 0:
                    raise ValueError(f"Qty must be positive: {qty}")

                price = float(row["price"])
                if price <= 0:
                    raise ValueError(f"Price must be positive: {price}")

                trades.append({
                    "date": date_str,
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "price": price,
                })
            except ValueError as e:
                raise ValueError(f"Row {row_num}: {e}")

    return trades
