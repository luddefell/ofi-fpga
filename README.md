# ofi-golden-model

Standalone golden model for order-flow-imbalance, per `ofi_golden_model_spec.md`
sections 2-5. Reads flat NASDAQ ITCH 5.0 sample files directly -- no
dependency on any FPGA packet-parser stage. See `../integrated/` for the
version wired to a real Stage A.

## Layout

```
src/
  itch/
    events.py       canonical book-event ABI (spec 2.1): Add/Cancel/Delete/Execute/Trade/Clear
    itch50.py        ITCH 5.0 message decoder -> canonical events
    moldudp64.py      MoldUDP64 UDP framing (kept for a future live/FPGA-fed source; unused by the file replay path)
  book/
    fixed_tick_book.py   fixed-tick direct-addressed book (spec 2.2), per-side best-of-book
    order_index.py       order_id -> (side, price, qty), needed for Cancel/Delete/Execute/Replace
  ofi_signal/
    ofi_core.py       OFICore -- bit-exact integer OFI + EWMA (spec 4.3), ported near-verbatim
sim/
  replay.py           drives an ITCH file through book + OFICore, emits CSV
tests/
  test_book_and_signal.py   directed coverage (spec 5 Stage 3): empty side, crossed book, saturation, replace
c/
  ofi_core.h/.c        bit-exact C port of ofi_core.py (spec 5 Stage 1: Python <-> C)
  gen_vectors.py        generates vectors.csv from the Python OFICore
  test_ofi_core.c        replays vectors.csv through the C port, asserts bit-exact match
rtl/
  ofi_core.sv          synchronous RTL port of the signal core (spec 4.3/8), one-cycle latency
cocotb_tests/
  test_ofi_core.py      cocotb testbench: drives RTL and the Python OFICore with identical
                         stimulus, asserts bit-exact (e_n, acc, flags) every event (spec 5 Stage 2)
  run.py                 runner (uses cocotb_tools.runner, not a Makefile); exits nonzero on any failure
```

## Running

```
pip install pytest cocotb cocotb-bus

# Python golden model tests
python -m pytest tests/ -q

# Python <-> C bit-exact check (spec 5 Stage 1)
python c/gen_vectors.py c/vectors.csv
gcc -std=c11 -Wall -Wextra -O2 c/ofi_core.c c/test_ofi_core.c -o c/test_ofi_core && ./c/test_ofi_core c/vectors.csv

# golden model <-> RTL bit-exact check (spec 5 Stage 2), needs Icarus Verilog (iverilog/vvp) on PATH
python sim/replay.py path/to/sample.itch --k 6 --theta-q16 6554 > out.csv
python cocotb_tests/run.py
```

### Toolchain note (Windows)

This was developed with no admin rights available, so the Icarus/GCC
installers (winget) were blocked by UAC. Portable no-install builds were
used instead: [oss-cad-suite](https://github.com/YosysHQ/oss-cad-suite-build)
(`bin` and `lib` both need to be on PATH -- `lib` holds runtime DLLs
`vvp.exe` needs) for Icarus Verilog, and
[WinLibs](https://github.com/brechtsanders/winlibs_mingw) for a portable
MinGW GCC. Any standard iverilog/gcc install works too.

## Status / what's not done yet

This is the spec's milestone-1/2 slice (weeks 1-4 of section 9), Python
only:

- [x] ITCH 5.0 decode for book-affecting message types (A/F/E/C/X/D/U) and halts (H)
- [x] Fixed-tick book + order index, REPLACE as Delete+Add (never collapsed)
- [x] OFICore ported from spec 4.3 (sat32, EWMA decay, division-free threshold)
- [x] Directed tests for empty side / crossed book / saturation / replace
- [ ] Sequence-gap recovery is stubbed (`seq_gap_suspected` in `replay.py` is
      always False for flat files -- there's no sequence number in a flat
      ITCH sample; wire this to `moldudp64.MoldPacket.sequence_number` once
      fed from a live/UDP source)
- [ ] Book validated against exchange-reported executions (spec 9 milestone 1) --
      needs a real ITCH sample file, not yet run
- [ ] Contemporaneous impact regression sanity check (spec 9 milestone 2)
- [x] Bit-exact C port (spec 5 Stage 1): `c/ofi_core.c`, verified against
      500 random golden-model vectors, 0 mismatches
- [x] RTL signal core (`rtl/ofi_core.sv`) + cocotb testbench (spec 5 Stage 2,
      substituting cocotb+Icarus for the SV/DPI-C flow the spec describes):
      verified bit-exact against the Python golden model over a 300-event
      random walk plus directed cases (first-event seed, bid-price-up,
      2-billion-share saturation)
- [ ] Book engine RTL (Stage B) -- out of scope for this pass; only the
      signal core (Stage C) has been ported to RTL, per spec section 9's
      own ordering (signal core RTL, weeks 9-10, before book engine RTL,
      weeks 11-12)
- [ ] RTL bit widths are generous/unoptimized (`ACC_WIDTH=64`, wide
      intermediate products) rather than sized per spec 4.1's headroom
      analysis -- this is a functional verification target, not an
      area/timing-closed synthesis result

## Field-offset caveat

`itch50.py`'s byte offsets are a first pass against memory of the public
ITCH 5.0 spec, not verified byte-for-byte against the official Nasdaq PDF.
Before trusting output against real data, cross-check every offset table
in that document -- this is exactly the kind of bug historical replay
tests (spec 9 milestone 1) are meant to surface.
