class RttEstimator:
    ALPHA = 1 / 8      # weight of a new sample in SRTT
    BETA = 1 / 4       # weight of a new deviation in RTTVAR
    K = 4

    def __init__(self, initial_rto=0.2, min_rto=0.05, max_rto=2.0, granularity=0.005):
        # RFC says min RTO = 1 s; we use 50 ms because our "network" is fast
        self.srtt = None
        self.rttvar = None
        self.rto = initial_rto
        self.min_rto, self.max_rto, self.g = min_rto, max_rto, granularity
        self.initial_rto = initial_rto

    def sample(self, r):
        if self.srtt is None:                       # first measurement
            self.srtt = r
            self.rttvar = r / 2
        else:                                       # RTTVAR first, using the OLD srtt
            self.rttvar = (1 - self.BETA) * self.rttvar + self.BETA * abs(self.srtt - r)
            self.srtt = (1 - self.ALPHA) * self.srtt + self.ALPHA * r
        rto = self.srtt + max(self.g, self.K * self.rttvar)
        self.rto = min(self.max_rto, max(self.min_rto, rto))

    def backoff(self):
        self.rto = min(self.max_rto, self.rto * 2)

    def reset_backoff(self):
        """Forward progress was made: undo exponential backoff."""
        if self.srtt is None:
            self.rto = self.initial_rto
        else:
            rto = self.srtt + max(self.g, self.K * self.rttvar)
            self.rto = min(self.max_rto, max(self.min_rto, rto))
