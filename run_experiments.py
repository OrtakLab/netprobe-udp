"""
NetProbe Experiment Runner

Automates all 4 required experiment scenarios and generates comparison charts.
Run from the netprobe/ directory after starting the server in a separate terminal.

Usage:
    # Terminal 1 — start server (no loss for scenarios 1, 2, 4):
    python src/server.py --port 5001

    # Terminal 2 — run all experiments:
    python run_experiments.py --port 5001 --log-dir logs --results-dir results
"""

import argparse
import os
import subprocess
import sys
import time


def run_client(args_extra: list[str], python: str = sys.executable) -> None:
    cmd = [python, "src/client.py"] + args_extra
    print(f"\n$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    time.sleep(0.5)   # let server reset


def run_analyzer(args_extra: list[str], python: str = sys.executable) -> None:
    cmd = [python, "src/analyzer.py"] + args_extra
    print(f"\n$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def make_test_file(path: str, size_bytes: int) -> None:
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "wb") as f:
        # Repeating pattern so SHA-256 is deterministic
        pattern = bytes(range(256))
        written = 0
        while written < size_bytes:
            chunk = pattern[: min(256, size_bytes - written)]
            f.write(chunk)
            written += len(chunk)
    print(f"[PREP] Created test file: {path}  ({size_bytes} bytes)")


def find_latest_logs(log_dir: str, label: str, count: int) -> list[str]:
    """Return the `count` most-recently-modified log files matching label."""
    files = [
        os.path.join(log_dir, f)
        for f in os.listdir(log_dir)
        if f.startswith(f"transfer_{label}") and f.endswith(".csv")
    ]
    files.sort(key=os.path.getmtime, reverse=True)
    return files[:count]


def main():
    parser = argparse.ArgumentParser(description="NetProbe Experiment Runner")
    parser.add_argument("--host",        type=str, default="127.0.0.1")
    parser.add_argument("--port",        type=int, default=5001)
    parser.add_argument("--log-dir",     type=str, default="logs")
    parser.add_argument("--results-dir", type=str, default="results")
    args = parser.parse_args()

    os.makedirs(args.log_dir, exist_ok=True)
    os.makedirs(args.results_dir, exist_ok=True)

    HOST = args.host
    PORT = str(args.port)
    LOSS_PORT = str(args.port + 1)
    LOG  = args.log_dir
    RES  = args.results_dir

    # ------------------------------------------------------------------ #
    # Prepare test files
    # ------------------------------------------------------------------ #
    make_test_file("test_files/file_1KB.bin",   1 * 1024)
    make_test_file("test_files/file_100KB.bin", 100 * 1024)
    make_test_file("test_files/file_1MB.bin",   1 * 1024 * 1024)
    make_test_file("test_files/file_10MB.bin",  10 * 1024 * 1024)

    # ================================================================== #
    # Scenario 1: Packet size effect (file = 1 MB, no loss)
    # ================================================================== #
    print("\n" + "=" * 60)
    print("SCENARIO 1: Packet Size Effect")
    print("=" * 60)
    FILE1 = "test_files/file_1MB.bin"
    PKT_SIZES = [512, 1024, 4096, 8192]
    for ps in PKT_SIZES:
        lbl = f"s1_pkt{ps}"
        run_client([
            "--file", FILE1, "--host", HOST, "--port", PORT,
            "--packet-size", str(ps), "--timeout", "1.0",
            "--log-dir", LOG, "--label", lbl,
        ])

    # Collect logs and generate chart
    logs1 = [find_latest_logs(LOG, f"s1_pkt{ps}", 1)[0] for ps in PKT_SIZES]
    labels1 = [f"{ps}B" for ps in PKT_SIZES]
    for metric in ("throughput_kbps", "goodput_kbps", "completion_sec"):
        run_analyzer([
            "--compare", "--logs", *logs1, "--labels", *labels1,
            "--file-size", str(1 * 1024 * 1024),
            "--metric", metric,
            "--title", f"Senaryo 1: Paket Boyutu — {metric}",
            "--output", os.path.join(RES, f"s1_{metric}.png"),
        ])

    # ================================================================== #
    # Scenario 2: Timeout effect (file = 100 KB, no loss)
    # ================================================================== #
    print("\n" + "=" * 60)
    print("SCENARIO 2: Timeout Value Effect")
    print("=" * 60)
    FILE2 = "test_files/file_100KB.bin"
    TIMEOUTS = [0.1, 0.5, 1.0, 2.0]
    for to in TIMEOUTS:
        lbl = f"s2_to{int(to * 1000)}ms"
        run_client([
            "--file", FILE2, "--host", HOST, "--port", PORT,
            "--packet-size", "1024", "--timeout", str(to),
            "--log-dir", LOG, "--label", lbl,
        ])

    logs2 = [find_latest_logs(LOG, f"s2_to{int(to * 1000)}ms", 1)[0]
             for to in TIMEOUTS]
    labels2 = [f"{int(to * 1000)}ms" for to in TIMEOUTS]
    for metric in ("completion_sec", "retransmit_rate_pct", "avg_rtt_ms"):
        run_analyzer([
            "--compare", "--logs", *logs2, "--labels", *labels2,
            "--file-size", str(100 * 1024),
            "--metric", metric,
            "--title", f"Senaryo 2: Timeout Değeri — {metric}",
            "--output", os.path.join(RES, f"s2_{metric}.png"),
        ])

    # ================================================================== #
    # Scenario 3: Packet loss rate effect — server spawned per loss rate
    # ================================================================== #
    print("\n" + "=" * 60)
    print("SCENARIO 3: Loss Rate Effect")
    print("=" * 60)
    FILE3 = "test_files/file_100KB.bin"
    LOSS_RATES_PCT = [0, 5, 10, 20]
    logs3 = []
    labels3 = []

    for lr_pct in LOSS_RATES_PCT:
        lr = lr_pct / 100.0
        lbl = f"s3_loss{lr_pct}"
        srv = subprocess.Popen(
            [sys.executable, "src/server.py",
             "--port", LOSS_PORT, "--loss-rate", str(lr),
             "--log-dir", LOG, "--label", lbl],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(0.5)   # let server bind
        try:
            run_client([
                "--file", FILE3, "--host", HOST, "--port", LOSS_PORT,
                "--packet-size", "1024", "--timeout", "1.0",
                "--log-dir", LOG, "--label", lbl,
            ])
        finally:
            srv.terminate()
            srv.wait()
        time.sleep(0.3)
        found = find_latest_logs(LOG, lbl, 1)
        if found:
            logs3.append(found[0])
            labels3.append(f"{lr_pct}%")

    if len(logs3) >= 2:
        for metric in ("retransmit_rate_pct", "completion_sec", "goodput_kbps"):
            run_analyzer([
                "--compare", "--logs", *logs3, "--labels", *labels3,
                "--file-size", str(100 * 1024),
                "--metric", metric,
                "--title", f"Senaryo 3: Kayip Orani -- {metric}",
                "--output", os.path.join(RES, f"s3_{metric}.png"),
            ])

    # ================================================================== #
    # Scenario 4: File size effect (packet_size=1024, no loss)
    # ================================================================== #
    print("\n" + "=" * 60)
    print("SCENARIO 4: File Size Effect")
    print("=" * 60)
    FILE_CONFIGS = [
        ("test_files/file_1KB.bin",   1 * 1024,        "1KB"),
        ("test_files/file_100KB.bin", 100 * 1024,      "100KB"),
        ("test_files/file_1MB.bin",   1 * 1024 * 1024, "1MB"),
        ("test_files/file_10MB.bin",  10 * 1024 * 1024,"10MB"),
    ]
    logs4 = []
    labels4 = []
    sizes4 = []
    for filepath, fsize, lbl_name in FILE_CONFIGS:
        lbl = f"s4_{lbl_name}"
        run_client([
            "--file", filepath, "--host", HOST, "--port", PORT,
            "--packet-size", "1024", "--timeout", "1.0",
            "--log-dir", LOG, "--label", lbl,
        ])
        found = find_latest_logs(LOG, f"s4_{lbl_name}", 1)
        if found:
            logs4.append(found[0])
            labels4.append(lbl_name)
            sizes4.append(fsize)

    if len(logs4) >= 2:
        for metric in ("throughput_kbps", "goodput_kbps", "completion_sec"):
            run_analyzer([
                "--compare", "--logs", *logs4, "--labels", *labels4,
                "--file-size", str(max(sizes4)), "--file-sizes", *map(str, sizes4),
                "--metric", metric,
                "--title", f"Senaryo 4: Dosya Boyutu — {metric}",
                "--output", os.path.join(RES, f"s4_{metric}.png"),
            ])

    print("\n" + "=" * 60)
    print(f"All experiments done. Charts saved to: {RES}/")
    print("=" * 60)


if __name__ == "__main__":
    main()
