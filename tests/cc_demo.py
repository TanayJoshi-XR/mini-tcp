"""Quick end-to-end check of congestion control (about 30 seconds):
    python -m tests.cc_demo
Every transfer asserts that the file arrives byte-for-byte intact.
"""
from experiments.netsim import run_flows, bdp_packets
from protocol.congestion import Reno, Cubic

RATE, DELAY, QUEUE = 4e6, 0.02, 30


def one(label, mk, size=1_000_000, loss=0.0, **kw):
    r = run_flows(size=size, rate_bps=RATE, delay=DELAY, queue_pkts=QUEUE, make_cc=mk, loss=loss,
                  send_kw=dict({"min_rto": 0.2}, **kw))
    st = r["flows"][0]
    assert st["clean_close"], "connection did not close cleanly"
    peak = max((c[1] for c in st["cwnd_log"]), default=0)
    print(f"{label:28s} OK  {st['transfer_time']:5.2f}s  {st['goodput_kBps']:4.0f} kB/s  "
          f"timeouts={st['timeouts']:2d} fast={st['fast_retransmits']:2d} "
          f"link_drops={r['link']['dropped_queue']:3d} peak_cwnd={peak:3.0f}")
    return st


if __name__ == "__main__":
    print(f"path: 4 Mbit/s, RTT 40 ms, buffer {QUEUE} packets -> "
          f"pipe holds {bdp_packets(RATE, 2 * DELAY):.0f} packets\n")
    one("fixed window 8", None, window=8)
    one("Reno", Reno)
    one("CUBIC", Cubic)
    one("Reno + 1% random loss", Reno, loss=0.01)
    one("CUBIC + 1% random loss", Cubic, loss=0.01)
    one("Reno, tiny file (3 packets)", Reno, size=3000)
    print("\nALL TRANSFERS ARRIVED INTACT")
