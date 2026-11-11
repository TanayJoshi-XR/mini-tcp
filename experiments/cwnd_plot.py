"""The classic congestion-window sawtooth, with the bottleneck queue underneath.

    python -m experiments.cwnd_plot            (takes about 15 seconds)
"""
import os
import matplotlib.pyplot as plt

from experiments import plotstyle as ps
from experiments.netsim import run_flows, bdp_packets
from protocol.congestion import Reno

RATE, DELAY, QUEUE = 4e6, 0.02, 30          # 4 Mbit/s, 20 ms each way, 30-packet buffer
SIZE = 5_000_000
YMAX = 80

if __name__ == "__main__":
    ps.apply()
    print("running one Reno transfer through the bottleneck...")
    r = run_flows(size=SIZE, rate_bps=RATE, delay=DELAY, queue_pkts=QUEUE, make_cc=Reno,
                  send_kw={"min_rto": 0.2})
    st = r["flows"][0]
    bdp = bdp_packets(RATE, 2 * DELAY)
    capacity = bdp + QUEUE

    log = st["cwnd_log"]
    t = [x[0] for x in log]
    cwnd = [x[1] for x in log]
    ssth = [x[2] if x[2] < 1e8 else None for x in log]
    states = [x[4] for x in log]

    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(11, 7.5), sharex=True,
                                  gridspec_kw={"height_ratios": [3, 1.3], "hspace": 0.12})

    # shade fast-recovery periods
    start = None
    for ti, s in zip(t, states):
        if s == "recovery" and start is None:
            start = ti
        elif s != "recovery" and start is not None:
            ax.axvspan(start, ti, color=ps.MUTED, alpha=0.15, lw=0)
            start = None
    if start is not None:
        ax.axvspan(start, t[-1], color=ps.MUTED, alpha=0.15, lw=0)

    ax.plot(t, cwnd, color=ps.BLUE, label="cwnd (congestion window)")
    ax.step([a for a, b in zip(t, ssth) if b is not None], [b for b in ssth if b is not None],
            where="post", color=ps.ORANGE, label="ssthresh (slow-start threshold)")
    ax.axhline(capacity, color=ps.INK2, lw=1, ls=(0, (4, 3)))
    ax.text(1.5, capacity + 3.2, f"path capacity ~ {capacity:.0f} packets", ha="left", va="bottom",
            color=ps.INK2, fontsize=9.5)

    ev_t = {k: [e[0] for e in st["events"] if e[1] == k] for k in ("fast_retransmit", "timeout")}
    if ev_t["fast_retransmit"]:
        yy = [next(c for tt, c, *_ in log if tt >= x) for x in ev_t["fast_retransmit"]]
        ax.plot(ev_t["fast_retransmit"], [min(y, YMAX - 2) for y in yy], "v", color=ps.INK, ms=9,
                mec=ps.SURFACE, mew=2, ls="none", label="fast retransmit (3 duplicate ACKs)")
    if ev_t["timeout"]:
        ax.plot(ev_t["timeout"], [1.5] * len(ev_t["timeout"]), "X", color=ps.INK, ms=9,
                mec=ps.SURFACE, mew=2, ls="none", label="timeout")

    peak = max(cwnd)
    ax.set_ylim(0, YMAX)
    if peak > YMAX:
        ax.text(0, 1.015, f"y-axis cut at {YMAX}: cwnd is inflated up to {peak:.0f} during fast "
                f"recovery (grey bands). Path capacity = pipe {bdp:.0f} + buffer {QUEUE} packets.",
                transform=ax.transAxes, va="bottom", fontsize=9.5, color=ps.INK2)
    ax.set_ylabel("packets")
    ax.set_title("Reno congestion window: slow start, then additive increase / multiplicative decrease",
                 pad=28)
    ax.legend(loc="lower right", ncol=1, fontsize=9.5)

    # bottom panel: queue occupancy at the bottleneck
    shift = st["t_start"] - r["link_t0"]
    q = r["queue_log"]
    ax2.step([a - shift for a, b in q], [b for a, b in q], where="post", color=ps.BLUE, lw=1.5)
    ax2.axhline(QUEUE, color=ps.INK2, lw=1, ls=(0, (4, 3)))
    ax2.text(t[-1], QUEUE + 1.5, f"buffer limit = {QUEUE} packets", ha="right", va="bottom",
             color=ps.INK2, fontsize=9.5)
    drops = [d - shift for d in r["drop_log"]]
    ax2.plot(drops, [QUEUE + 9] * len(drops), "|", color=ps.INK, ms=10, mew=1.5, ls="none")
    ax2.set_ylim(0, QUEUE + 13)
    ax2.set_ylabel("queue (packets)")
    ax2.set_xlabel("time (s)")
    ax2.set_title(f"Bottleneck queue; each black tick is a dropped packet ({len(drops)} total)",
                  fontsize=10.5, pad=6)
    ax2.set_xlim(0, t[-1])

    os.makedirs("results", exist_ok=True)
    plt.savefig("results/cwnd_sawtooth.png", dpi=150, bbox_inches="tight")

    link_max = RATE / 8 / 1041 * 1024 / 1000
    print(f"\ntransfer: {st['transfer_time']:.1f}s, goodput {st['goodput_kBps']:.0f} kB/s "
          f"({100 * st['goodput_kBps'] / link_max:.0f}% of the {link_max:.0f} kB/s link limit)")
    print(f"timeouts={st['timeouts']}  fast retransmits={st['fast_retransmits']}  "
          f"partial-ACK retransmits={st['partial_retransmits']}  link drops={r['link']['dropped_queue']}")
    print("saved results/cwnd_sawtooth.png")
    plt.show()
