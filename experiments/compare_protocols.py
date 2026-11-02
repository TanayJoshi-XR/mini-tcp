import os
import socket
import threading
import time
import statistics
import matplotlib.pyplot as plt

from protocol.channel import LossyChannel
from protocol import stop_and_wait, go_back_n, selective_repeat

WINDOW = 8
TIMEOUT = 0.1       # retransmission timer (seconds)
DELAY = 0.01        # one-way delay: 10 ms, so RTT is about 20 ms
SIZE = 30_000
TRIALS = 3
LOSSES = [0.0, 0.05, 0.10, 0.20, 0.30]

PROTOCOLS = {
    "Stop-and-Wait": (
        lambda ch, a, d: stop_and_wait.send_file(ch, a, d, timeout=TIMEOUT),
        lambda ch: stop_and_wait.receive_file(ch, linger=1.0)),
    "Go-Back-N": (
        lambda ch, a, d: go_back_n.send_file(ch, a, d, window=WINDOW, timeout=TIMEOUT),
        lambda ch: go_back_n.receive_file(ch, linger=1.0)),
    "Selective Repeat": (
        lambda ch, a, d: selective_repeat.send_file(ch, a, d, window=WINDOW, timeout=TIMEOUT),
        lambda ch: selective_repeat.receive_file(ch, window=WINDOW, linger=1.0)),
}


def transfer(name, loss, corrupt=0.02):
    send, recv = PROTOCOLS[name]
    data = os.urandom(SIZE)
    rs = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rs.bind(("127.0.0.1", 0))
    ss = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ss.bind(("127.0.0.1", 0))
    rchan = LossyChannel(rs, loss=loss, corrupt=corrupt, delay=DELAY)
    schan = LossyChannel(ss, loss=loss, corrupt=corrupt, delay=DELAY)

    result = {}
    t = threading.Thread(target=lambda: result.update(data=recv(rchan)))
    t.start()
    start = time.time()
    stats = send(schan, rs.getsockname(), data)
    elapsed = time.time() - start
    t.join()
    rs.close()
    ss.close()

    assert result["data"] == data, f"{name}: FILE CORRUPTED"
    return elapsed, stats["retransmits"]


if __name__ == "__main__":
    results = {name: [] for name in PROTOCOLS}
    for loss in LOSSES:
        for name in PROTOCOLS:
            runs = [transfer(name, loss) for _ in range(TRIALS)]
            t = statistics.mean(r[0] for r in runs)
            rt = statistics.mean(r[1] for r in runs)
            kbps = SIZE / 1000 / t
            results[name].append(kbps)
            print(f"loss={loss:4.0%}  {name:17s} {t:5.2f}s  "
                  f"{kbps:6.1f} KB/s  {rt:5.1f} retransmits")

    plt.figure(figsize=(8, 5))
    for name, ys in results.items():
        plt.plot([l * 100 for l in LOSSES], ys, marker="o", label=name)
    plt.xlabel("Packet loss (%)")
    plt.ylabel("Throughput (KB/s)")
    plt.title("Throughput vs packet loss (RTT about 20 ms, window = 8)")
    plt.grid(True, alpha=0.3)
    plt.legend()
    os.makedirs("results", exist_ok=True)
    plt.savefig("results/throughput_vs_loss.png", dpi=150, bbox_inches="tight")
    plt.show()