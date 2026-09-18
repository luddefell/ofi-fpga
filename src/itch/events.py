"""Canonical book-event ABI, per ofi_golden_model_spec.md section 2.1.

Every feed decoder (ITCH, MDP, ...) normalizes into these event types.
This is the internal boundary between "Stage A" (feed decode) and
"Stage B" (book engine) in the spec's pipeline.
"""

from dataclasses import dataclass
from enum import IntEnum


class Side(IntEnum):
    BID = 0
    ASK = 1


@dataclass(frozen=True)
class Add:
    side: Side
    price: int  # ticks
    qty: int
    order_id: int
    ts_ns: int


@dataclass(frozen=True)
class Cancel:
    order_id: int
    qty: int  # partial reduction
    ts_ns: int


@dataclass(frozen=True)
class Delete:
    order_id: int
    ts_ns: int


@dataclass(frozen=True)
class Execute:
    order_id: int
    qty: int
    ts_ns: int


@dataclass(frozen=True)
class Replace:
    """Emitted as Delete(old_id) followed by Add(new_id, ...) by the decoder.

    Kept here only as a documentation of intent -- per spec section 2.1,
    REPLACE is never itself pushed to the book; it is split at decode time.
    """

    old_order_id: int
    new_order_id: int
    price: int
    qty: int
    ts_ns: int


@dataclass(frozen=True)
class Trade:
    """Hidden/odd-lot execution or auction print. No book effect."""

    side: Side | None
    price: int
    qty: int
    ts_ns: int


@dataclass(frozen=True)
class Clear:
    """Book wipe: trading halt, resume-from-snapshot, or sequence-gap recovery."""

    side: Side | None  # None = whole book
    ts_ns: int
    reason: str = ""


BookEvent = Add | Cancel | Delete | Execute | Trade | Clear
