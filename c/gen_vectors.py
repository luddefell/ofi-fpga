"""Generate golden test vectors from the Python reference OFICore, for the
C port to replay and compare bit-exactly against (spec section 5 Stage 1:
Python <-> C, before RTL ever enters the picture).
"""

import csv
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ofi_signal.ofi_core import OFICore, Top  # noqa: E402

K = 6
THETA_Q16 = 6554


def main(out_path: str, n: int = 500, seed: int = 1234) -> None:
    rng = random.Random(seed)
    core = OFICore(k_decay=K, theta_q16=THETA_Q16)

    bid_px, ask_px = 10000, 10005
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["bid_px", "bid_qty", "ask_px", "ask_qty", "exp_e", "exp_acc", "exp_flags"]
        )
        for _ in range(n):
            bid_px += rng.choice([-1, 0, 0, 1])
            ask_px = max(bid_px + 1, ask_px + rng.choice([-1, 0, 0, 1]))
            bid_qty = rng.randint(0, 50000)
            ask_qty = rng.randint(0, 50000)
            top = Top(bid_px=bid_px, bid_qty=bid_qty, ask_px=ask_px, ask_qty=ask_qty)
            e, acc, flags = core.event(top)
            writer.writerow([bid_px, bid_qty, ask_px, ask_qty, e, acc, flags])


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "vectors.csv"
    main(out)
