"""Start the API and every local worker in one terminal; Ctrl+C stops them all.

Loads .env, then runs uvicorn, the raw/outbox/memory workers, and the connector poller,
prefixing each line with the process name. Used by start.bat and start.sh.

Usage: python scripts/run_stack.py [--tenant UUID] [--port 8080] [--poll 60] [--no-poll]
"""

import argparse
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from _local_env import load_local_env

ROOT = Path(__file__).resolve().parents[1]


def relay(name: str, process: subprocess.Popen) -> None:
    for line in process.stdout or ():
        print(f"[{name:>8}] {line}", end="", flush=True)


def main() -> None:
    load_local_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", default=os.getenv("CUE_DEV_TENANT_ID")
                        or "11111111-1111-1111-1111-111111111111")
    parser.add_argument("--port", default="8080")
    parser.add_argument("--poll", default="60", help="connector poll interval in seconds")
    parser.add_argument("--no-poll", action="store_true")
    args = parser.parse_args()

    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT), str(ROOT / "scripts")]),
               PYTHONUNBUFFERED="1")
    python = sys.executable
    commands = {
        "api": [python, "-m", "uvicorn", "cue.main:app", "--host", "0.0.0.0", "--port", args.port],
        "raw": [python, "scripts/process_raw.py"],
        "outbox": [python, "scripts/publish_outbox.py"],
        "memory": [python, "scripts/process_memory.py"],
    }
    if not args.no_poll:
        commands["poll"] = [python, "scripts/poll_connectors.py", args.tenant, "--interval", args.poll]

    processes = {}
    for name, command in commands.items():
        processes[name] = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, text=True, bufsize=1)
        threading.Thread(target=relay, args=(name, processes[name]), daemon=True).start()
    print(f"Cue is up: console http://localhost:{args.port}/ui  (Ctrl+C to stop)", flush=True)
    try:
        while all(p.poll() is None for p in processes.values()):
            time.sleep(1)
        dead = [n for n, p in processes.items() if p.poll() is not None]
        print(f"stopped unexpectedly: {', '.join(dead)}; shutting down the rest", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes.values():
            if process.poll() is None:
                process.terminate()
        for process in processes.values():
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    main()
