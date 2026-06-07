"""
NetProbe UDP Server

Usage:
    python src/server.py [--port 5001] [--output-dir received]
                         [--loss-rate 0.0] [--delay 0]
                         [--log-dir logs] [--label ""]
"""

import argparse
import hashlib
import os
import random
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from protocol import (
    DataPacket, AckPacket, parse_packet,
    PKT_DATA, PKT_FIN, PKT_ACK, PKT_FIN_ACK,
    DATA_HEADER_SIZE,
)
from logger import TransferLogger

MAX_UDP = 65535


def run_server(port: int, output_dir: str, loss_rate: float,
               delay_ms: float, log_dir: str, label: str):
    os.makedirs(output_dir, exist_ok=True)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", port))
    print(f"[SERVER] Listening on port {port}  (loss_rate={loss_rate:.2f}, delay={delay_ms}ms)")

    while True:
        logger = TransferLogger(log_dir=log_dir, label=label or "server")
        chunks: dict[int, bytes] = {}
        total_pkts = None
        client_addr = None
        filename = "received_file"

        print("[SERVER] Waiting for transfer...")

        while True:
            try:
                raw, addr = sock.recvfrom(MAX_UDP)
            except KeyboardInterrupt:
                print("\n[SERVER] Stopped.")
                logger.close()
                sock.close()
                return

            # Network simulation: artificial loss
            if loss_rate > 0 and random.random() < loss_rate:
                logger.log("DROP_SIM", detail=f"from {addr}")
                print(f"  [SIM] Dropped packet from {addr}")
                continue

            # Artificial delay
            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)

            pkt = parse_packet(raw)
            if pkt is None:
                print("  [WARN] Corrupt/unknown packet, ignoring.")
                continue

            client_addr = addr

            # ---- DATA packet ----
            if pkt.pkt_type == PKT_DATA:
                seq = pkt.seq_num
                if total_pkts is None:
                    total_pkts = pkt.total_pkts

                if seq in chunks:
                    logger.log("DUPLICATE", seq_num=seq)
                    print(f"  [RECV] Duplicate seq={seq}, resending ACK")
                else:
                    chunks[seq] = pkt.payload
                    logger.log("RECV", seq_num=seq,
                               detail=f"payload_len={len(pkt.payload)}")
                    print(f"  [RECV] seq={seq}/{total_pkts - 1}  "
                          f"({len(chunks)}/{total_pkts})")

                ack = AckPacket(ack_num=seq)
                sock.sendto(ack.to_bytes(), addr)

            # ---- FIN packet ----
            elif pkt.pkt_type == PKT_FIN:
                received_hash = pkt.payload.decode(errors="ignore").strip()
                print(f"[SERVER] FIN received. Reassembling file...")

                if total_pkts is not None and len(chunks) == total_pkts:
                    file_data = b"".join(chunks[i] for i in range(total_pkts))
                    computed_hash = hashlib.sha256(file_data).hexdigest()

                    if computed_hash == received_hash:
                        logger.log("INTEGRITY_OK",
                                   detail=f"sha256={computed_hash[:16]}...")
                        print(f"[SERVER] Integrity OK  sha256={computed_hash[:16]}...")
                    else:
                        logger.log("INTEGRITY_FAIL",
                                   detail=f"expected={received_hash[:16]} got={computed_hash[:16]}")
                        print("[SERVER] Integrity FAILED!")

                    out_path = os.path.join(output_dir, filename)
                    with open(out_path, "wb") as f:
                        f.write(file_data)
                    print(f"[SERVER] File saved to {out_path}  ({len(file_data)} bytes)")
                else:
                    missing = (total_pkts or 0) - len(chunks)
                    print(f"[SERVER] WARNING: {missing} packets missing, saving partial file.")
                    file_data = b"".join(
                        chunks.get(i, b"") for i in range(total_pkts or len(chunks))
                    )
                    out_path = os.path.join(output_dir, filename + ".partial")
                    with open(out_path, "wb") as f:
                        f.write(file_data)

                logger.log("TRANSFER_DONE", detail=f"pkts={len(chunks)}")
                summary = logger.summary()
                print(f"[SERVER] Summary: {summary}")
                logger.close()

                fin_ack = AckPacket(ack_num=0, pkt_type=PKT_FIN_ACK)
                sock.sendto(fin_ack.to_bytes(), addr)
                break   # ready for next transfer


def main():
    parser = argparse.ArgumentParser(description="NetProbe UDP Server")
    parser.add_argument("--port",       type=int,   default=5001)
    parser.add_argument("--output-dir", type=str,   default="received")
    parser.add_argument("--loss-rate",  type=float, default=0.0,
                        help="Simulated packet loss probability [0, 1)")
    parser.add_argument("--delay",      type=float, default=0.0,
                        help="Artificial delay per packet in milliseconds")
    parser.add_argument("--log-dir",    type=str,   default="logs")
    parser.add_argument("--label",      type=str,   default="",
                        help="Label appended to log file name")
    args = parser.parse_args()

    run_server(
        port=args.port,
        output_dir=args.output_dir,
        loss_rate=args.loss_rate,
        delay_ms=args.delay,
        log_dir=args.log_dir,
        label=args.label,
    )


if __name__ == "__main__":
    main()
