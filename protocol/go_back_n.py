import socket
import time
from .packet import DATA, ACK, FIN, MAX_PAYLOAD, make_packet, parse_packet


def send_file(chan, addr, data, window=8, timeout=0.1, poll=0.005):
    chunks = [data[i:i + MAX_PAYLOAD] for i in range(0, len(data), MAX_PAYLOAD)]
    packets = [make_packet(DATA, s, c) for s, c in enumerate(chunks)]
    packets.append(make_packet(FIN, len(chunks)))
    total = len(packets)

    base = 0              # oldest unacknowledged packet
    nxt = 0               # next packet to send for the first time
    timer_start = None    # one timer, for the packet at `base`
    retransmits = 0
    chan.settimeout(poll)  # short wait so we can keep checking the timer
    started = time.time()

    while base < total:
        if time.time() - started > 120:
            raise TimeoutError("transfer took too long")

        # 1. fill the window
        while nxt < base + window and nxt < total:
            chan.sendto(packets[nxt], addr)
            if base == nxt:                  # window was empty: start timer
                timer_start = time.time()
            nxt += 1

        # 2. look for an ACK
        try:
            raw, _ = chan.recvfrom(2048)
        except socket.timeout:
            raw = None
        if raw:
            p = parse_packet(raw)
            # ACK number n means "I have everything below n"
            if p and p[0] == ACK and p[1] > base:
                base = min(p[1], total)      # slide the window forward
                timer_start = time.time() if base < nxt else None

        # 3. timeout: go back and resend everything in the window
        if timer_start is not None and time.time() - timer_start > timeout:
            for s in range(base, nxt):
                chan.sendto(packets[s], addr)
                retransmits += 1
            timer_start = time.time()

    return {"packets": total, "retransmits": retransmits}


def receive_file(chan, linger=1.0):
    expected, out = 0, bytearray()
    while True:
        raw, addr = chan.recvfrom(2048)
        p = parse_packet(raw)
        if p is None:
            continue                          # corrupt: drop
        ptype, seq, payload = p
        if seq == expected:                   # only accept the exact next one
            if ptype == DATA:
                out += payload
                expected += 1
            elif ptype == FIN:
                expected += 1
                chan.sendto(make_packet(ACK, expected), addr)
                break
        # always answer with "next packet I need" (cumulative ACK)
        chan.sendto(make_packet(ACK, expected), addr)

    # linger: re-ACK if the sender didn't get our last ACK
    chan.settimeout(linger)
    while True:
        try:
            raw, addr = chan.recvfrom(2048)
        except socket.timeout:
            break
        if parse_packet(raw):
            chan.sendto(make_packet(ACK, expected), addr)
    return bytes(out)