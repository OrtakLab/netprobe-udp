"""
NetProbe Web UI — Flask backend.

Run:  python web_app.py
Then open http://localhost:8080 in your browser.
"""

import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory

BASE_DIR = Path(__file__).parent
SRC_DIR  = BASE_DIR / "src"
LOG_DIR  = BASE_DIR / "logs"
RES_DIR  = BASE_DIR / "results"
UPL_DIR  = BASE_DIR / "uploads"

for d in (LOG_DIR, RES_DIR, UPL_DIR):
    d.mkdir(exist_ok=True)

app = Flask(__name__, static_folder=str(BASE_DIR / "static"))

# ------------------------------------------------------------------ #
# Shared state
# ------------------------------------------------------------------ #
state: dict = {
    "server_proc":      None,     # subprocess.Popen
    "server_running":   False,
    "server_log":       deque(maxlen=300),
    "transfer_running": False,
    "transfer_log":     deque(maxlen=300),
    "last_summary":     {},
    "last_log_path":    None,
}
state_lock = threading.Lock()


def _read_proc_output(proc: subprocess.Popen, target_deque: deque):
    """Background thread: read lines from process stdout into a deque."""
    try:
        for line in iter(proc.stdout.readline, b""):
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                with state_lock:
                    target_deque.append({"t": time.time(), "msg": text})
    except Exception:
        pass


# ------------------------------------------------------------------ #
# Routes — static
# ------------------------------------------------------------------ #

@app.route("/")
def index():
    return send_from_directory(str(BASE_DIR / "static"), "index.html")


@app.route("/api/results/<path:filename>")
def serve_result(filename):
    return send_from_directory(str(RES_DIR), filename)


# ------------------------------------------------------------------ #
# Routes — server control
# ------------------------------------------------------------------ #

@app.route("/api/server/start", methods=["POST"])
def server_start():
    with state_lock:
        if state["server_running"]:
            return jsonify({"ok": False, "error": "Server already running"}), 400

    data = request.get_json(silent=True) or {}
    loss_rate = float(data.get("loss_rate", 0.0))
    delay     = float(data.get("delay", 0.0))

    cmd = [
        sys.executable, str(SRC_DIR / "server.py"),
        "--port", "5001",
        "--output-dir", str(BASE_DIR / "received"),
        "--loss-rate", str(loss_rate),
        "--delay",     str(delay),
        "--log-dir",   str(LOG_DIR),
        "--label",     "srv",
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(BASE_DIR),
    )
    with state_lock:
        state["server_proc"]    = proc
        state["server_running"] = True
        state["server_log"].clear()

    threading.Thread(
        target=_read_proc_output,
        args=(proc, state["server_log"]),
        daemon=True,
    ).start()

    return jsonify({"ok": True})


@app.route("/api/server/stop", methods=["POST"])
def server_stop():
    with state_lock:
        proc = state["server_proc"]
        if not proc:
            return jsonify({"ok": False, "error": "Not running"}), 400
        proc.terminate()
        state["server_proc"]    = None
        state["server_running"] = False

    return jsonify({"ok": True})


# ------------------------------------------------------------------ #
# Routes — file transfer
# ------------------------------------------------------------------ #

@app.route("/api/transfer", methods=["POST"])
def transfer():
    with state_lock:
        if state["transfer_running"]:
            return jsonify({"ok": False, "error": "Transfer already in progress"}), 400

    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400

    f = request.files["file"]
    save_path = UPL_DIR / f.filename
    f.save(str(save_path))

    packet_size = int(request.form.get("packet_size", 1024))
    timeout     = float(request.form.get("timeout", 1.0))
    max_retries = int(request.form.get("max_retries", 5))
    use_gbn     = request.form.get("use_gbn", "false").lower() == "true"
    window_size = int(request.form.get("window_size", 4))

    script = "sliding_window.py" if use_gbn else "client.py"
    cmd = [
        sys.executable, str(SRC_DIR / script),
        "--file",        str(save_path),
        "--host",        "127.0.0.1",
        "--port",        "5001",
        "--packet-size", str(packet_size),
        "--timeout",     str(timeout),
        "--max-retries", str(max_retries),
        "--log-dir",     str(LOG_DIR),
        "--label",       "cli",
    ]
    if use_gbn:
        cmd += ["--window-size", str(window_size)]

    with state_lock:
        state["transfer_running"] = True
        state["transfer_log"].clear()
        state["last_summary"] = {}

    def run_transfer():
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(BASE_DIR),
        )
        lines = []
        for raw in iter(proc.stdout.readline, b""):
            text = raw.decode("utf-8", errors="replace").rstrip()
            if text:
                lines.append(text)
                with state_lock:
                    state["transfer_log"].append({"t": time.time(), "msg": text})
        proc.wait()

        # Parse summary from output
        summary = _parse_summary(lines)
        # Find latest client log
        log_path = _latest_log("cli")
        with state_lock:
            state["transfer_running"] = False
            state["last_summary"] = summary
            state["last_log_path"] = log_path

    threading.Thread(target=run_transfer, daemon=True).start()
    return jsonify({"ok": True})


def _parse_summary(lines: list[str]) -> dict:
    summary = {}
    for line in lines:
        line = line.strip()
        if "Throughput" in line and "kbps" in line:
            try:
                summary["throughput_kbps"] = float(line.split(":")[1].strip().split()[0])
            except Exception:
                pass
        elif "Goodput" in line and "kbps" in line:
            try:
                summary["goodput_kbps"] = float(line.split(":")[1].strip().split()[0])
            except Exception:
                pass
        elif "Elapsed time" in line:
            try:
                summary["elapsed_sec"] = float(line.split(":")[1].strip().split()[0])
            except Exception:
                pass
        elif "Retransmit rate" in line:
            try:
                val = line.split(":")[1].strip().rstrip("%")
                summary["retransmit_rate_pct"] = float(val)
            except Exception:
                pass
        elif "Avg RTT" in line:
            try:
                summary["avg_rtt_ms"] = float(line.split(":")[1].strip().split()[0])
            except Exception:
                pass
        elif "Sent packets" in line:
            try:
                summary["sent_packets"] = int(line.split(":")[1].strip())
            except Exception:
                pass
        elif "Retransmits" in line and "rate" not in line.lower():
            try:
                summary["retransmits"] = int(line.split(":")[1].strip())
            except Exception:
                pass
        elif "File size" in line:
            try:
                summary["file_size_bytes"] = int(line.split(":")[1].strip().split()[0])
            except Exception:
                pass
    return summary


def _latest_log(label: str) -> str | None:
    files = sorted(
        LOG_DIR.glob(f"transfer_{label}_*.csv"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return str(files[0]) if files else None


# ------------------------------------------------------------------ #
# Routes — status & analyze
# ------------------------------------------------------------------ #

@app.route("/api/status")
def status():
    with state_lock:
        srv_log  = list(state["server_log"])
        xfr_log  = list(state["transfer_log"])
        summary  = dict(state["last_summary"])
        running  = state["server_running"]
        xfr_run  = state["transfer_running"]

    return jsonify({
        "server_running":   running,
        "transfer_running": xfr_run,
        "server_log":       srv_log[-50:],
        "transfer_log":     xfr_log[-100:],
        "summary":          summary,
    })


@app.route("/api/analyze", methods=["POST"])
def analyze():
    with state_lock:
        log_path = state["last_log_path"]
        summary  = dict(state["last_summary"])

    if not log_path or not os.path.exists(log_path):
        return jsonify({"ok": False, "error": "No transfer log found. Run a transfer first."}), 400

    file_size = summary.get("file_size_bytes", 102400)
    out_png   = str(RES_DIR / "latest_metrics.png")

    cmd = [
        sys.executable, str(SRC_DIR / "analyzer.py"),
        "--log",       log_path,
        "--file-size", str(file_size),
        "--output",    out_png,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(BASE_DIR))
    if result.returncode != 0:
        return jsonify({"ok": False, "error": result.stderr}), 500

    return jsonify({"ok": True, "image": "/api/results/latest_metrics.png"})


@app.route("/api/results")
def results_list():
    files = [f.name for f in sorted(RES_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)]
    return jsonify(files)


# ------------------------------------------------------------------ #
# Main
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    port = 8080
    url  = f"http://localhost:{port}"
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"\n  NetProbe Web UI: {url}\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
