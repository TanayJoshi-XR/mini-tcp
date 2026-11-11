"""A tiny network emulator: a bottleneck link with a finite drop-tail queue.

         sender ---> [ queue (N packets) ]--rate-->(propagation delay)---> receiver
                          full? -> the packet is DROPPED  (this is congestion)

Without a bottleneck, loopback never drops anything by itself, so congestion
control would have nothing to react to.
"""
import heapq
import itertools
import os
import random
import socket
import threading
import time
from collections import deque

from protocol import mini_tcp


class Link:
    """One direction of a link: queue -> transmission at `rate_bps` -> `delay` seconds."""

    def __init__(self, rate_bps, delay, queue_pkts, loss=0.0):
        self.rate = float(rate_bps)
        self.delay = delay
        self.queue_pkts = queue_pkts       # packets that fit in the buffer (incl. the one being sent)
        self.loss = loss                   # extra random loss (e.g. a bad wireless link)
        self.t0 = time.time()
        self.stats = {"offered": 0, "dropped_queue": 0, "dropped_random": 0, "delivered": 0}
        self.queue_log = []                # (time, queue occupancy) at each arrival
        self.drop_log = []                 # times at which the queue overflowed
        self._cv = threading.Condition()
        self._heap = []
        self._count = itertools.count()
        self._in_system = deque()          # departure times of packets still queued or in service
        self._busy_until = 0.0
        self._closed = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def send(self, sock, data, addr):
        now = time.time()
        with self._cv:
            self.stats["offered"] += 1
            if self.loss and random.random() < self.loss:
                self.stats["dropped_random"] += 1
                return
            q = self._in_system
            while q and q[0] <= now:
                q.popleft()
            if len(q) >= self.queue_pkts:                  # buffer full: tail drop
                self.stats["dropped_queue"] += 1
                self.drop_log.append(now - self.t0)
                return
            start = max(now, self._busy_until)
            done = start + len(data) * 8.0 / self.rate     # transmission time of this packet
            self._busy_until = done
            q.append(done)
            self.queue_log.append((now - self.t0, len(q)))
            heapq.heappush(self._heap, (done + self.delay, next(self._count), sock, data, addr))
            self._cv.notify()

    def _run(self):
        with self._cv:
            while not self._closed:
                if not self._heap:
                    self._cv.wait(0.2)
                    continue
                due = self._heap[0][0]
                now = time.time()
                if due > now:
                    self._cv.wait(due - now)
                    continue
                _, _, sock, data, addr = heapq.heappop(self._heap)
                try:
                    sock.sendto(data, addr)
                except OSError:
                    pass
                self.stats["delivered"] += 1

    def close(self):
        with self._cv:
            self._closed = True
            self._cv.notify()


class NetChannel:
    """Same interface as LossyChannel, but sends go through a Link."""

    def __init__(self, sock, link):
        self.sock, self.link = sock, link

    def sendto(self, data, addr):
        self.link.send(self.sock, data, addr)

    def recvfrom(self, n):
        return self.sock.recvfrom(n)

    def settimeout(self, t):
        self.sock.settimeout(t)


def bdp_packets(rate_bps, rtt, pkt_bytes=1041):
    """Bandwidth-delay product in packets: how many packets fit 'in the pipe'."""
    return rate_bps * rtt / (8.0 * pkt_bytes)


def run_flows(n_flows=1, size=1_000_000, rate_bps=4e6, delay=0.02, queue_pkts=30,
              make_cc=None, loss=0.0, send_kw=None, recv_kw=None, stagger=0.0):
    """Run n_flows transfers that share ONE bottleneck. Verifies every file arrives intact."""
    fwd = Link(rate_bps, delay, queue_pkts, loss)      # data direction: the bottleneck
    rev = Link(1e9, delay, 100_000)                    # ACK direction: fast, never congested
    send_kw = dict(send_kw or {})
    recv_kw = dict({"rcv_buf": 256}, **(recv_kw or {}))
    flows = []
    for _ in range(n_flows):
        rs = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ss = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for sk in (rs, ss):
            sk.bind(("127.0.0.1", 0))
            try:
                sk.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
            except OSError:
                pass
        flows.append({"rs": rs, "ss": ss, "data": os.urandom(size)})

    def recv_worker(f):
        try:
            f["got"] = mini_tcp.receive_file(NetChannel(f["rs"], rev), **recv_kw)
        except Exception as e:                          # reported after the join
            f["error"] = e

    def send_worker(f, i):
        try:
            time.sleep(i * stagger)
            f["stats"] = mini_tcp.send_file(
                NetChannel(f["ss"], fwd), f["rs"].getsockname(), f["data"],
                cc=make_cc() if make_cc else None, **send_kw)
        except Exception as e:
            f["error"] = e

    rthreads = [threading.Thread(target=recv_worker, args=(f,), daemon=True) for f in flows]
    sthreads = [threading.Thread(target=send_worker, args=(f, i), daemon=True)
                for i, f in enumerate(flows)]
    for t in rthreads + sthreads:
        t.start()
    for t in sthreads:
        t.join()
    for t in rthreads:
        t.join(timeout=10)
    time.sleep(0.1)
    fwd.close()
    rev.close()
    for f in flows:
        f["rs"].close()
        f["ss"].close()
    for f in flows:
        if "error" in f:
            raise f["error"]
        assert f.get("got") == f["data"], "FILE CORRUPTED!"

    out = []
    for f in flows:
        st = f["stats"]
        st["goodput_kBps"] = size / 1000.0 / st["transfer_time"]
        out.append(st)
    return {"flows": out, "link": fwd.stats, "queue_log": fwd.queue_log,
            "drop_log": fwd.drop_log, "link_t0": fwd.t0}
