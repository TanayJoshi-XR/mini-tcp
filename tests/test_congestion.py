"""Pure-logic checks of the congestion controllers (no network). Run:
    python -m tests.test_congestion
"""
from protocol.congestion import Reno, Cubic


def approx(a, b, tol):
    assert abs(a - b) <= tol, f"{a} is not within {tol} of {b}"


def test_slow_start_doubles():
    cc = Reno(initial_cwnd=2)
    for expected in (4, 8, 16, 32):                 # one "round": ACK every packet in flight
        for _ in range(int(cc.cwnd)):
            cc.on_ack(1, 0, 0.04)
        assert cc.cwnd == expected, (cc.cwnd, expected)
    print("ok  slow start doubles every RTT: 2 -> 4 -> 8 -> 16 -> 32")


def test_avoidance_adds_one_per_rtt():
    cc = Reno(initial_cwnd=20, initial_ssthresh=10)
    for _ in range(20):
        cc.on_ack(1, 0, 0.04)
    approx(cc.cwnd, 21, 0.1)
    print("ok  congestion avoidance adds about 1 packet per RTT:", round(cc.cwnd, 2))


def test_fast_recovery_cycle():
    cc = Reno(initial_cwnd=40, initial_ssthresh=10)
    cc.on_fast_loss(flight=40, now=0)
    assert cc.ssthresh == 20 and cc.cwnd == 23 and cc.in_recovery
    cc.on_dup_in_recovery()
    assert cc.cwnd == 24
    cc.on_partial_ack(3)
    assert cc.cwnd == 22 and cc.in_recovery
    cc.on_recovery_exit()
    assert cc.cwnd == 20 and not cc.in_recovery
    print("ok  fast recovery: halve, inflate on dup ACKs, deflate on partial ACK, exit at ssthresh")


def test_timeout_collapses():
    cc = Reno(initial_cwnd=40, initial_ssthresh=10)
    cc.on_timeout(flight=40, now=0)
    assert cc.cwnd == 1 and cc.ssthresh == 20 and not cc.in_recovery
    for _ in range(19):
        cc.on_ack(1, 0, 0.04)
    assert cc.cwnd == 20 and cc.state == "avoidance"
    print("ok  timeout: cwnd=1, slow start back up to ssthresh=20, then avoidance")


def test_ssthresh_floor():
    cc = Reno()
    cc.on_timeout(flight=3, now=0)
    assert cc.ssthresh == 2
    print("ok  ssthresh never drops below 2")


def test_cubic_friendly_region_dominates_at_short_rtt():
    cc = Cubic(initial_cwnd=50, initial_ssthresh=10)      # tcp_friendly=True (the RFC default)
    cc.on_fast_loss(flight=50, now=0)
    cc.on_recovery_exit()
    now = 0.0
    while now < 3.35:
        for _ in range(max(1, int(cc.cwnd))):
            cc.on_ack(1, now, 0.04)
        now += 0.04
    assert cc.cwnd > 60            # Reno-like growth is faster than the cubic curve here
    print(f"ok  CUBIC with the RFC's Reno-friendly term: already {cc.cwnd:.1f} at t=3.35s "
          f"(the cubic curve alone would be ~50)")


def test_cubic_curve():
    cc = Cubic(initial_cwnd=50, initial_ssthresh=10, tcp_friendly=False)
    cc.on_fast_loss(flight=50, now=0)
    approx(cc.ssthresh, 35, 1e-9)
    cc.on_recovery_exit()
    approx(cc.cwnd, 35, 1e-9)
    now, rtt, last = 0.0, 0.04, cc.cwnd
    trace = {}
    while now < 8:
        for _ in range(max(1, int(cc.cwnd))):
            cc.on_ack(1, now, rtt)
        assert cc.cwnd >= last - 1e-9
        last = cc.cwnd
        now += rtt
        trace[round(now, 2)] = cc.cwnd
    approx(cc.k, ((50 - 35) / 0.4) ** (1 / 3), 1e-9)
    near_k = trace[min(trace, key=lambda t: abs(t - cc.k))]
    approx(near_k, 50, 5)                          # back near w_max after about K seconds
    assert cc.cwnd > 50                            # then it probes past the old maximum
    print(f"ok  CUBIC: K={cc.k:.2f}s, cwnd~{near_k:.1f} at t=K (w_max=50), "
          f"{cc.cwnd:.1f} at t=8s")


if __name__ == "__main__":
    test_slow_start_doubles()
    test_avoidance_adds_one_per_rtt()
    test_fast_recovery_cycle()
    test_timeout_collapses()
    test_ssthresh_floor()
    test_cubic_curve()
    test_cubic_friendly_region_dominates_at_short_rtt()
    print("\nALL CONGESTION-CONTROL CHECKS PASSED")
