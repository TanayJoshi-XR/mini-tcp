import statistics
from experiments.common import run_transfer

if __name__ == "__main__":
    print("== A. Reliability under loss ==")
    for loss in (0.0, 0.1, 0.2, 0.3):
        _, st = run_transfer(loss=loss)
        print(f"loss={loss:.0%}  OK  {st['transfer_time']:.2f}s  "
              f"timeouts={st['timeouts']:3d}  fast_retx={st['fast_retransmits']:3d}  "
              f"srtt={st['srtt'] * 1000:.0f}ms  rto={st['rto'] * 1000:.0f}ms")

    print("\n== B. Fast retransmit off vs on (10% loss, mean of 5 runs) ==")
    for fr in (False, True):
        times = [run_transfer(loss=0.1, send_kw={"fast_retransmit": fr})[1]["transfer_time"]
                 for _ in range(5)]
        print(f"fast_retransmit={fr!s:5}  {statistics.mean(times):.2f}s")

    print("\n== C. Flow control: receiver app reads 1 packet per 20 ms ==")
    size = 40_000
    _, st = run_transfer(size=size, loss=0.0, corrupt=0.0,
                         recv_kw={"rcv_buf": 8, "read_interval": 0.02})
    n = -(-size // 1024)
    print(f"{n} packets, took {st['transfer_time']:.2f}s "
          f"(reader limit about {n * 0.02:.2f}s), zero-window ACKs: {st['zero_window_acks']}")