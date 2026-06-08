"""
NetProbe UDP Client — Go-Back-N Sliding Window (bonus feature).

Sends up to WINDOW_SIZE packets without waiting for individual ACKs.
On timeout the entire window is retransmitted from the oldest unACKed packet.
Cumulative ACKs are used: ACK(n) confirms all packets up to and including n.

Usage:
    python src/sliding_window.py --file path/to/file [--host 127.0.0.1] [--port 5001]
                                 [--packet-size 1024] [--timeout 1.0] [--max-retries 5]
                                 [--window-size 4] [--log-dir logs] [--label "gbn"]
"""

import argparse
import hashlib
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(__file__))
from protocol import (
    DataPacket, AckPacket, parse_packet,
    PKT_DATA, PKT_ACK, PKT_FIN, PKT_FIN_ACK,
)
from logger import TransferLogger


def split_file(path: str, chunk_size: int) -> tuple[list[bytes], str]:
    with open(path, "rb") as f:
        data = f.read()
    sha256 = hashlib.sha256(data).hexdigest()
    chunks = [data[i: i + chunk_size] for i in range(0, len(data), chunk_size)]
    return chunks, sha256


def send_file_gbn(host: str, port: int, filepath: str,
                  packet_size: int, timeout: float, max_retries: int,
                  window_size: int, log_dir: str, label: str) -> dict:

    chunks, file_hash = split_file(filepath, packet_size)
    total = len(chunks)
    print(f"[GBN CLIENT] File: {filepath}  ({os.path.getsize(filepath)} bytes)")
    print(f"[GBN CLIENT] Chunks: {total}  window={window_size}  "
          f"pkt_size={packet_size}  timeout={timeout}s")
    print(f"[GBN CLIENT] SHA-256: {file_hash[:16]}...")

    logger = TransferLogger(log_dir=log_dir, label=label or "gbn")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)

    base = 0          # oldest unACKed packet index
    next_seq = 0      # next packet to send
    lock = threading.Lock()
    retries: dict[int, int] = {}   # seq -> retry count
    total_bytes_sent = 0           # wire bytes including retransmits
    transfer_ok = True
    start = time.perf_counter()

    def ack_receiver():
        nonlocal base, transfer_ok
        while base < total and transfer_ok:
            try:
                raw, _ = sock.recvfrom(65535)
                pkt = parse_packet(raw)
                if pkt is None or pkt.pkt_type != PKT_ACK:
                    continue
                ack_n = pkt.ack_num
                with lock:
                    if ack_n >= base:
                        logger.log("ACK_RECV", seq_num=ack_n)
                        base = ack_n + 1
            except socket.timeout:
                pass

    ack_thread = threading.Thread(target=ack_receiver, daemon=True)
    ack_thread.start()

    while base < total and transfer_ok:
        with lock:
            while next_seq < total and next_seq < base + window_size:
                chunk = chunks[next_seq]
                pkt = DataPacket(seq_num=next_seq, total_pkts=total, payload=chunk)
                event = "RETRANSMIT" if retries.get(next_seq, 0) > 0 else "SEND"
                logger.log(event, seq_num=next_seq)
                raw_pkt = pkt.to_bytes()
                total_bytes_sent += len(raw_pkt)
                sock.sendto(raw_pkt, (host, port))
                if event == "SEND":
                    print(f"  [SEND] seq={next_seq}/{total - 1}")
                else:
                    print(f"  [RETX] seq={next_seq}")
                retries[next_seq] = retries.get(next_seq, 0) + 1
                next_seq += 1

        time.sleep(timeout)

        with lock:
            if base < total:
                # Check if window base has stalled (timeout on base packet)
                if retries.get(base, 0) >= max_retries:
                    logger.log("TRANSFER_FAIL", seq_num=base,
                               detail=f"max_retries={max_retries} exceeded")
                    print(f"[GBN] FAILED seq={base} after {max_retries} retries. Aborting.")
                    transfer_ok = False
                    break
                # Go-Back-N: retransmit from base
                logger.log("TIMEOUT", seq_num=base,
                           detail=f"window_base={base} next={next_seq}")
                print(f"  [TIMEOUT] window base={base}, rewinding next_seq to {base}")
                next_seq = base

    ack_thread.join(timeout=timeout * 2)

    if transfer_ok:
        fin_pkt = DataPacket(seq_num=0, total_pkts=0,
                             payload=file_hash.encode(), pkt_type=PKT_FIN)
        fin_acked = False
        for _ in range(max_retries):
            sock.sendto(fin_pkt.to_bytes(), (host, port))
            print("[GBN] Sent FIN, waiting for FIN_ACK...")
            try:
                raw, _ = sock.recvfrom(65535)
                resp = parse_packet(raw)
                if resp is not None and resp.pkt_type == PKT_FIN_ACK:
                    fin_acked = True
                    break
            except socket.timeout:
                print("[GBN] FIN timeout, retrying...")
        if not fin_acked:
            print("[GBN] WARNING: FIN_ACK not received.")

    elapsed = time.perf_counter() - start
    file_size = os.path.getsize(filepath)
    logger.log("TRANSFER_DONE", detail=f"elapsed={elapsed:.3f}s ok={transfer_ok}")
    summary = logger.summary()
    summary["file_size_bytes"] = file_size
    summary["packet_size"] = packet_size
    summary["window_size"] = window_size
    summary["transfer_ok"] = transfer_ok
    sent_total = summary["sent"] + summary["retransmits"]
    summary["retransmit_rate"] = summary["retransmits"] / sent_total if sent_total else 0.0

    if elapsed > 0:
        summary["throughput_bps"] = total_bytes_sent * 8 / elapsed
        summary["goodput_bps"]    = file_size * 8 / elapsed
    else:
        summary["throughput_bps"] = summary["goodput_bps"] = 0

    logger.close()
    sock.close()

    print("\n[GBN] ===== Transfer Summary =====")
    print(f"  Status       : {'SUCCESS' if transfer_ok else 'FAILED'}")
    print(f"  File size    : {file_size} bytes")
    print(f"  Elapsed time : {elapsed:.3f} s")
    print(f"  Throughput   : {summary['throughput_bps'] / 1000:.1f} kbps")
    print(f"  Goodput      : {summary['goodput_bps'] / 1000:.1f} kbps")
    print(f"  Sent packets : {summary['sent']}")
    print(f"  Retransmits  : {summary['retransmits']}")
    print(f"  Retransmit rate: {summary['retransmit_rate']:.2%}")
    print(f"  Avg RTT      : {summary['avg_rtt_sec'] * 1000:.2f} ms")
    print(f"  Log saved to : {summary['log_path']}")
    print("==================================\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description="NetProbe Go-Back-N Sliding Window Client")
    parser.add_argument("--file",        type=str,   required=True)
    parser.add_argument("--host",        type=str,   default="127.0.0.1")
    parser.add_argument("--port",        type=int,   default=5001)
    parser.add_argument("--packet-size", type=int,   default=1024)
    parser.add_argument("--timeout",     type=float, default=1.0)
    parser.add_argument("--max-retries", type=int,   default=5)
    parser.add_argument("--window-size", type=int,   default=4)
    parser.add_argument("--log-dir",     type=str,   default="logs")
    parser.add_argument("--label",       type=str,   default="gbn")
    args = parser.parse_args()

    send_file_gbn(
        host=args.host, port=args.port, filepath=args.file,
        packet_size=args.packet_size, timeout=args.timeout,
        max_retries=args.max_retries, window_size=args.window_size,
        log_dir=args.log_dir, label=args.label,
    )


if __name__ == "__main__":
    main()
