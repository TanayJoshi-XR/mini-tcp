import os
import socket
import threading
import time
from protocol.channel import LossyChannel
from protocol import mini_tcp


def run_transfer(size=60_000, loss=0.1, corrupt=0.02, delay=0.01, jitter=0.0,
                 send_kw=None, recv_kw=None):
    data = os.urandom(size)
    rs = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rs.bind(("127.0.0.1", 0))
    ss = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ss.bind(("127.0.0.1", 0))
    rchan = LossyChannel(rs, loss=loss, corrupt=corrupt, delay=delay, jitter=jitter)
    schan = LossyChannel(ss, loss=loss, corrupt=corrupt, delay=delay, jitter=jitter)

    result = {}
    t = threading.Thread(target=lambda: result.update(
        data=mini_tcp.receive_file(rchan, **(recv_kw or {}))))
    t.start()
    start = time.time()
    stats = mini_tcp.send_file(schan, rs.getsockname(), data, **(send_kw or {}))
    elapsed = time.time() - start
    t.join()
    time.sleep(0.1)                     # let in-flight delayed packets drain
    rs.close()
    ss.close()

    assert result["data"] == data, "FILE CORRUPTED!"
    return elapsed, stats