"""cocotb testbench: proves rtl/ofi_core.sv matches the Python golden model
(src/ofi_signal/ofi_core.py) bit-exactly, event for event. This is the
spec section 5 "Stage 2" comparison (golden model vs RTL), substituting
cocotb+Icarus for the SV/DPI-C flow the spec describes -- same intent:
drive identical stimulus into both, fail immediately with the event index
on any mismatch.
"""

import os
import random
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ofi_signal.ofi_core import OFICore, Top  # noqa: E402

K_DECAY = int(os.environ.get("OFI_K_DECAY", "6"))
THETA_Q16 = int(os.environ.get("OFI_THETA_Q16", "6554"))


async def _reset(dut):
    dut.rst_n.value = 0
    dut.in_valid.value = 0
    dut.bid_px.value = 0
    dut.bid_qty.value = 0
    dut.ask_px.value = 0
    dut.ask_qty.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def _drive_event(dut, top: Top):
    dut.bid_px.value = top.bid_px
    dut.bid_qty.value = top.bid_qty
    dut.ask_px.value = top.ask_px
    dut.ask_qty.value = top.ask_qty
    dut.in_valid.value = 1
    await RisingEdge(dut.clk)
    # Icarus's VPI value-change callback (which RisingEdge relies on) fires
    # before this edge's nonblocking assignments have settled, so sampling
    # dut.* right after RisingEdge sees last cycle's values, not this
    # cycle's. ReadOnly() waits for the post-NBA settle point before we (or
    # the caller) read any output.
    await ReadOnly()
    # Leave the ReadOnly region so the next call's writes (new stimulus for
    # the following cycle) are legal -- writing while still parked in
    # ReadOnly raises in cocotb.
    await NextTimeStep()


def _check(dut, i, expected):
    exp_e, exp_acc, exp_flags = expected
    assert dut.out_valid.value == 1, f"event {i}: out_valid not asserted"
    got_e = dut.e_n.value.to_signed()
    got_acc = dut.acc.value.to_signed()
    got_flags = int(dut.flags.value)
    assert got_e == exp_e, f"event {i}: e_n mismatch: got {got_e}, expected {exp_e}"
    assert got_acc == exp_acc, f"event {i}: acc mismatch: got {got_acc}, expected {exp_acc}"
    assert got_flags == exp_flags, f"event {i}: flags mismatch: got {got_flags}, expected {exp_flags}"


@cocotb.test()
async def test_first_event_is_seed(dut):
    """Spec 4.3: the first event seeds prev/depth and returns (0, 0, 0)."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    ref = OFICore(k_decay=K_DECAY, theta_q16=THETA_Q16)
    top = Top(bid_px=100, bid_qty=10, ask_px=101, ask_qty=10)
    expected = ref.event(top)

    await _drive_event(dut, top)
    _check(dut, 0, expected)


@cocotb.test()
async def test_bid_price_up_counts_full_new_queue(dut):
    """Spec 3.1: bid price up -> only the first indicator fires -> +bid_qty."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    ref = OFICore(k_decay=K_DECAY, theta_q16=THETA_Q16)

    seq = [
        Top(bid_px=100, bid_qty=10, ask_px=101, ask_qty=10),
        Top(bid_px=101, bid_qty=30, ask_px=101, ask_qty=10),
    ]
    for i, top in enumerate(seq):
        expected = ref.event(top)
        await _drive_event(dut, top)
        _check(dut, i, expected)

    assert dut.e_n.value.to_signed() == 30


@cocotb.test()
async def test_matches_golden_model_random_walk(dut):
    """Bit-exact RTL vs Python golden model over a random book-state walk --
    the actual "prove it works" comparison, event by event."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    ref = OFICore(k_decay=K_DECAY, theta_q16=THETA_Q16)
    rng = random.Random(1234)

    bid_px, ask_px = 10000, 10005
    for i in range(300):
        bid_px += rng.choice([-1, 0, 0, 1])
        ask_px = max(bid_px + 1, ask_px + rng.choice([-1, 0, 0, 1]))
        bid_qty = rng.randint(0, 50000)
        ask_qty = rng.randint(0, 50000)
        top = Top(bid_px=bid_px, bid_qty=bid_qty, ask_px=ask_px, ask_qty=ask_qty)

        expected = ref.event(top)
        await _drive_event(dut, top)
        _check(dut, i, expected)


@cocotb.test()
async def test_saturation_extreme_quantities(dut):
    """Spec 5 Stage 3 directed case: max-quantity saturation."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    ref = OFICore(k_decay=K_DECAY, theta_q16=THETA_Q16)
    seq = [
        Top(bid_px=100, bid_qty=2_000_000_000, ask_px=101, ask_qty=2_000_000_000),
        Top(bid_px=101, bid_qty=2_000_000_000, ask_px=100, ask_qty=2_000_000_000),  # crossed + extreme
    ]
    for i, top in enumerate(seq):
        expected = ref.event(top)
        await _drive_event(dut, top)
        _check(dut, i, expected)
