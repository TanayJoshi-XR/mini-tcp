import socket
import time
from .packet import DATA, ACK, FIN, MAX_PAYLOAD, make_packet, parse_packet


def send_file(chan, addr, data, window=8, timeout=0.1, poll=0.005):
    chunks = [data[i:i + MAX_PAYLOAD] for i in range(0, len(data), MAX_PAYLOAD)]
    packets = [make_packet(DATA, s, c) for s, c in enumerate(chunks)]
    packets.append(make_packet(FIN, len(chunks)))
    total = len(packets)

    acked = [False] * total
    sent_at = [0.0] * total      # one timer PER packet
    base = nxt = 0
    retransmits = 0
    chan.settimeout(poll)
    started = time.time()

    while base < total:
        if time.time() - started > 120:
            raise TimeoutError("transfer took too long")

        while nxt < base + window and nxt < total:
            chan.sendto(packets[nxt], addr)
            sent_at[nxt] = time.time()
            nxt += 1

        try:
            raw, _ = chan.recvfrom(2048)
        except socket.timeout:
            raw = None
        if raw:
            p = parse_packet(raw)
            # ACK n means "I got packet n" (just that one)
            if p and p[0] == ACK and base <= p[1] < nxt:
                acked[p[1]] = True
                while base < total and acked[base]:   # slide past acked ones
                    base += 1

        now = time.time()
        for s in range(base, nxt):                    # resend only the late ones
            if not acked[s] and now - sent_at[s] > timeout:
                chan.sendto(packets[s], addr)
                sent_at[s] = now
                retransmits += 1

    return {"packets": total, "retransmits": retransmits}


def receive_file(chan, window=8, linger=1.0):
    rcv_base = 0
    buffer = {}                   # out-of-order packets waiting for gaps to fill
    out = bytearray()
    finished = False

    while not finished:
        raw, addr = chan.recvfrom(2048)
        p = parse_packet(raw)
        if p is None:
            continue
        ptype, seq, payload = p
        if ptype == ACK:
            continue
        if rcv_base <= seq < rcv_base + window:
            buffer[seq] = (ptype, payload)
            chan.sendto(make_packet(ACK, seq), addr)   # ACK this exact packet
            while rcv_base in buffer:                  # deliver in order
                t, pl = buffer.pop(rcv_base)
                rcv_base += 1
                if t == DATA:
                    out += pl
                else:                                  # FIN
                    finished = True
                    break
        elif seq < rcv_base:                           # old packet: ACK was lost
            chan.sendto(make_packet(ACK, seq), addr)

    chan.settimeout(linger)
    while True:
        try:
            raw, addr = chan.recvfrom(2048)
        except socket.timeout:
            break
        p = parse_packet(raw)
        if p and p[0] != ACK and p[1] < rcv_base:
            chan.sendto(make_packet(ACK, p[1]), addr)
    return bytes(out)