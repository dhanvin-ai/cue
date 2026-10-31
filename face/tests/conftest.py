import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

FACE_DIR = Path(__file__).resolve().parents[1]
ROOT = FACE_DIR.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(FACE_DIR))

CHROMIUM_ARGS = [
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
    "--autoplay-policy=no-user-gesture-required",
]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server():
    """face/dev_server.py: static face page + WebSocket hub on one port."""
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, str(FACE_DIR / "dev_server.py"), "serve", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError("dev server did not start: " + proc.stderr.read().decode())
    yield {"http": f"http://127.0.0.1:{port}", "ws": f"ws://127.0.0.1:{port}/ws"}
    proc.terminate()
    proc.wait(5)


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(args=CHROMIUM_ARGS)
        yield b
        b.close()


@pytest.fixture
def page(browser, server):
    context = browser.new_context(viewport={"width": 1280, "height": 720})
    pg = context.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.errors = errors
    yield pg
    context.close()
