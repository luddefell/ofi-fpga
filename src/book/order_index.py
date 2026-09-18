"""order_id -> (side, price, qty) table.

Per spec section 2.2: storing only aggregate quantity per price level means
CANCEL/DELETE/EXECUTE (which carry only an order_id) can't find their side
and price without this side table. In RTL this is a separate BRAM hashed
on order_id; in Python a dict is the direct equivalent.
"""

from __future__ import annotations

from dataclasses import dataclass

from itch.events import Side


@dataclass
class OrderRecord:
    side: Side
    price: int  # ticks
    qty: int


class OrderIndex:
    def __init__(self) -> None:
        self._orders: dict[int, OrderRecord] = {}

    def add(self, order_id: int, side: Side, price: int, qty: int) -> None:
        self._orders[order_id] = OrderRecord(side, price, qty)

    def get(self, order_id: int) -> OrderRecord | None:
        return self._orders.get(order_id)

    def reduce(self, order_id: int, qty: int) -> OrderRecord | None:
        """Reduce remaining qty (cancel/execute). Removes the record at zero."""
        rec = self._orders.get(order_id)
        if rec is None:
            return None
        rec.qty -= qty
        if rec.qty <= 0:
            del self._orders[order_id]
        return rec

    def remove(self, order_id: int) -> OrderRecord | None:
        return self._orders.pop(order_id, None)

    def clear(self) -> None:
        self._orders.clear()
