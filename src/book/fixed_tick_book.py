"""Fixed-tick direct-addressed book, per spec section 2.2.

RTL stores this as a dense array indexed by `price - price_floor` (a plain
subtract, since the parser already converted to ticks). A Python dict is
the sparse software-equivalent of that same addressing scheme -- same
semantics, no BRAM-sizing constraint to worry about here.

Determinism policy pinned per spec section 2.3 (documented, not implicit):
  - REPLACE: emitted as Delete(old) then Add(new), never collapsed.
  - Sequence gaps: caller invalidates the book (`mark_invalid`); no event
    is emitted downstream until a fresh, consistent state is confirmed.
  - Crossed/locked books: NOT rejected here. best_bid() >= best_ask() is
    allowed to pass through to the signal core with book.crossed flagged;
    Stage D decides whether to gate on it, this layer does not silently
    drop data.
  - Overflow: quantities saturate at 0 on over-reduction (can't go
    negative) rather than wrapping; this matches "saturating" semantics
    from spec section 2.3, applied at the point closest to the exchange
    data rather than deferred to the signal core.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

from itch import itch50
from itch.events import Add, BookEvent, Cancel, Clear, Delete, Execute, Side, Trade
from book.order_index import OrderIndex


@dataclass(frozen=True)
class Top:
    bid_px: int
    bid_qty: int
    ask_px: int
    ask_qty: int


class _SideBook:
    """One side's price -> qty map plus a lazy-deletion heap for best-of-book."""

    def __init__(self, is_bid: bool) -> None:
        self._is_bid = is_bid
        self._qty: dict[int, int] = {}
        # bids: max-heap via negated price; asks: min-heap, native price.
        self._heap: list[int] = []

    def _heap_key(self, price: int) -> int:
        return -price if self._is_bid else price

    def add(self, price: int, qty: int) -> None:
        if qty <= 0:
            return
        new_qty = self._qty.get(price, 0) + qty
        self._qty[price] = new_qty
        heapq.heappush(self._heap, self._heap_key(price))

    def reduce(self, price: int, qty: int) -> None:
        cur = self._qty.get(price, 0)
        remaining = cur - qty
        if remaining <= 0:
            self._qty.pop(price, None)
        else:
            self._qty[price] = remaining

    def best(self) -> tuple[int, int]:
        """Returns (price, qty); (0, 0) sentinel when the side is empty."""
        while self._heap:
            key = self._heap[0]
            price = -key if self._is_bid else key
            qty = self._qty.get(price, 0)
            if qty > 0:
                return price, qty
            heapq.heappop(self._heap)  # stale entry, drop and retry
        return 0, 0


class Book:
    def __init__(self) -> None:
        self.bids = _SideBook(is_bid=True)
        self.asks = _SideBook(is_bid=False)
        self.orders = OrderIndex()
        self.valid = True
        self.crossed = False

    def mark_invalid(self) -> None:
        self.valid = False

    def clear(self) -> None:
        self.bids = _SideBook(is_bid=True)
        self.asks = _SideBook(is_bid=False)
        self.orders.clear()
        self.valid = True
        self.crossed = False

    def top(self) -> Top:
        bid_px, bid_qty = self.bids.best()
        ask_px, ask_qty = self.asks.best()
        self.crossed = bool(bid_qty and ask_qty and bid_px >= ask_px)
        return Top(bid_px=bid_px, bid_qty=bid_qty, ask_px=ask_px, ask_qty=ask_qty)

    def apply(self, event: BookEvent) -> None:
        if isinstance(event, Add):
            side_book = self.bids if event.side == Side.BID else self.asks
            side_book.add(event.price, event.qty)
            self.orders.add(event.order_id, event.side, event.price, event.qty)

        elif isinstance(event, Cancel):
            rec = self.orders.reduce(event.order_id, event.qty)
            if rec is not None:
                side_book = self.bids if rec.side == Side.BID else self.asks
                side_book.reduce(rec.price, event.qty)

        elif isinstance(event, Delete):
            rec = self.orders.remove(event.order_id)
            if rec is not None:
                side_book = self.bids if rec.side == Side.BID else self.asks
                side_book.reduce(rec.price, rec.qty)

        elif isinstance(event, Execute):
            rec = self.orders.reduce(event.order_id, event.qty)
            if rec is not None:
                side_book = self.bids if rec.side == Side.BID else self.asks
                side_book.reduce(rec.price, event.qty)

        elif isinstance(event, Clear):
            if event.side is None:
                self.clear()
            else:
                side_book = self.bids if event.side == Side.BID else self.asks
                self.__dict__[  # noqa: no per-side clear helper needed beyond this
                    "bids" if event.side == Side.BID else "asks"
                ] = _SideBook(is_bid=event.side == Side.BID)

        elif isinstance(event, Trade):
            pass  # no book effect, per spec section 2.1

    def apply_replace(self, fields: "itch50.ReplaceFields") -> None:
        """Delete(old) + Add(new), per spec section 2.1 -- never collapsed."""
        rec = self.orders.remove(fields.old_order_id)
        if rec is None:
            return  # replace of an order we never saw (e.g. post sequence-gap); skip
        old_side_book = self.bids if rec.side == Side.BID else self.asks
        old_side_book.reduce(rec.price, rec.qty)

        new_side_book = self.bids if rec.side == Side.BID else self.asks
        new_side_book.add(fields.price, fields.qty)
        self.orders.add(fields.new_order_id, rec.side, fields.price, fields.qty)
