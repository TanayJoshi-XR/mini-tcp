import socket
import time
from collections import deque
from .segment import SYN, ACK, FIN, MAX_PAYLOAD, make_segment, parse_segment
from .rtt import RttEstimator

POLL = 0.005


def send_file(chan, addr, data, window=16, fast_retransmit=True,
              time_wait=0.5, overall_timeout=120, cc=None, min_rto=0.05):
    """Send `data` reliably.

    cc=None  -> Phase 2 behaviour: a fixed window of `window` packets.
    cc=Reno() / Cubic() -> Phase 3: the window is cwnd, chosen by congestion control.
    """
    rtt = RttEstimator(min_rto=min_rto)
    chunks = [data[i:i + MAX_PAYLOAD] for i in range(0, len(data), MAX_PAYLOAD)]
    total = len(chunks)
    t0 = time.time()
    stats = {"timeouts": 0, "fast_retransmits": 0, "partial_retransmits": 0,
             "zero_window_acks": 0, "rtt_log": [], "clean_close": True,
             "cwnd_log": [], "events": [], "ack_log": [], "sent_total": 0,
             "t_start": t0}
    chan.settimeout(POLL)

    # ---- 1. handshake -------------------------------------------------
    tries = 0
    hs_start = time.time()
    while True:
        chan.sendto(make_segment(SYN), addr)
        deadline = time.time() + rtt.rto
        got = None
        while time.time() < deadline and got is None:
            try:
                raw, _ = chan.recvfrom(2048)
            except socket.timeout:
                continue
            s = parse_segment(raw)
            if s and s.flags == (SYN | ACK):
                got = s
        if got:
            break
        tries += 1
        rtt.backoff()
        if tries > 20:
            raise TimeoutError("handshake failed")
    if tries == 0:
        rtt.sample(time.time() - hs_start)          # the handshake is our first RTT sample
    peer_window = got.window
    chan.sendto(make_segment(ACK), addr)

    # ---- 2. data transfer ---------------------------------------------
    packets = [make_segment(0, s, 0, 0, c) for s, c in enumerate(chunks)]
    sent_at = [0.0] * total
    resent = [False] * total                        # for Karn's algorithm
    base = nxt = 0          # base = oldest unacked packet, nxt = next packet to send
    high = 0                # highest nxt ever reached (below it = already sent once)
    timer = None
    dup = 0
    last_win = peer_window
    recover = -1            # NewReno: highest packet outstanding at the last loss event

    def log(kind=None):
        now_rel = time.time() - t0
        if cc is not None:
            stats["cwnd_log"].append((now_rel, cc.cwnd, cc.ssthresh, nxt - base, cc.state))
        if kind:
            stats["events"].append((now_rel, kind))

    def resend(seq):
        chan.sendto(packets[seq], addr)
        sent_at[seq] = time.time()
        resent[seq] = True
        stats["sent_total"] += 1

    if cc is not None:
        log()

    while base < total:
        if time.time() - t0 > overall_timeout:
            raise TimeoutError("transfer took too long")

        # send as much as BOTH our window and the receiver's window allow
        wnd = window if cc is None else int(cc.cwnd)
        limit = base + max(1, min(wnd, peer_window))
        while nxt < min(limit, total):
            chan.sendto(packets[nxt], addr)
            stats["sent_total"] += 1
            sent_at[nxt] = time.time()
            if nxt < high:
                resent[nxt] = True                  # sent before: this is a retransmission
            if timer is None:
                timer = time.time()
            nxt += 1
            if nxt > high:
                high = nxt

        try:
            raw, _ = chan.recvfrom(2048)
        except socket.timeout:
            raw = None
        s = parse_segment(raw) if raw else None

        if s and (s.flags & ACK) and not (s.flags & (SYN | FIN)):
            now = time.time()
            peer_window = s.window
            if s.window == 0:
                stats["zero_window_acks"] += 1

            if base < s.ack <= high:                             # new data acknowledged
                acked = s.ack - base
                if not any(resent[base:s.ack]):                  # Karn's rule
                    sample = now - sent_at[s.ack - 1]
                    rtt.sample(sample)
                    stats["rtt_log"].append((now - t0, sample, rtt.srtt, rtt.rto))
                else:
                    rtt.reset_backoff()      # progress made, no valid sample: undo backoff
                base = s.ack
                if nxt < base:                # after a go-back, the ACK may jump past nxt
                    nxt = base
                dup = 0
                timer = now if base < nxt else None
                stats["ack_log"].append((now - t0, base))

                if cc is not None:
                    if cc.in_recovery:
                        if base > recover:                       # everything from before the loss is acked
                            cc.on_recovery_exit()
                            log("recovery_exit")
                        else:                                    # partial ACK: the next hole
                            resend(base)
                            stats["partial_retransmits"] += 1
                            cc.on_partial_ack(acked)
                            timer = time.time()
                    else:
                        cc.on_ack(acked, now, rtt.srtt or 0.05)
                    log()

            elif s.ack == base and nxt > base and last_win > 0:
                dup += 1                                         # a true duplicate ACK
                if cc is None:
                    if fast_retransmit and dup == 3:
                        resend(base)
                        stats["fast_retransmits"] += 1
                        timer = time.time()
                elif cc.in_recovery:
                    cc.on_dup_in_recovery()                      # window inflation
                    log()
                elif fast_retransmit and dup == 3 and base > recover:
                    cc.on_fast_loss(nxt - base, now)
                    recover = nxt - 1
                    resend(base)
                    stats["fast_retransmits"] += 1
                    timer = time.time()
                    log("fast_retransmit")
            last_win = s.window

        # timeout
        if timer is not None and time.time() - timer > rtt.rto:
            stats["timeouts"] += 1
            rtt.backoff()
            dup = 0
            if cc is None:
                resend(base)                                     # resend only the oldest
                timer = time.time()
            else:
                cc.on_timeout(nxt - base, time.time())
                recover = nxt - 1
                nxt = base                                       # go back: resend from the hole
                timer = None                                     # the send loop restarts it
                log("timeout")

    stats["transfer_time"] = time.time() - t0

    # ---- 3. teardown --------------------------------------------------
    fin = make_segment(FIN, seq=total)
    tries = 0
    while True:
        chan.sendto(fin, addr)
        deadline = time.time() + max(rtt.rto, 0.1)
        got = False
        while time.time() < deadline and not got:
            try:
                raw, _ = chan.recvfrom(2048)
            except socket.timeout:
                continue
            s = parse_segment(raw)
            if s and s.flags == (FIN | ACK) and s.ack == total + 1:
                got = True
        if got:
            break
        tries += 1
        if tries > 20:                  # all data was already acked, so this is harmless
            stats["clean_close"] = False
            break
    chan.sendto(make_segment(ACK, ack=total + 1), addr)

    end = time.time() + time_wait       # TIME_WAIT: re-ACK if the receiver repeats its FIN-ACK
    while time.time() < end:
        try:
            raw, _ = chan.recvfrom(2048)
        except socket.timeout:
            continue
        s = parse_segment(raw)
        if s and s.flags == (FIN | ACK):
            chan.sendto(make_segment(ACK, ack=total + 1), addr)

    stats.update(packets=total, srtt=rtt.srtt or 0.0, rto=rtt.rto,
                 retransmits=stats["timeouts"] + stats["fast_retransmits"]
                 + stats["partial_retransmits"])
    return stats


def receive_file(chan, rcv_buf=32, read_interval=0.0, close_rto=0.1, idle_limit=30):
    # LISTEN: wait for a SYN
    chan.settimeout(None)
    while True:
        raw, peer = chan.recvfrom(2048)
        s = parse_segment(raw)
        if s and s.flags == SYN:
            chan.sendto(make_segment(SYN | ACK, window=rcv_buf), peer)
            break

    expected = 0
    ooo = {}                    # out-of-order packets waiting for a gap to fill
    ready = deque()             # in-order packets the "application" hasn't read yet
    out = bytearray()
    last_adv = rcv_buf          # the window we last told the sender
    last_read = last_heard = time.time()
    chan.settimeout(POLL)

    while True:
        # the application reads from the buffer (slowly, if read_interval > 0)
        now = time.time()
        if read_interval == 0:
            while ready:
                out += ready.popleft()
        elif ready and now - last_read >= read_interval:
            out += ready.popleft()
            last_read = now

        free = max(0, rcv_buf - len(ready) - len(ooo))
        if last_adv == 0 and free > 0:                  # window re-opened: tell the sender
            chan.sendto(make_segment(ACK, ack=expected, window=free), peer)
            last_adv = free

        try:
            raw, _ = chan.recvfrom(2048)
        except socket.timeout:
            if time.time() - last_heard > idle_limit:
                raise TimeoutError("sender went silent")
            continue
        s = parse_segment(raw)
        if s is None:
            continue                                    # corrupt: drop silently
        last_heard = time.time()

        if s.flags & SYN:                               # our SYN-ACK was lost
            chan.sendto(make_segment(SYN | ACK, window=rcv_buf), peer)
            continue
        if (s.flags & FIN) and s.seq == expected:       # all data is here
            break
        if s.flags == ACK:                              # 3rd step of the handshake
            continue
        if s.flags == 0 and (s.seq == expected or
                             (s.seq > expected and s.seq not in ooo and free > 0)):
            ooo[s.seq] = s.payload
            while expected in ooo:                      # deliver in order
                ready.append(ooo.pop(expected))
                expected += 1

        # every data packet (new, duplicate or early FIN) gets a cumulative ACK + window
        free = max(0, rcv_buf - len(ready) - len(ooo))
        chan.sendto(make_segment(ACK, ack=expected, window=free), peer)
        last_adv = free

    while ready:
        out += ready.popleft()

    # LAST_ACK: keep resending FIN-ACK until the final ACK arrives
    fin_ack = make_segment(FIN | ACK, seq=expected, ack=expected + 1)
    for _ in range(10):
        chan.sendto(fin_ack, peer)
        deadline = time.time() + close_rto
        done = False
        while time.time() < deadline and not done:
            try:
                raw, _ = chan.recvfrom(2048)
            except socket.timeout:
                continue
            s = parse_segment(raw)
            if s and s.flags == ACK and s.ack == expected + 1:
                done = True
        if done:
            break
    return bytes(out)
