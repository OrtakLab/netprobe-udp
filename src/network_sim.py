"""
NetProbe Network Simulator

Wraps a UDP socket to inject packet loss and artificial delay.
Used by both server and client for testing under degraded conditions.

This module is intentionally standalone — import and wrap any socket:

    from network_sim import SimulatedSocket
    raw_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sim_sock = SimulatedSocket(raw_sock, loss_rate=0.1, delay_ms=50)
"""

import random
import socket
import time


class SimulatedSocket:
    """
    Thin wrapper around a UDP socket that simulates network impairments.

    loss_rate  : probability [0, 1) that a received packet is silently dropped.
    delay_ms   : fixed delay added before delivering each received packet (ms).
    send_loss  : probability [0, 1) that a sent packet is silently dropped.
    """

    def __init__(self, sock: socket.socket,
                 loss_rate: float = 0.0,
                 delay_ms: float = 0.0,
                 send_loss: float = 0.0):
        self._sock = sock
        self.loss_rate = loss_rate
        self.delay_ms = delay_ms
        self.send_loss = send_loss

        self.stats = {
            "recv_total": 0,
            "recv_dropped": 0,
            "send_total": 0,
            "send_dropped": 0,
        }

    # ---- Delegate attribute access to the underlying socket ----

    def __getattr__(self, name):
        return getattr(self._sock, name)

    # ---- Overridden methods ----

    def recvfrom(self, bufsize: int):
        """Block until a non-dropped packet arrives."""
        while True:
            data, addr = self._sock.recvfrom(bufsize)
            self.stats["recv_total"] += 1

            if self.loss_rate > 0 and random.random() < self.loss_rate:
                self.stats["recv_dropped"] += 1
                continue   # silently discard, keep waiting

            if self.delay_ms > 0:
                time.sleep(self.delay_ms / 1000.0)

            return data, addr

    def sendto(self, data: bytes, addr):
        self.stats["send_total"] += 1
        if self.send_loss > 0 and random.random() < self.send_loss:
            self.stats["send_dropped"] += 1
            return len(data)   # pretend it was sent
        return self._sock.sendto(data, addr)

    def report(self) -> dict:
        s = self.stats
        return {
            **s,
            "recv_loss_rate": (s["recv_dropped"] / s["recv_total"]
                               if s["recv_total"] else 0.0),
            "send_loss_rate": (s["send_dropped"] / s["send_total"]
                               if s["send_total"] else 0.0),
        }
