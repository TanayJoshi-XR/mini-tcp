"""Congestion-control algorithms for mini-TCP.

All windows are measured in PACKETS (our sequence numbers count packets, not bytes).

The sender (mini_tcp.send_file) owns the retransmission logic.  A controller only
owns the numbers: cwnd (how many packets may be in flight), ssthresh (the
slow-start threshold) and whether we are in fast recovery.

Phases of the classic (Reno / NewReno) algorithm:

  slow start            cwnd < ssthresh   cwnd grows by 1 per ACK  -> doubles every RTT
  congestion avoidance  cwnd >= ssthresh  cwnd grows by 1/cwnd per ACK -> +1 per RTT
  fast recovery         entered on 3 duplicate ACKs (one packet lost, the rest arrive)
  timeout               the severe case: cwnd back to 1, slow start again
"""


class Reno:
    name = "Reno"

    # initial_ssthresh=64 packets (= 64 KB with 1 KB packets) is the classic default of
    # older TCP stacks.  Without it, slow start doubles blindly until the queue
    # overflows and a huge burst of packets is lost at once.
    def __init__(self, initial_cwnd=2.0, initial_ssthresh=64.0, min_ssthresh=2.0):
        self.initial_cwnd = float(initial_cwnd)
        self.cwnd = float(initial_cwnd)
        self.ssthresh = float(initial_ssthresh)
        self.min_ssthresh = float(min_ssthresh)
        self.in_recovery = False

    @property
    def state(self):
        if self.in_recovery:
            return "recovery"
        return "slow_start" if self.cwnd < self.ssthresh else "avoidance"

    # ---- growth: new data was acknowledged (not in recovery) ---------------
    def on_ack(self, acked, now, rtt):
        if self.cwnd < self.ssthresh:
            # slow start: +1 per ACK.  A cumulative ACK may cover many packets,
            # so we cap the credit at 2 (RFC 3465, "appropriate byte counting").
            self.cwnd += min(acked, 2)
        else:
            self._avoidance(acked, now, rtt)

    def _avoidance(self, acked, now, rtt):
        self.cwnd += acked / self.cwnd              # about +1 packet per RTT

    # ---- decrease -----------------------------------------------------------
    def _new_ssthresh(self, flight, now):
        # multiplicative decrease: half of what was in flight (RFC 5681)
        return max(flight / 2.0, self.min_ssthresh)

    def on_fast_loss(self, flight, now):
        """3 duplicate ACKs: enter fast recovery."""
        self.ssthresh = self._new_ssthresh(flight, now)
        self.cwnd = self.ssthresh + 3               # +3: the 3 packets that caused the dup ACKs
        self.in_recovery = True

    def on_dup_in_recovery(self):
        self.cwnd += 1                              # each dup ACK means one packet left the network

    def on_partial_ack(self, acked):
        """NewReno: an ACK that does not cover everything sent before the loss."""
        self.cwnd = max(self.cwnd - acked + 1, 1.0)  # deflate by what was acked, +1 for the retransmit

    def on_recovery_exit(self):
        self.cwnd = self.ssthresh                   # deflate to the new, lower window
        self.in_recovery = False

    def on_timeout(self, flight, now):
        """Severe loss: collapse to 1 packet and slow-start again."""
        self.ssthresh = self._new_ssthresh(flight, now)
        self.cwnd = 1.0
        self.in_recovery = False


class Cubic(Reno):
    """CUBIC (RFC 8312, simplified): after a loss the window follows a cubic curve
    that is flat around the old maximum W_max, so it probes cautiously there,
    and grows fast far from it.  Growth depends on elapsed TIME, not on RTT count."""
    name = "CUBIC"
    C = 0.4          # how aggressive the cubic curve is (packets / second^3)
    BETA = 0.7       # window after a loss = 0.7 * window before (Reno uses 0.5)

    def __init__(self, tcp_friendly=True, **kw):
        # tcp_friendly=True follows the RFC: never grow slower than a Reno-like flow.
        # On a short-RTT, small-window path that Reno-like term dominates, so the
        # cubic curve is hidden; tcp_friendly=False shows the pure cubic shape.
        super().__init__(**kw)
        self.tcp_friendly = tcp_friendly
        self.w_max = 0.0
        self.epoch = None        # start time of the current growth period
        self.k = 0.0             # time the curve needs to get back to w_max
        self.origin = 0.0
        self.w_est = 0.0         # what Reno would have, so we're never slower than Reno

    def _new_ssthresh(self, flight, now):
        w = max(1.0, min(self.cwnd, max(flight, 1)))
        if w < self.w_max:                          # fast convergence: leave room for new flows
            self.w_max = w * (1 + self.BETA) / 2
        else:
            self.w_max = w
        self.epoch = None
        return max(w * self.BETA, self.min_ssthresh)

    def _avoidance(self, acked, now, rtt):
        if self.epoch is None:
            self.epoch = now
            if self.cwnd < self.w_max:
                self.k = ((self.w_max - self.cwnd) / self.C) ** (1.0 / 3.0)
                self.origin = self.w_max
            else:
                self.k = 0.0
                self.origin = self.cwnd
            self.w_est = self.cwnd
        t = now - self.epoch + rtt
        target = self.origin + self.C * (t - self.k) ** 3
        self.w_est += 3 * (1 - self.BETA) / (1 + self.BETA) * acked / self.cwnd
        if self.tcp_friendly:
            target = max(target, self.w_est)
        if target > self.cwnd:
            inc = (target - self.cwnd) / self.cwnd * acked
            self.cwnd += min(inc, 0.5 * acked)      # never faster than +50% per RTT
        else:
            self.cwnd += 0.01 * acked / self.cwnd   # tiny growth when above the curve
