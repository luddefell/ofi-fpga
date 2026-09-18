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
```

## Running

```
pip install pytest
python -m pytest tests/ -q

python sim/replay.py path/to/sample.itch --k 6 --theta-q16 6554 > out.csv
```

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
- [ ] Bit-exact C++ port (spec 5 Stage 1) and SV/DPI-C testbench (Stage 2) --
      out of scope for this pass, see spec section 9 weeks 8-10

## Field-offset caveat

`itch50.py`'s byte offsets are a first pass against memory of the public
ITCH 5.0 spec, not verified byte-for-byte against the official Nasdaq PDF.
Before trusting output against real data, cross-check every offset table
in that document -- this is exactly the kind of bug historical replay
tests (spec 9 milestone 1) are meant to surface.
