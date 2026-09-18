"""Directed coverage per spec section 5 Stage 3 -- the cases historical
replay under-samples: empty side, crossed book, saturation, replace.
Run with: python -m pytest tests/ (from ofi-golden-model/, src on path via conftest).
"""

from itch.events import Add, Delete, Side
from book.fixed_tick_book import Book
from ofi_signal.ofi_core import OFICore, Top, sat32


def test_empty_side_sentinel():
    book = Book()
    book.apply(Add(side=Side.BID, price=1000, qty=100, order_id=1, ts_ns=0))
    top = book.top()
    assert top.bid_px == 1000 and top.bid_qty == 100
    assert top.ask_px == 0 and top.ask_qty == 0  # spec 2.3 sentinel for empty side


def test_crossed_book_detected_not_dropped():
    book = Book()
    book.apply(Add(side=Side.BID, price=1005, qty=50, order_id=1, ts_ns=0))
    book.apply(Add(side=Side.ASK, price=1000, qty=50, order_id=2, ts_ns=0))
    top = book.top()
    assert top.bid_px >= top.ask_px
    assert book.crossed is True  # flagged, not rejected -- spec 2.3 policy


def test_delete_reduces_book_and_index():
    book = Book()
    book.apply(Add(side=Side.BID, price=1000, qty=100, order_id=1, ts_ns=0))
    book.apply(Delete(order_id=1, ts_ns=1))
    top = book.top()
    assert top.bid_px == 0 and top.bid_qty == 0
    assert book.orders.get(1) is None


def test_sat32_saturates_both_directions():
    assert sat32(1 << 40) == (1 << 31) - 1
    assert sat32(-(1 << 40)) == -(1 << 31)
    assert sat32(42) == 42


def test_ofi_first_event_is_seed_not_signal():
    core = OFICore(k_decay=4, theta_q16=1 << 15)
    e, acc, flags = core.event(Top(bid_px=100, bid_qty=10, ask_px=101, ask_qty=10))
    assert (e, acc, flags) == (0, 0, 0)  # spec 4.3: first call seeds prev/depth only


def test_ofi_bid_price_up_counts_full_new_queue():
    core = OFICore(k_decay=4, theta_q16=1 << 15)
    core.event(Top(bid_px=100, bid_qty=10, ask_px=101, ask_qty=10))
    e, _, _ = core.event(Top(bid_px=101, bid_qty=30, ask_px=101, ask_qty=10))
    # bid up -> only first indicator fires -> e gets +bid_qty; ask unchanged -> both fire -> net 0
    assert e == 30
