"""
NetProbe UDP Client — Stop-and-Wait reliable file transfer.

Usage:
    python src/client.py --file path/to/file [--host 127.0.0.1] [--port 5001]
                         [--packet-size 1024] [--timeout 1.0] [--max-retries 5]
                         [--log-dir logs] [--label ""]
"""

import argparse
import hashlib
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from protocol import (
    DataPacket, AckPacket, parse_packet,
    PKT_DATA, PKT_ACK, PKT_FIN, PKT_FIN_ACK,
    DATA_HEADER_SIZE,
)
from logger import TransferLogger

MAX_UDP = 65535


def split_file(path: str, chunk_size: int) -> tuple[list[bytes], str]:
    with open(path, "rb") as f:
        data = f.read()
    sha256 = hashlib.sha256(data).hexdigest()
    chunks = [data[i: i + chunk_size] for i in range(0, len(data), chunk_size)]
    return chunks, sha256


def send_file(host: str, port: int, filepath: str,
              packet_size: int, timeout: float, max_retries: int,
              log_dir: str, label: str) -> dict:

    chunks, file_hash = split_file(filepath, packet_size)
    total = len(chunks)
    print(f"[CLIENT] File: {filepath}  ({os.path.getsize(filepath)} bytes)")
    print(f"[CLIENT] Chunks: {total}  packet_size={packet_size}  "
          f"timeout={timeout}s  max_retries={max_retries}")
    print(f"[CLIENT] SHA-256: {file_hash[:16]}...")

    logger = TransferLogger(log_dir=log_dir, label=label or "client")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)

    transfer_ok = True
    start = time.perf_counter()

    for seq, chunk in enumerate(chunks):
        pkt = DataPacket(seq_num=seq, total_pkts=total, payload=chunk)
        raw = pkt.to_bytes()
        attempts = 0
        acked = False

        while not acked:
            if attempts > max_retries:
                logger.log("TRANSFER_FAIL", seq_num=seq,
                           detail=f"max_retries={max_retries} exceeded")
                print(f"[CLIENT] FAILED seq={seq} after {max_retries} retries. Aborting.")
                transfer_ok = False
                break

            event = "RETRANSMIT" if attempts > 0 else "SEND"
            logger.log(event, seq_num=seq, detail=f"attempt={attempts + 1}")
            sock.sendto(raw, (host, port))
            if attempts > 0:
                print(f"  [RETX]  seq={seq}  attempt={attempts + 1}/{max_retries}")
            else:
                print(f"  [SEND]  seq={seq}/{total - 1}")

            try:
                resp_raw, _ = sock.recvfrom(MAX_UDP)
                ack = parse_packet(resp_raw)
                if ack is not None and ack.pkt_type == PKT_ACK and ack.ack_num == seq:
                    logger.log("ACK_RECV", seq_num=seq)
                    acked = True
                else:
                    attempts += 1
                    logger.log("TIMEOUT", seq_num=seq, detail="unexpected response")
            except socket.timeout:
                attempts += 1
                logger.log("TIMEOUT", seq_num=seq, detail=f"attempt={attempts}")
                print(f"  [TIMEOUT] seq={seq}  attempt={attempts}")

        if not transfer_ok:
            break

    if transfer_ok:
        # Send FIN with file hash payload
        fin_pkt = DataPacket(seq_num=0, total_pkts=0,
                             payload=file_hash.encode(), pkt_type=PKT_FIN)
        fin_raw = fin_pkt.to_bytes()
        fin_acked = False
        for _ in range(max_retries):
            sock.sendto(fin_raw, (host, port))
            print("[CLIENT] Sent FIN, waiting for FIN_ACK...")
            try:
                resp_raw, _ = sock.recvfrom(MAX_UDP)
                resp = parse_packet(resp_raw)
                if resp is not None and resp.pkt_type == PKT_FIN_ACK:
                    fin_acked = True
                    break
            except socket.timeout:
                print("[CLIENT] FIN timeout, retrying...")

        if not fin_acked:
            print("[CLIENT] WARNING: FIN_ACK not received.")

    elapsed = time.perf_counter() - start
    file_size = os.path.getsize(filepath)
    total_sent_bytes = sum(len(c) for c in chunks)

    logger.log("TRANSFER_DONE", detail=f"elapsed={elapsed:.3f}s ok={transfer_ok}")
    summary = logger.summary()
    summary["file_size_bytes"] = file_size
    summary["total_sent_bytes"] = total_sent_bytes
    summary["packet_size"] = packet_size
    summary["timeout"] = timeout
    summary["max_retries"] = max_retries
    summary["total_pkts"] = total
    summary["transfer_ok"] = transfer_ok

    # Derived metrics
    if elapsed > 0:
        summary["throughput_bps"] = total_sent_bytes * 8 / elapsed
        summary["goodput_bps"]    = file_size * 8 / elapsed
    else:
        summary["throughput_bps"] = 0
        summary["goodput_bps"]    = 0

    if summary["sent"] > 0:
        summary["retransmit_rate"] = summary["retransmits"] / summary["sent"]
    else:
        summary["retransmit_rate"] = 0.0

    logger.close()
    sock.close()

    print("\n[CLIENT] ===== Transfer Summary =====")
    print(f"  File size      : {file_size} bytes")
    print(f"  Elapsed time   : {elapsed:.3f} s")
    print(f"  Throughput     : {summary['throughput_bps'] / 1000:.1f} kbps")
    print(f"  Goodput        : {summary['goodput_bps'] / 1000:.1f} kbps")
    print(f"  Sent packets   : {summary['sent']}")
    print(f"  Retransmits    : {summary['retransmits']}")
    print(f"  Retransmit rate: {summary['retransmit_rate']:.2%}")
    print(f"  Timeouts       : {summary['timeouts']}")
    print(f"  Avg RTT        : {summary['avg_rtt_sec'] * 1000:.2f} ms")
    print(f"  Log saved to   : {summary['log_path']}")
    print("=====================================\n")

    return summary


def main():
    parser = argparse.ArgumentParser(description="NetProbe Stop-and-Wait UDP Client")
    parser.add_argument("--file",        type=str,   required=True)
    parser.add_argument("--host",        type=str,   default="127.0.0.1")
    parser.add_argument("--port",        type=int,   default=5001)
    parser.add_argument("--packet-size", type=int,   default=1024,
                        help="Payload bytes per packet")
    parser.add_argument("--timeout",     type=float, default=1.0,
                        help="ACK timeout in seconds")
    parser.add_argument("--max-retries", type=int,   default=5)
    parser.add_argument("--log-dir",     type=str,   default="logs")
    parser.add_argument("--label",       type=str,   default="",
                        help="Label appended to log file name")
    args = parser.parse_args()

    send_file(
        host=args.host,
        port=args.port,
        filepath=args.file,
        packet_size=args.packet_size,
        timeout=args.timeout,
        max_retries=args.max_retries,
        log_dir=args.log_dir,
        label=args.label,
    )


if __name__ == "__main__":
    main()
