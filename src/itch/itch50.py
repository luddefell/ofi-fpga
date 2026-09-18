"""NASDAQ TotalView-ITCH 5.0 message decoder -> canonical book events.

Field offsets below follow the public ITCH 5.0 spec (all big-endian,
6-byte timestamps = nanoseconds since midnight). Verify byte-for-byte
against the official Nasdaq ITCH 5.0 spec PDF before trusting real data --
this is a first pass covering the messages that affect book state, not a
certified decoder.

Only message types that touch the book or trade tape are handled:
  A/F  Add Order            -> Add
  E    Order Executed       -> Execute
  C    Order Executed w/ Px -> Execute (+ Trade if printable)
  X    Order Cancel         -> Cancel
  D    Order Delete         -> Delete
  U    Order Replace        -> Delete(old) + Add(new)   [spec 2.1: two events]
  P    Trade (non-cross)    -> Trade
  H    Stock Trading Action -> Clear (on halt)

Prices arrive as price x 10000 (4 implied decimals); we convert to ticks
(tick_size = $0.01 = 100 of those units) once, here, so downstream book
addressing is a plain subtract per spec section 2.2.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator

from .events import Add, BookEvent, Cancel, Clear, Delete, Execute, Side, Trade

TICK_UNITS_PER_TICK = 100  # price field units (1/10000 $) per $0.01 tick


def _to_ticks(raw_price: int) -> int:
    # Saturating truncation toward zero; document if a venue ever needs
    # sub-tick prices -- ITCH 5.0 equities do not.
    return raw_price // TICK_UNITS_PER_TICK


def iter_raw_messages(path: str) -> Iterator[bytes]:
    """Read a flat ITCH 5.0 sample file: repeated [u16 BE length][message]."""
    with open(path, "rb") as f:
        while True:
            length_bytes = f.read(2)
            if len(length_bytes) < 2:
                return
            (length,) = struct.unpack(">H", length_bytes)
            body = f.read(length)
            if len(body) < length:
                raise EOFError("truncated ITCH message at EOF")
            yield body


def decode(msg: bytes) -> list[BookEvent]:
    """Decode one ITCH message body into zero or more canonical events."""
    mtype = chr(msg[0])
    handler = _HANDLERS.get(mtype)
    if handler is None:
        return []
    return handler(msg)


def _ts_ns(msg: bytes, offset: int) -> int:
    return int.from_bytes(msg[offset : offset + 6], "big")


def _add_order(msg: bytes) -> list[BookEvent]:
    # Type(1) StockLocate(2) Tracking(2) Timestamp(6) OrderRef(8)
    # Buy/Sell(1) Shares(4) Stock(8) Price(4) [MPID(4) for 'F']
    ts = _ts_ns(msg, 5)
    order_ref = int.from_bytes(msg[11:19], "big")
    side = Side.BID if msg[19:20] == b"B" else Side.ASK
    shares = int.from_bytes(msg[20:24], "big")
    raw_price = int.from_bytes(msg[32:36], "big")
    return [Add(side=side, price=_to_ticks(raw_price), qty=shares, order_id=order_ref, ts_ns=ts)]


def _order_executed(msg: bytes) -> list[BookEvent]:
    # Type(1) StockLocate(2) Tracking(2) Timestamp(6) OrderRef(8) Shares(4) MatchNum(8)
    ts = _ts_ns(msg, 5)
    order_ref = int.from_bytes(msg[11:19], "big")
    shares = int.from_bytes(msg[19:23], "big")
    return [Execute(order_id=order_ref, qty=shares, ts_ns=ts)]


def _order_executed_with_price(msg: bytes) -> list[BookEvent]:
    # Same prefix as 'E', then Printable(1) Price(4)
    ts = _ts_ns(msg, 5)
    order_ref = int.from_bytes(msg[11:19], "big")
    shares = int.from_bytes(msg[19:23], "big")
    match_num = int.from_bytes(msg[23:31], "big")  # noqa: F841 (kept for future trade tape use)
    printable = msg[31:32] == b"Y"
    events: list[BookEvent] = [Execute(order_id=order_ref, qty=shares, ts_ns=ts)]
    if printable:
        raw_price = int.from_bytes(msg[32:36], "big")
        events.append(Trade(side=None, price=_to_ticks(raw_price), qty=shares, ts_ns=ts))
    return events


def _order_cancel(msg: bytes) -> list[BookEvent]:
    # Type(1) StockLocate(2) Tracking(2) Timestamp(6) OrderRef(8) CanceledShares(4)
    ts = _ts_ns(msg, 5)
    order_ref = int.from_bytes(msg[11:19], "big")
    shares = int.from_bytes(msg[19:23], "big")
    return [Cancel(order_id=order_ref, qty=shares, ts_ns=ts)]


def _order_delete(msg: bytes) -> list[BookEvent]:
    # Type(1) StockLocate(2) Tracking(2) Timestamp(6) OrderRef(8)
    ts = _ts_ns(msg, 5)
    order_ref = int.from_bytes(msg[11:19], "big")
    return [Delete(order_id=order_ref, ts_ns=ts)]


class ReplaceFields:
    """Raw fields of a 'U' message. No Side field exists on the wire --
    the book engine must look up the original order's side before it can
    emit the Add half of Delete+Add (spec section 2.1)."""

    __slots__ = ("old_order_id", "new_order_id", "qty", "price", "ts_ns")

    def __init__(self, old_order_id: int, new_order_id: int, qty: int, price: int, ts_ns: int):
        self.old_order_id = old_order_id
        self.new_order_id = new_order_id
        self.qty = qty
        self.price = price
        self.ts_ns = ts_ns


def parse_replace(msg: bytes) -> ReplaceFields:
    # Type(1) StockLocate(2) Tracking(2) Timestamp(6)
    # OriginalOrderRef(8) NewOrderRef(8) Shares(4) Price(4)
    ts = _ts_ns(msg, 5)
    old_ref = int.from_bytes(msg[11:19], "big")
    new_ref = int.from_bytes(msg[19:27], "big")
    shares = int.from_bytes(msg[27:31], "big")
    raw_price = int.from_bytes(msg[31:35], "big")
    return ReplaceFields(old_ref, new_ref, shares, _to_ticks(raw_price), ts)


def _trade_non_cross(msg: bytes) -> list[BookEvent]:
    # Type(1) StockLocate(2) Tracking(2) Timestamp(6) OrderRef(8)
    # Buy/Sell(1) Shares(4) Stock(8) Price(4) MatchNum(8)
    ts = _ts_ns(msg, 5)
    side = Side.BID if msg[19:20] == b"B" else Side.ASK
    shares = int.from_bytes(msg[20:24], "big")
    raw_price = int.from_bytes(msg[32:36], "big")
    return [Trade(side=side, price=_to_ticks(raw_price), qty=shares, ts_ns=ts)]


def _trading_action(msg: bytes) -> list[BookEvent]:
    # Type(1) StockLocate(2) Tracking(2) Timestamp(6) Stock(8) State(1) Reserved(1) Reason(4)
    ts = _ts_ns(msg, 5)
    state = chr(msg[13])
    if state != "T":  # not Trading -> halted/paused/quotation-only
        return [Clear(side=None, ts_ns=ts, reason=f"trading_state={state}")]
    return []


_HANDLERS = {
    "A": _add_order,
    "F": _add_order,
    "E": _order_executed,
    "C": _order_executed_with_price,
    "X": _order_cancel,
    "D": _order_delete,
    "P": _trade_non_cross,
    "H": _trading_action,
}
