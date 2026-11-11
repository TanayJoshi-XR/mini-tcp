"""Two flows share one bottleneck. AIMD should drive them toward an equal split.

    python -m experiments.fairness             (takes about 25 seconds)

Jain's fairness index: 1.0 = perfectly equal, 0.5 = one flow takes everything (2 flows).
"""
import bisect
import os
import matplotlib.pyplot as plt

from experiments import plotstyle as ps
from experiments.netsim import run_flows
from protocol.congestion import Reno

RATE, DELAY, QUEUE = 4e6, 0.02, 30
SIZE = 3_000_000
STAGGER = 1.0              # flow 2 starts one second after flow 1
BIN = 0.5
PKT = 1024


def acked_at(log, t):
    """Packets acknowledged by time t (log = [(t, base), ...] with growing t)."""
    i = bisect.bisect_right([x[0] for x in log], t)
    return log[i - 1][1] if i else 0


if __name__ == "__main__":
    ps.apply()
    r = run_flows(n_flows=2, size=SIZE, rate_bps=RATE, delay=DELAY, queue_pkts=QUEUE, make_cc=Reno,
                  stagger=STAGGER, send_kw={"min_rto": 0.2})
    f1, f2 = r["flows"]
    origin = min(f1["t_start"], f2["t_start"])
    offs = [f["t_start"] - origin for f in (f1, f2)]
    logs = [[(t + o, b) for t, b in f["ack_log"]] for f, o in zip((f1, f2), offs)]
    ends = [o + f["transfer_time"] for f, o in zip((f1, f2), offs)]

    # overlap = both flows active (flow 2 has started, nobody has finished)
    lo, hi = offs[1] + 1.0, min(ends)          # skip the first second of flow 2 (slow start)
    avg = [(acked_at(l, hi) - acked_at(l, lo)) * PKT / 1000 / (hi - lo) for l in logs]
    jain = (avg[0] + avg[1]) ** 2 / (2 * (avg[0] ** 2 + avg[1] ** 2))

    fig, ax = plt.subplots(figsize=(10, 5.2))
    ax.axvspan(lo, hi, color=ps.MUTED, alpha=0.12, lw=0)
    for name, log, end in zip(("flow 1", "flow 2"), logs, ends):
        ts, gs = [], []
        t = log[0][0]
        while t + BIN <= end:
            ts.append(t + BIN / 2)
            gs.append((acked_at(log, t + BIN) - acked_at(log, t)) * PKT / 1000 / BIN)
            t += BIN
        ax.plot(ts, gs, color=ps.COLORS[name], label=name)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("goodput (kB/s, 0.5 s bins)")
    ax.set_ylim(0, RATE / 8 / 1041 * 1024 / 1000 * 1.1)
    ax.set_title(f"Two Reno flows on one bottleneck: Jain's fairness index {jain:.2f} "
                 f"while both are active", pad=12)
    ax.text((lo + hi) / 2, ax.get_ylim()[1] * 0.97, "both flows active", ha="center", va="top",
            color=ps.INK2, fontsize=9.5)
    ax.legend(loc="lower right")

    os.makedirs("results", exist_ok=True)
    plt.savefig("results/fairness.png", dpi=150, bbox_inches="tight")

    print(f"flow 1: {f1['transfer_time']:.1f}s  timeouts={f1['timeouts']}  fast={f1['fast_retransmits']}")
    print(f"flow 2: {f2['transfer_time']:.1f}s  timeouts={f2['timeouts']}  fast={f2['fast_retransmits']}")
    print(f"average goodput while both active ({lo:.1f}s to {hi:.1f}s): "
          f"flow 1 {avg[0]:.0f} kB/s, flow 2 {avg[1]:.0f} kB/s, Jain index {jain:.3f}")
    print("saved results/fairness.png")
    plt.show()
