"""Drive a flat ITCH 5.0 sample file through book reconstruction + OFICore,
emitting one CSV row per book-changing message.

Usage:
    python sim/replay.py path/to/sample.itch --k 6 --theta-q16 6554 > out.csv

theta default (6554 / 65536 ~= 0.1) is a placeholder -- tune against your
dataset per spec section 9 milestone 3, it is not a calibrated value.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from itch import itch50  # noqa: E402
from itch.events import Add, Cancel, Clear, Delete, Execute, Trade  # noqa: E402
from book.fixed_tick_book import Book  # noqa: E402
from ofi_signal.ofi_core import OFICore, Top  # noqa: E402


def run(itch_path: str, k_decay: int, theta_q16: int, out=sys.stdout) -> None:
    book = Book()
    core = OFICore(k_decay=k_decay, theta_q16=theta_q16)

    writer = csv.writer(out)
    writer.writerow(
        ["ts_ns", "bid_px", "bid_qty", "ask_px", "ask_qty", "crossed", "e_n", "acc", "flags"]
    )

    seq_gap_suspected = False  # placeholder: flat sample files carry no sequence
    # number of their own; wire this up to MoldUDP64.sequence_number for a
    # live/UDP-fed source (see itch/moldudp64.py).

    for raw in itch50.iter_raw_messages(itch_path):
        mtype = chr(raw[0])

        if mtype == "U":
            fields = itch50.parse_replace(raw)
            book.apply_replace(fields)
            ts_ns = fields.ts_ns
        else:
            events = itch50.decode(raw)
            ts_ns = None
            for ev in events:
                ts_ns = getattr(ev, "ts_ns", ts_ns)
                book.apply(ev)
            if ts_ns is None:
                continue  # message type we don't decode (system events, etc.)

        book_touching = mtype in ("A", "F", "E", "C", "X", "D", "U")
        if not book_touching:
            continue

        if not book.valid or seq_gap_suspected:
            continue  # per spec 2.3: suppress signal output until recovery

        t = book.top()
        core_top = Top(bid_px=t.bid_px, bid_qty=t.bid_qty, ask_px=t.ask_px, ask_qty=t.ask_qty)
        e_n, acc, flags = core.event(core_top)

        writer.writerow([ts_ns, t.bid_px, t.bid_qty, t.ask_px, t.ask_qty, int(book.crossed), e_n, acc, flags])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("itch_file")
    ap.add_argument("--k", type=int, default=6, help="EWMA decay shift (spec section 3.5)")
    ap.add_argument(
        "--theta-q16", type=int, default=6554, help="threshold, Q16.16 fixed point"
    )
    args = ap.parse_args()
    run(args.itch_file, args.k, args.theta_q16)


if __name__ == "__main__":
    main()
