import struct
import zlib

DATA, ACK, FIN = 0, 1, 2
HEADER_FMT = "!BIHI"          # ! = network byte order
HEADER_SIZE = struct.calcsize(HEADER_FMT)
MAX_PAYLOAD = 1024


def make_packet(ptype, seq, payload=b""):
    no_crc = struct.pack(HEADER_FMT, ptype, seq, len(payload), 0)
    crc = zlib.crc32(no_crc + payload)
    return struct.pack(HEADER_FMT, ptype, seq, len(payload), crc) + payload


def parse_packet(data):
    """Return (ptype, seq, payload), or None if the packet is corrupt."""
    if len(data) < HEADER_SIZE:
        return None
    ptype, seq, length, crc = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
    payload = data[HEADER_SIZE:]
    if len(payload) != length:
        return None
    no_crc = struct.pack(HEADER_FMT, ptype, seq, length, 0)
    if zlib.crc32(no_crc + payload) != crc:
        return None
    return ptype, seq, payload