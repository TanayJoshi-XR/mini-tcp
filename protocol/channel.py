import random
import threading


class LossyChannel:
    def __init__(self, sock, loss=0.0, corrupt=0.0, delay=0.0, jitter=0.0):
        self.sock = sock
        self.loss, self.corrupt = loss, corrupt
        self.delay, self.jitter = delay, jitter

    def sendto(self, data, addr):
        if random.random() < self.loss:
            return                                   # packet "lost"
        if random.random() < self.corrupt:
            i = random.randrange(len(data))
            data = data[:i] + bytes([data[i] ^ 0xFF]) + data[i + 1:]
        d = max(0.0, self.delay + random.uniform(-self.jitter, self.jitter))
        if d > 0:                                    # jitter also causes reordering
            threading.Timer(d, self.sock.sendto, (data, addr)).start()
        else:
            self.sock.sendto(data, addr)

    def recvfrom(self, n):
        return self.sock.recvfrom(n)

    def settimeout(self, t):
        self.sock.settimeout(t)