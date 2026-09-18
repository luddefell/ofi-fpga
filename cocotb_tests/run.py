"""Runner for the cocotb testbench, using cocotb_tools.runner (cocotb 2.x)
instead of the classic Makefile flow, since GNU Make isn't assumed to be
on PATH. Requires Icarus Verilog (iverilog/vvp) on PATH.

Usage:
    python cocotb_tests/run.py
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from cocotb_tools.runner import get_runner

THIS_DIR = Path(__file__).resolve().parent
RTL_DIR = THIS_DIR.parent / "rtl"


def main() -> int:
    runner = get_runner("icarus")
    runner.build(
        verilog_sources=[str(RTL_DIR / "ofi_core.sv")],
        hdl_toplevel="ofi_core",
        build_args=["-g2012"],
        timescale=("1ns", "1ps"),
        always=True,
    )
    results_xml = runner.test(
        hdl_toplevel="ofi_core",
        test_module="test_ofi_core",
        test_dir=str(THIS_DIR),
    )

    # runner.test() doesn't raise or return a nonzero exit code on test
    # failure (only on a build/sim crash) -- it just writes a JUnit-style
    # results.xml. Parse it so this script is usable in CI / as a plain
    # pass/fail gate, per spec section 5's "fail immediately" requirement.
    root = ET.parse(results_xml).getroot()
    failures = sum(int(ts.get("failures", 0)) + int(ts.get("errors", 0)) for ts in root.iter("testsuite"))
    total = sum(int(ts.get("tests", 0)) for ts in root.iter("testsuite"))
    print(f"\n{total} cocotb tests run, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
