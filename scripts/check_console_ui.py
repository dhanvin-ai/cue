"""Drive the Cue console in a real browser against the running local API.

Opens each view, sends an agent request, queries memory, creates a proactive
rule and loads the admin panels, then reports every page error and failed
request it saw. Requires the API on 127.0.0.1:8000 with the dev auth bypass on.
"""

import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from scripts._local_env import load_local_env

load_local_env()
BASE = os.getenv("CONSOLE_URL", "http://127.0.0.1:8000")
TENANT = os.environ["CUE_DEV_TENANT_ID"]

page_errors: list[str] = []
failed_requests: list[str] = []


def _launch_browser(playwright):
    """Use a locally installed Chromium build; CI installs its own via playwright."""
    import glob

    roots = [Path(local) for local in filter(None, (
        os.environ.get("LOCALAPPDATA"),
        str(Path(os.environ.get("USERPROFILE") or "") / "AppData" / "Local"),
        r"C:\Users\Avinash\AppData\Local",
    ))]
    patterns = (
        "chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe",
        "chromium-*/chrome-win64/chrome.exe",
        "chromium-*/chrome-win/chrome.exe",
    )
    candidates = [path for root in roots for pattern in patterns
                  for path in sorted(glob.glob(str(root / "ms-playwright" / pattern)), reverse=True)]
    for path in candidates:
        if os.path.isfile(path):
            print(f"browser: {path}")
            return playwright.chromium.launch(headless=True, executable_path=path)
    raise SystemExit("No local Chromium found. Run `playwright install chromium` first.")


def main() -> int:
    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("console", lambda message: page_errors.append(f"console.{message.type}: {message.text}")
                if message.type == "error" else None)
        page.on("requestfailed", lambda request: failed_requests.append(f"{request.url} {request.failure}"))
        page.on("response", lambda response: failed_requests.append(f"HTTP {response.status} {response.url}")
                if response.status >= 400 else None)

        page.goto(f"{BASE}/ui", wait_until="networkidle")
        nav_count = page.locator(".nav-item").count()
        print(f"nav items rendered: {nav_count}")
        assert nav_count == 7, "navigation did not render; console.js failed"

        # Identity comes from /me, so these prove the boot sequence ran.
        who = page.locator("#who").inner_text()
        role = page.locator("#roleLabel").inner_text()
        api_state = page.locator("#apiText").inner_text()
        worker_state = page.locator("#workerText").inner_text()
        print(f"identity: uid={who} role={role} api={api_state} worker={worker_state}")

        # Ask tab: history loaded from the new /agent/tasks endpoint.
        bubbles = page.locator("#thread .bubble").count()
        print(f"thread bubbles after boot: {bubbles}")

        # Send a real request through the runtime ingress.
        stamp = int(time.time())
        page.fill("#askInput", f"Browser check {stamp}: what changed today?")
        page.click("#askBtn")
        page.wait_for_selector('.bubble[data-task-id]', timeout=10000)
        task_id = page.locator(".bubble.agent").last.get_attribute("data-task-id")
        print(f"submitted task {task_id}; pill={page.locator('.bubble.agent').last.locator('.pill').inner_text()}")

        # Approvals view (empty is a valid outcome, but must render without error).
        page.click('.nav-item[data-pane="approvals"]')
        print("approvals:", page.locator("#approvalsList").inner_text()[:60].replace("\n", " "))

        # Memory query hits Qdrant + Postgres through the real route. Without
        # inference credentials the backend legitimately fails; the console must
        # surface that reason rather than a blank pane or an uncaught error.
        page.click('.nav-item[data-pane="memory"]')
        page.fill("#memInput", "What did we decide about the launch date?")
        page.click("#memBtn")
        page.wait_for_function(
            "!document.querySelector('#memOut').textContent.includes('Routing')", timeout=30000)
        memory_out = page.locator("#memOut").inner_text()[:200].replace("\n", " ")
        print("memory result:", memory_out)
        assert memory_out.strip(), "memory pane rendered nothing at all"

        # Tasks table.
        page.click('.nav-item[data-pane="tasks"]')
        page.wait_for_selector("#tasksTable tbody tr, #tasksTable .empty, #tasksTable .err", timeout=10000)
        rows = page.locator("#tasksTable tbody tr").count()
        print("tasks rows:", rows)
        assert rows >= 1, "the task list rendered no rows"
        if rows:
            page.locator("#tasksTable tbody tr").first.click()
            page.wait_for_timeout(1500)
            detail = page.locator("#tasksTable .card").count()
            print("task detail opened:", detail > 0)
            assert detail > 0, "clicking a task row did not open its detail"

        # Proactive: create a rule through the form, then read it back.
        page.click('.nav-item[data-pane="proactive"]')
        page.fill("#prKey", f"browser-digest-{stamp}")
        page.select_option("#prKind", "daily_digest")
        page.click("#prCreate")
        page.wait_for_timeout(1500)
        print("proactive out:", page.locator("#prOut").inner_text()[:80].replace("\n", " "))
        rules = page.locator("#ruleList tbody tr").count()
        print("rules listed:", rules)
        assert rules >= 1, "created rule did not appear in the rule list"

        # Admin: status tiles, kill switch round trip, access report, audit export.
        page.click('.nav-item[data-pane="admin"]')
        page.wait_for_selector("#statusStats .stat", timeout=10000)
        tiles = page.locator("#statusStats .stat")
        print("status tiles:", [tiles.nth(i).inner_text().replace("\n", "=") for i in range(tiles.count())])
        page.click("#ksPause")
        page.wait_for_timeout(1500)
        paused = page.locator("#switchList").inner_text()[:80].replace("\n", " ")
        print("after pause:", paused)
        page.click("#ksResume")
        page.wait_for_timeout(1500)
        print("after resume:", page.locator("#switchList").inner_text()[:80].replace("\n", " "))
        page.click("#arLoad")
        page.wait_for_selector("#accessReport .stat", timeout=10000)
        print("access report sections:", page.locator("#accessReport details").count())
        page.click("#auLoad")
        page.wait_for_timeout(2000)
        print("audit export chars:", len(page.locator("#auditOut").inner_text()))

        # Meetings view renders its forms (joining needs a Recall key).
        page.click('.nav-item[data-pane="meetings"]')
        print("meeting form fields:", page.locator('#mtUrl, #mtTitle, #mtPeople, #ntId').count())

        # Mobile layout.
        page.set_viewport_size({"width": 390, "height": 844})
        page.click('.nav-item[data-pane="ask"]')
        page.wait_for_timeout(500)
        overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        print(f"mobile horizontal overflow: {overflow}px")
        page.screenshot(path="snapshots/console-mobile.png", full_page=False)
        page.set_viewport_size({"width": 1440, "height": 900})
        page.screenshot(path="snapshots/console-desktop.png", full_page=False)

        browser.close()

    print("\n--- page errors ---")
    for item in page_errors or ["none"]:
        print(item)
    print("--- failed/4xx requests ---")
    for item in failed_requests or ["none"]:
        print(item)
    # A 500 from /memory/query is expected without inference credentials; the
    # console itself must still be free of script errors.
    script_errors = [e for e in page_errors if "Failed to load resource" not in e]
    return 1 if script_errors else 0


if __name__ == "__main__":
    sys.exit(main())
