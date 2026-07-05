#!/usr/bin/env python3
"""Dashboard daemon — keeps the GMGN dashboard running reliably."""
from __future__ import annotations

import os
import sys
import time
import signal
import subprocess
from pathlib import Path

PID_FILE = Path("/tmp/gmgn_dashboard.pid")
LOG_FILE = Path("/tmp/gmgn_dashboard.log")
PORT = 8765
PROJECT_ROOT = Path("/Users/henry/projects/gmgn")


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def start() -> None:
    """Start the dashboard daemon."""
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            if _is_running(old_pid):
                print(f"Dashboard already running (PID {old_pid})")
                return
        except (ValueError, OSError):
            pass

    # Fork to background
    pid = os.fork()
    if pid > 0:
        # Parent: wait a moment and check
        time.sleep(2)
        if PID_FILE.exists():
            child_pid = int(PID_FILE.read_text().strip())
            if _is_running(child_pid):
                print(f"Dashboard started (PID {child_pid}) on port {PORT}")
                return
        print("Failed to start dashboard")
        sys.exit(1)

    # Child: become session leader and redirect I/O
    os.setsid()
    os.chdir(PROJECT_ROOT)
    sys.stdout.flush()
    sys.stderr.flush()

    # Redirect stdout/stderr to log file
    with open(LOG_FILE, "a") as log:
        os.dup2(log.fileno(), sys.stdout.fileno())
        os.dup2(log.fileno(), sys.stderr.fileno())

    # Write PID file
    PID_FILE.write_text(str(os.getpid()))

    # Start dashboard in a loop (auto-restart on crash)
    while True:
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "gmgn_monitor.dashboard", "--port", str(PORT)],
                cwd=PROJECT_ROOT,
            )
            proc.wait()
            print(f"Dashboard exited with code {proc.returncode}, restarting in 3s...")
        except Exception as exc:
            print(f"Dashboard crashed: {exc}, restarting in 3s...")
        time.sleep(3)


def stop() -> None:
    """Stop the dashboard daemon."""
    if not PID_FILE.exists():
        print("Dashboard not running")
        return

    try:
        pid = int(PID_FILE.read_text().strip())
        if _is_running(pid):
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
            if _is_running(pid):
                os.kill(pid, signal.SIGKILL)
            print(f"Dashboard stopped (PID {pid})")
        else:
            print("Dashboard not running")
    except (ValueError, OSError) as exc:
        print(f"Error stopping dashboard: {exc}")
    finally:
        PID_FILE.unlink(missing_ok=True)


def status() -> None:
    """Check dashboard status."""
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            if _is_running(pid):
                print(f"Dashboard running (PID {pid}) on port {PORT}")
                return
        except (ValueError, OSError):
            pass
    print("Dashboard not running")


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: dashboard_daemon.py <start|stop|status|restart>")
        return 1

    cmd = sys.argv[1].lower()
    if cmd == "start":
        start()
    elif cmd == "stop":
        stop()
    elif cmd == "restart":
        stop()
        time.sleep(1)
        start()
    elif cmd == "status":
        status()
    else:
        print(f"Unknown command: {cmd}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
