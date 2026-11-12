"""Run one Mini-TCP transfer on loopback so you can watch it in Wireshark.

    python wireshark/demo_transfer.py              # congestion: Reno over a bottleneck (default)
    python wireshark/demo_transfer.py lossy        # random loss + corrupted packets (shows BAD CRC)

Start the Wireshark capture on the loopback interface FIRST, then run this.
Everything is sent as UDP between 127.0.0.1 ports, which is what Wireshark records.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from experiments.netsim import run_flows          # noqa: E402
from experiments.common import run_transfer       # noqa: E402
from protocol.congestion import Reno              # noqa: E402


def congestion():
    print("Reno transfer of 300 kB through a 4 Mbit/s bottleneck with a 30-packet buffer...")
    r = run_flows(size=300_000, rate_bps=4e6, delay=0.02, queue_pkts=30, make_cc=Reno,
                  send_kw={"min_rto": 0.2})
    st = r["flows"][0]
    print(f"done in {st['transfer_time']:.2f}s, {st['goodput_kBps']:.0f} kB/s, "
          f"timeouts={st['timeouts']}, fast retransmits={st['fast_retransmits']}, "
          f"packets dropped by the bottleneck={r['link']['dropped_queue']}")


def lossy():
    print("40 kB transfer over a channel with 10% loss and 5% corruption...")
    elapsed, st = run_transfer(size=40_000, loss=0.10, corrupt=0.05, delay=0.01,
                               send_kw={"window": 8, "min_rto": 0.05})
    print(f"done in {elapsed:.2f}s, timeouts={st['timeouts']}, retransmits={st['retransmits']}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "congestion"
    {"congestion": congestion, "lossy": lossy}[mode]()
