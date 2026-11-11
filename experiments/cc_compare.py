"""Fixed windows vs congestion control on the same bottleneck.

    python -m experiments.cc_compare           (takes about 2 minutes)

Fixed window 64 is too big for this path, so it collapses.  To keep the run short it
sends 0.5 MB instead of 3 MB; goodput (kB/s) is still comparable.
"""
import os
import statistics
import matplotlib.pyplot as plt

from experiments import plotstyle as ps
from experiments.netsim import run_flows
from protocol.congestion import Reno, Cubic

RATE, DELAY, QUEUE = 4e6, 0.02, 30
LINK_MAX = RATE / 8 / 1041 * 1024 / 1000          # kB/s of payload the link can carry

# (label, controller factory, extra send_file args, size in bytes, trials)
VARIANTS = [
    ("Fixed window 8",  None,  {"window": 8},  3_000_000, 2),
    ("Fixed window 64", None,  {"window": 64}, 500_000,   1),
    ("Reno",            Reno,  {},             3_000_000, 2),
    ("CUBIC",           lambda: Cubic(tcp_friendly=False), {}, 3_000_000, 2),
]

if __name__ == "__main__":
    ps.apply()
    res = {}
    for label, mk, kw, size, trials in VARIANTS:
        runs = []
        for _ in range(trials):
            r = run_flows(size=size, rate_bps=RATE, delay=DELAY, queue_pkts=QUEUE, make_cc=mk,
                          send_kw=dict({"min_rto": 0.2, "overall_timeout": 150}, **kw))
            runs.append(r)
        gp = statistics.mean(r["flows"][0]["goodput_kBps"] for r in runs)
        waste = statistics.mean(
            100 * (r["flows"][0]["sent_total"] - r["flows"][0]["packets"]) / r["flows"][0]["sent_total"]
            for r in runs)
        drops = statistics.mean(r["link"]["dropped_queue"] for r in runs)
        to = statistics.mean(r["flows"][0]["timeouts"] for r in runs)
        res[label] = dict(goodput=gp, waste=waste, drops=drops, timeouts=to, run=runs[0])
        print(f"{label:16s} goodput {gp:5.0f} kB/s  wasted sends {waste:4.1f}%  "
              f"link drops {drops:5.0f}  timeouts {to:5.1f}  ({trials} run{'s' if trials > 1 else ''})",
              flush=True)

    labels = [v[0] for v in VARIANTS]
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), gridspec_kw={"width_ratios": [1, 1, 1.4],
                                                                 "wspace": 0.28})
    # (a) goodput
    ax = axes[0]
    vals = [res[l]["goodput"] for l in labels]
    ax.bar(range(len(labels)), vals, width=0.6, color=[ps.COLORS[l] for l in labels])
    ax.axhline(LINK_MAX, color=ps.INK2, lw=1, ls=(0, (4, 3)))
    ax.text(len(labels) - 0.5, LINK_MAX + 8, f"link limit {LINK_MAX:.0f}", ha="right",
            color=ps.INK2, fontsize=9.5)
    for i, v in enumerate(vals):
        ax.text(i, v + 8, f"{v:.0f}", ha="center", va="bottom", color=ps.INK, fontsize=10)
    ax.set_ylim(0, LINK_MAX * 1.15)
    ax.set_xticks(range(len(labels)), [l.replace(" ", "\n", 1) for l in labels], fontsize=9)
    ax.set_title("Goodput (kB/s), higher is better", pad=10)
    ax.grid(False, axis="x")

    # (b) wasted transmissions
    ax = axes[1]
    vals = [res[l]["waste"] for l in labels]
    ax.bar(range(len(labels)), vals, width=0.6, color=[ps.COLORS[l] for l in labels])
    for i, v in enumerate(vals):
        ax.text(i, v + 0.4, f"{v:.1f}%", ha="center", va="bottom", color=ps.INK, fontsize=10)
    ax.set_ylim(0, max(vals) * 1.2 + 1)
    ax.set_xticks(range(len(labels)), [l.replace(" ", "\n", 1) for l in labels], fontsize=9)
    ax.set_title("Wasted sends (%), lower is better", pad=10)
    ax.grid(False, axis="x")

    # (c) cwnd traces
    ax = axes[2]
    ymax = 90
    clipped = []
    for name in ("Reno", "CUBIC"):
        log = res[name]["run"]["flows"][0]["cwnd_log"]
        ax.plot([x[0] for x in log], [x[1] for x in log], color=ps.COLORS[name], label=name)
        clipped.append(f"{name} {max(x[1] for x in log):.0f}")
    ax.set_ylim(0, ymax)
    ax.set_xlabel("time (s)\ny-axis cut at %d; recovery peaks: %s" % (ymax, ", ".join(clipped)))
    ax.set_ylabel("cwnd (packets)")
    ax.set_title("Congestion window over time", pad=10)
    ax.legend(loc="lower right")

    os.makedirs("results", exist_ok=True)
    plt.savefig("results/cc_compare.png", dpi=150, bbox_inches="tight")
    print("\nsaved results/cc_compare.png")
    plt.show()
