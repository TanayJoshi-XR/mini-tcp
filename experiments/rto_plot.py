import os
import matplotlib.pyplot as plt
from experiments.common import run_transfer

if __name__ == "__main__":
    _, st = run_transfer(size=200_000, loss=0.05, corrupt=0.0, delay=0.02, jitter=0.01)
    log = st["rtt_log"]
    t = [x[0] for x in log]
    plt.figure(figsize=(9, 5))
    plt.plot(t, [x[1] * 1000 for x in log], ".", alpha=0.4, label="RTT sample")
    plt.plot(t, [x[2] * 1000 for x in log], label="SRTT")
    plt.plot(t, [x[3] * 1000 for x in log], label="RTO")
    plt.xlabel("Time (s)")
    plt.ylabel("Milliseconds")
    plt.title("RTT estimation: SRTT and RTO follow the measured RTT")
    plt.grid(True, alpha=0.3)
    plt.legend()
    os.makedirs("results", exist_ok=True)
    plt.savefig("results/rto_adaptation.png", dpi=150, bbox_inches="tight")
    plt.show()