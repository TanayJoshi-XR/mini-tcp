import struct
import zlib
from collections import namedtuple

SYN, ACK, FIN = 1, 2, 4
HEADER_FMT = "!BIIHHI"     # flags, seq, ack, window, length, crc
HEADER_SIZE = struct.calcsize(HEADER_FMT)
MAX_PAYLOAD = 1024

Segment = namedtuple("Segment", "flags seq ack window payload")


def make_segment(flags, seq=0, ack=0, window=0, payload=b""):
    head = struct.pack(HEADER_FMT, flags, seq, ack, window, len(payload), 0)
    crc = zlib.crc32(head + payload)
    return struct.pack(HEADER_FMT, flags, seq, ack, window, len(payload), crc) + payload


def parse_segment(data):
    """Return a Segment, or None if the packet is damaged."""
    if len(data) < HEADER_SIZE:
        return None
    flags, seq, ack, window, length, crc = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
    payload = data[HEADER_SIZE:]
    if len(payload) != length:
        return None
    head = struct.pack(HEADER_FMT, flags, seq, ack, window, length, 0)
    if zlib.crc32(head + payload) != crc:
        return None
    return Segment(flags, seq, ack, window, payload)