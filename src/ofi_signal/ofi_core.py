"""Bit-exact integer OFI with EWMA accumulation. Ported near-verbatim from
ofi_golden_model_spec.md section 4.3 -- this is the file that must match
the RTL cycle-for-cycle, so do not "clean it up" with anything that isn't
also in the spec (no floats, no implicit division, explicit saturation).
"""

from __future__ import annotations

from dataclasses import dataclass

INT32_MIN, INT32_MAX = -(1 << 31), (1 << 31) - 1


def sat32(x: int) -> int:
    return INT32_MAX if x > INT32_MAX else INT32_MIN if x < INT32_MIN else x


@dataclass
class Top:
    bid_px: int  # ticks
    bid_qty: int  # shares
    ask_px: int
    ask_qty: int


class OFICore:
    """Mirrors the RTL exactly: no floats, explicit saturation,
    arithmetic right shift for decay."""

    def __init__(self, k_decay: int, theta_q16: int):
        self.k = k_decay  # EWMA: acc -= acc >> k
        self.theta = theta_q16  # Q16.16 threshold multiplier
        self.prev: Top | None = None
        self.acc = 0  # int48/int64 in RTL
        self.depth_acc = 0  # running depth EWMA
        self.valid = False  # gated on book validity

    def event(self, t: Top) -> tuple[int, int, int]:
        """Process one book state. Returns (e_n, acc, flags)."""
        p = self.prev
        if p is None:
            self.prev = t
            self.depth_acc = (t.bid_qty + t.ask_qty) << self.k
            return (0, 0, 0)

        # --- OFI event term: 4 compares, 4 conditional adds ---
        e = 0
        if t.bid_px >= p.bid_px:
            e += t.bid_qty
        if t.bid_px <= p.bid_px:
            e -= p.bid_qty
        if t.ask_px <= p.ask_px:
            e -= t.ask_qty
        if t.ask_px >= p.ask_px:
            e += p.ask_qty
        e = sat32(e)

        # --- EWMA accumulate: one shift, two adds ---
        self.acc = self.acc - (self.acc >> self.k) + e

        # --- depth EWMA, same structure ---
        d = t.bid_qty + t.ask_qty
        self.depth_acc = self.depth_acc - (self.depth_acc >> self.k) + d

        # --- threshold WITHOUT division (spec section 3.2) ---
        # want: acc / depth > theta   <=>   acc << 16 > theta * depth
        lhs = self.acc << 16
        rhs = (self.theta * self.depth_acc) >> self.k
        flags = 0
        if lhs > rhs:
            flags |= 0b01  # buy pressure
        if lhs < -rhs:
            flags |= 0b10  # sell pressure

        self.prev = t
        return (e, self.acc, flags)
