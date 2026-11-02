import socket
from .packet import DATA, ACK, FIN, MAX_PAYLOAD, make_packet, parse_packet


def send_file(chan, addr, data, timeout=0.05, max_tries=200):
    chunks = [data[i:i + MAX_PAYLOAD] for i in range(0, len(data), MAX_PAYLOAD)]
    chan.settimeout(timeout)
    retransmits = 0

    # all data packets, then a FIN carrying the final seq number
    packets = [make_packet(DATA, s, c) for s, c in enumerate(chunks)]
    packets.append(make_packet(FIN, len(chunks)))

    for seq, pkt in enumerate(packets):
        for attempt in range(max_tries):
            chan.sendto(pkt, addr)
            try:
                raw, _ = chan.recvfrom(2048)
            except socket.timeout:
                retransmits += 1
                continue
            parsed = parse_packet(raw)
            if parsed and parsed[0] == ACK and parsed[1] == seq:
                break                                # got the right ACK
            retransmits += 1                         # corrupt or stale ACK
        else:
            raise TimeoutError(f"gave up on packet {seq}")
    return {"packets": len(packets), "retransmits": retransmits}


def receive_file(chan):
    expected, out = 0, bytearray()
    while True:
        raw, addr = chan.recvfrom(2048)
        parsed = parse_packet(raw)
        if parsed is None:
            continue                                 # corrupt: silently drop
        ptype, seq, payload = parsed
        if ptype == DATA:
            if seq == expected:                      # the one we wanted
                out += payload
                expected += 1
            if seq < expected:                       # new OR duplicate: ACK it
                chan.sendto(make_packet(ACK, seq), addr)
        elif ptype == FIN and seq == expected:
            chan.sendto(make_packet(ACK, seq), addr)
            break

    # linger: if our last ACK was lost, the sender will resend FIN
    chan.settimeout(1.0)
    while True:
        try:
            raw, addr = chan.recvfrom(2048)
        except socket.timeout:
            break
        p = parse_packet(raw)
        if p and p[0] == FIN:
            chan.sendto(make_packet(ACK, p[1]), addr)
    return bytes(out)