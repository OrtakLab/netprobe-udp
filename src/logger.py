"""
NetProbe event logger — writes per-transfer CSV logs.

CSV columns: timestamp, event, seq_num, detail
"""

import csv
import os
import time
from datetime import datetime


EVENTS = {
    "SEND":          "Packet sent",
    "ACK_RECV":      "ACK received",
    "TIMEOUT":       "Timeout waiting for ACK",
    "RETRANSMIT":    "Packet retransmitted",
    "DROP_SIM":      "Packet dropped by simulator",
    "DUPLICATE":     "Duplicate packet discarded",
    "RECV":          "Packet received",
    "TRANSFER_DONE": "Transfer completed",
    "TRANSFER_FAIL": "Transfer failed (max retries)",
    "INTEGRITY_OK":  "File integrity check passed",
    "INTEGRITY_FAIL":"File integrity check failed",
}


class TransferLogger:
    def __init__(self, log_dir: str = "logs", label: str = ""):
        os.makedirs(log_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        suffix = f"_{label}" if label else ""
        self.path = os.path.join(log_dir, f"transfer{suffix}_{ts}.csv")
        self._file = open(self.path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(["timestamp", "event", "seq_num", "detail"])
        self._file.flush()
        self.start_time = time.perf_counter()
        # Summary counters
        self.sent = 0
        self.acks_recv = 0
        self.timeouts = 0
        self.retransmits = 0
        self.drops_sim = 0
        self.duplicates = 0
        self._send_times: dict[int, float] = {}  # seq -> send time for RTT
        self._rtt_samples: list[float] = []

    def log(self, event: str, seq_num: int = -1, detail: str = ""):
        now = time.perf_counter()
        self._writer.writerow([f"{now:.6f}", event, seq_num, detail])
        self._file.flush()

        if event == "SEND":
            self.sent += 1
            self._send_times[seq_num] = now
        elif event == "ACK_RECV":
            self.acks_recv += 1
            if seq_num in self._send_times:
                rtt = now - self._send_times.pop(seq_num)
                self._rtt_samples.append(rtt)
        elif event == "TIMEOUT":
            self.timeouts += 1
        elif event == "RETRANSMIT":
            self.retransmits += 1
        elif event == "DROP_SIM":
            self.drops_sim += 1
        elif event == "DUPLICATE":
            self.duplicates += 1

    def close(self):
        self._file.close()

    def summary(self) -> dict:
        elapsed = time.perf_counter() - self.start_time
        avg_rtt = (sum(self._rtt_samples) / len(self._rtt_samples)
                   if self._rtt_samples else 0.0)
        return {
            "sent": self.sent,
            "acks_recv": self.acks_recv,
            "timeouts": self.timeouts,
            "retransmits": self.retransmits,
            "drops_sim": self.drops_sim,
            "duplicates": self.duplicates,
            "elapsed_sec": elapsed,
            "avg_rtt_sec": avg_rtt,
            "log_path": self.path,
        }
