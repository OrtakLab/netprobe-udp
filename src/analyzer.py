"""
NetProbe Performance Analyzer

Reads one or more transfer CSV logs and computes:
  - Throughput, Goodput (bps)
  - Packet loss rate, Retransmission rate
  - Average RTT
  - Completion time

Also generates comparison charts for experiment scenarios.

Usage:
    # Analyze a single log
    python src/analyzer.py --log logs/transfer_client_xxx.csv \
                           --file-size 102400 --output results/

    # Compare multiple logs (e.g. different packet sizes)
    python src/analyzer.py --compare \
        --logs logs/pkt512.csv logs/pkt1024.csv logs/pkt4096.csv \
        --labels "512B" "1024B" "4096B" \
        --file-size 102400 \
        --metric throughput_kbps \
        --title "Packet Size vs Throughput" \
        --output results/scenario1_throughput.png
"""

import argparse
import csv
import os

import matplotlib
matplotlib.use("Agg")   # headless rendering
import matplotlib.pyplot as plt

DATA_HEADER_SIZE = 15


def parse_log(path: str) -> dict:
    """Return per-event counts and timing from a CSV log."""
    events = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            events.append(row)

    counts = {
        "SEND": 0, "ACK_RECV": 0, "TIMEOUT": 0,
        "RETRANSMIT": 0, "DROP_SIM": 0, "DUPLICATE": 0,
    }
    send_times: dict[int, float] = {}
    transmitted_seqs: list[int] = []
    rtt_samples: list[float] = []
    first_ts = None
    last_ts = None

    for e in events:
        ev = e["event"]
        ts = float(e["timestamp"])
        seq = int(e["seq_num"]) if e["seq_num"] not in ("", "-1") else -1

        if first_ts is None:
            first_ts = ts
        last_ts = ts

        if ev in counts:
            counts[ev] += 1
        if ev in ("SEND", "RETRANSMIT") and seq >= 0:
            transmitted_seqs.append(seq)

        if ev == "SEND" and seq >= 0:
            send_times[seq] = ts
        elif ev == "ACK_RECV" and seq >= 0 and seq in send_times:
            rtt_samples.append(ts - send_times.pop(seq))

    elapsed = (last_ts - first_ts) if (first_ts and last_ts) else 0.0
    avg_rtt = sum(rtt_samples) / len(rtt_samples) if rtt_samples else 0.0

    return {
        **counts,
        "elapsed_sec": elapsed,
        "avg_rtt_sec": avg_rtt,
        "rtt_samples": rtt_samples,
        "transmitted_seqs": transmitted_seqs,
    }


def compute_metrics(log_data: dict, file_size_bytes: int,
                    packet_size: int | None = None) -> dict:
    sent = log_data["SEND"] + log_data["RETRANSMIT"]
    retx = log_data["RETRANSMIT"]
    elapsed = log_data["elapsed_sec"]

    # UDP data packet bytes pushed over the wire (payload + NetProbe header)
    if packet_size:
        pkt_bytes = sum(
            DATA_HEADER_SIZE + max(0, min(packet_size, file_size_bytes - seq * packet_size))
            for seq in log_data.get("transmitted_seqs", [])
        )
        if not pkt_bytes and sent:
            pkt_bytes = (packet_size + DATA_HEADER_SIZE) * sent
    else:
        pkt_bytes = file_size_bytes
    throughput_bps = (pkt_bytes * 8 / elapsed) if elapsed else 0.0
    goodput_bps    = (file_size_bytes * 8 / elapsed) if elapsed else 0.0

    total_sent_pkts = log_data["SEND"]
    loss_rate = (log_data["DROP_SIM"] / (total_sent_pkts + log_data["DROP_SIM"])
                 if (total_sent_pkts + log_data["DROP_SIM"]) else 0.0)
    retx_rate = retx / sent if sent else 0.0

    return {
        "throughput_kbps":  throughput_bps / 1000,
        "goodput_kbps":     goodput_bps / 1000,
        "loss_rate_pct":    loss_rate * 100,
        "retransmit_rate_pct": retx_rate * 100,
        "avg_rtt_ms":       log_data["avg_rtt_sec"] * 1000,
        "completion_sec":   elapsed,
        "retransmits":      retx,
        "timeouts":         log_data["TIMEOUT"],
        "sent_total":       sent,
    }


def print_metrics(label: str, metrics: dict):
    print(f"\n=== {label} ===")
    for k, v in metrics.items():
        print(f"  {k:28s}: {v:.4f}")


def bar_chart(labels: list, values: list, title: str,
              ylabel: str, out_path: str):
    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(labels, values, color="#2196F3", edgecolor="black", width=0.5)
    ax.bar_label(bars, fmt="%.2f", padding=4, fontsize=9)
    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.set_ylabel(ylabel)
    ax.set_xlabel("")
    ax.grid(axis="y", linestyle="--", alpha=0.6)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"  Chart saved: {out_path}")


def multi_metric_chart(labels: list, metric_sets: list[dict],
                       metrics_to_plot: list[tuple[str, str]],
                       title: str, out_path: str):
    """Bar chart with multiple metric groups side by side."""
    import numpy as np
    n_labels = len(labels)
    n_metrics = len(metrics_to_plot)
    x = np.arange(n_labels)
    width = 0.8 / n_metrics

    fig, ax = plt.subplots(figsize=(10, 5))
    colors = ["#2196F3", "#FF5722", "#4CAF50", "#9C27B0"]
    for i, (metric_key, metric_label) in enumerate(metrics_to_plot):
        vals = [ms[metric_key] for ms in metric_sets]
        offset = (i - n_metrics / 2 + 0.5) * width
        bars = ax.bar(x + offset, vals, width, label=metric_label,
                      color=colors[i % len(colors)], edgecolor="black")
        ax.bar_label(bars, fmt="%.1f", padding=3, fontsize=8)

    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.legend()
    ax.grid(axis="y", linestyle="--", alpha=0.6)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"  Chart saved: {out_path}")


METRIC_META = {
    "throughput_kbps":     ("Throughput (kbps)",        "Throughput"),
    "goodput_kbps":        ("Goodput (kbps)",            "Goodput"),
    "completion_sec":      ("Completion time (s)",       "Completion Time"),
    "retransmit_rate_pct": ("Retransmission rate (%)",   "Retransmit Rate"),
    "loss_rate_pct":       ("Packet loss rate (%)",      "Loss Rate"),
    "avg_rtt_ms":          ("Average RTT (ms)",          "Avg RTT"),
}


def main():
    parser = argparse.ArgumentParser(description="NetProbe Analyzer")
    parser.add_argument("--log",       type=str, help="Single log CSV to analyze")
    parser.add_argument("--logs",      nargs="+", help="Multiple log CSVs (compare mode)")
    parser.add_argument("--labels",    nargs="+", help="Labels for each log in compare mode")
    parser.add_argument("--file-size", type=int, required=True,
                        help="Original file size in bytes")
    parser.add_argument("--file-sizes", nargs="+", type=int,
                        help="Per-log original file sizes for compare mode")
    parser.add_argument("--packet-size", type=int, default=None)
    parser.add_argument("--packet-sizes", nargs="+", type=int,
                        help="Per-log packet sizes for compare mode")
    parser.add_argument("--metric",    type=str, default="throughput_kbps",
                        choices=list(METRIC_META.keys()))
    parser.add_argument("--title",     type=str, default="")
    parser.add_argument("--output",    type=str, default="results",
                        help="Output directory or .png file path")
    parser.add_argument("--compare",   action="store_true")
    args = parser.parse_args()

    os.makedirs(args.output if os.path.isdir(args.output) or not args.output.endswith(".png")
                else os.path.dirname(args.output) or ".", exist_ok=True)

    if args.compare and args.logs:
        labels = args.labels or [os.path.basename(p) for p in args.logs]
        if args.file_sizes and len(args.file_sizes) != len(args.logs):
            parser.error("--file-sizes must have the same number of values as --logs")
        if args.packet_sizes and len(args.packet_sizes) != len(args.logs):
            parser.error("--packet-sizes must have the same number of values as --logs")
        all_metrics = []
        file_sizes = args.file_sizes or [args.file_size] * len(args.logs)
        for i, (path, lbl, fsize) in enumerate(zip(args.logs, labels, file_sizes)):
            log_data = parse_log(path)
            psize = args.packet_sizes[i] if args.packet_sizes else args.packet_size
            m = compute_metrics(log_data, fsize, psize)
            print_metrics(lbl, m)
            all_metrics.append(m)

        ylabel, chart_title = METRIC_META.get(args.metric, (args.metric, args.metric))
        title = args.title or chart_title
        values = [m[args.metric] for m in all_metrics]

        if args.output.endswith(".png"):
            out_path = args.output
        else:
            out_path = os.path.join(args.output, f"{args.metric}_comparison.png")

        bar_chart(labels, values, title=title, ylabel=ylabel, out_path=out_path)

    elif args.log:
        log_data = parse_log(args.log)
        m = compute_metrics(log_data, args.file_size, args.packet_size)
        print_metrics(os.path.basename(args.log), m)

        if args.output.endswith(".png"):
            out_path = args.output
        else:
            os.makedirs(args.output, exist_ok=True)
            base = os.path.splitext(os.path.basename(args.log))[0]
            out_path = os.path.join(args.output, f"{base}_metrics.png")

        # Multi-metric overview bar chart
        metrics_to_show = [
            ("throughput_kbps",     "Throughput (kbps)"),
            ("goodput_kbps",        "Goodput (kbps)"),
        ]
        multi_metric_chart(
            labels=["Transfer"],
            metric_sets=[m],
            metrics_to_plot=metrics_to_show,
            title=args.title or "Transfer Metrics",
            out_path=out_path,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
