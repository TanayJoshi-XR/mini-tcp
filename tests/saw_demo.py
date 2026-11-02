import os
import socket
import threading
import time
from protocol.channel import LossyChannel
from protocol.stop_and_wait import send_file, receive_file


def run(loss, corrupt=0.0, size=50_000):
    data = os.urandom(size)
    rs = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rs.bind(("127.0.0.1", 0))
    ss = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ss.bind(("127.0.0.1", 0))
    rchan = LossyChannel(rs, loss=loss, corrupt=corrupt)
    schan = LossyChannel(ss, loss=loss, corrupt=corrupt)

    result = {}
    t = threading.Thread(target=lambda: result.update(data=receive_file(rchan)))
    t.start()
    start = time.time()
    stats = send_file(schan, rs.getsockname(), data)
    elapsed = time.time() - start
    t.join()

    assert result["data"] == data, "FILE CORRUPTED!"
    print(f"loss={loss:.0%} corrupt={corrupt:.0%}  OK  "
          f"{elapsed:5.2f}s  {stats['retransmits']} retransmits")


if __name__ == "__main__":
    for loss in (0.0, 0.1, 0.2, 0.3):
        run(loss, corrupt=0.05)
