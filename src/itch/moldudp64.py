"""MoldUDP64 session framing.

This is the transport wrapper NASDAQ uses to carry ITCH messages over UDP
multicast in the *live* feed. Archived/sample ITCH files are NOT wrapped in
this -- they are a flat stream of length-prefixed messages (see itch50.py).

This module exists for one reason: it is the exact seam where a real
packet-parser-fpga-style Stage A would hand payload bytes to this golden
model. Today nothing calls it (we replay flat ITCH files instead, per
project decision), but the interface is kept realistic so swapping in a
live/FPGA-fed source later doesn't require touching itch50.py.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

_HEADER_FMT = ">10sQH"  # session(10s), sequence_number(u64 BE), message_count(u16 BE)
_HEADER_LEN = struct.calcsize(_HEADER_FMT)


@dataclass(frozen=True)
class MoldPacket:
    session: bytes
    sequence_number: int
    messages: list[bytes]


def parse_packet(payload: bytes) -> MoldPacket:
    """Parse one UDP payload (post Ethernet/IPv4/UDP strip) as MoldUDP64."""
    if len(payload) < _HEADER_LEN:
        raise ValueError(f"MoldUDP64 payload too short: {len(payload)} bytes")

    session, seq, msg_count = struct.unpack_from(_HEADER_FMT, payload, 0)
    offset = _HEADER_LEN
    messages: list[bytes] = []
    for _ in range(msg_count):
        if offset + 2 > len(payload):
            raise ValueError("truncated MoldUDP64 message length field")
        (msg_len,) = struct.unpack_from(">H", payload, offset)
        offset += 2
        if offset + msg_len > len(payload):
            raise ValueError("truncated MoldUDP64 message body")
        messages.append(payload[offset : offset + msg_len])
        offset += msg_len

    return MoldPacket(session=session, sequence_number=seq, messages=messages)
