"""Join a Google Meet as "Cue" with the animated mascot as the camera and Cue's speech as the mic.

Self-hosted Playwright + Chromium bot; no paid meeting-bot service. The face scripts from face/ are
injected into the Meet tab, where canvas.captureStream() and a Web Audio MediaStreamDestination
replace getUserMedia. Contract events (state, speak, stop, action, caption) arrive over a WebSocket
and are dispatched into the page; face events (speak_started, speak_ended, ...) and bot status go
back over the same socket.

    python scripts/face_bot.py login                      # sign in to Cue's dedicated Google account
    python scripts/face_bot.py join https://meet.google.com/abc-defg-hij --ws ws://127.0.0.1:8765/ws
    python scripts/face_bot.py join https://meet.google.com/abc-defg-hij --mock   # scripted demo

See face/README.md for setup and the real-Meet test procedure.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import BrowserContext, Error as PlaywrightError, Page, async_playwright

ROOT = Path(__file__).resolve().parents[1]
FACE_DIR = ROOT / "face"
DEFAULT_PROFILE = Path(os.environ.get("CUE_FACE_PROFILE", Path.home() / ".cue-face-bot" / "chrome-profile"))
MEET_HOST_PATTERN = r"^meet\.google\.com$"
EMIT_BINDING = "__cueFaceEmit"
MAX_FRAME = 16 * 1024 * 1024
CHROME_PATHS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
)

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_NOT_ADMITTED = 3
EXIT_JOIN_FAILED = 4
EXIT_INTERRUPTED = 130

log = logging.getLogger("face_bot")


# ---------------------------------------------------------------------------------------------
# Face bundle


def face_scripts(face_dir: Path = FACE_DIR) -> list[Path]:
    """The scripts index.html loads, in order. index.html is the single source of truth."""
    html = (face_dir / "index.html").read_text(encoding="utf-8")
    sources = re.findall(r'<script src="(src/[\w./-]+\.js)"></script>', html)
    if not sources:
        raise RuntimeError("No face scripts found in face/index.html")
    return [face_dir / source for source in sources]


def build_init_script(config: dict, host_pattern: str = MEET_HOST_PATTERN, face_dir: Path = FACE_DIR) -> str:
    """One classic script that boots the face in embedded mode, only in the top-level Meet frame."""
    font = face_dir / "assets" / "geist-latin.woff2"
    embed = {"emitBinding": EMIT_BINDING, **config}
    if font.is_file():
        embed["font"] = "data:font/woff2;base64," + base64.b64encode(font.read_bytes()).decode()
    bundle = "\n;\n".join(path.read_text(encoding="utf-8") for path in face_scripts(face_dir))
    return (
        "(function () {\n"
        "  if (window.top !== window) return;\n"
        f"  if (!new RegExp({json.dumps(host_pattern)}).test(location.hostname)) return;\n"
        "  if (globalThis.__CUE_FACE_EMBED__) return;\n"
        f"  globalThis.__CUE_FACE_EMBED__ = {json.dumps(embed)};\n"
        f"{bundle}\n"
        "})();\n"
    )


# ---------------------------------------------------------------------------------------------
# Meet page state

WAITING = re.compile(
    r"asking to be let in|someone in the call will let you in|please wait until a meeting host brings you"
    r"|waiting for the host|you'll join the call when someone lets you in",
    re.I,
)
DENIED = re.compile(
    r"denied your request|you can.t join this (video )?call|your request to join (was|has been) (declined|denied)"
    r"|no one responded to your request|you.ve been removed|removed you from the (call|meeting)",
    re.I,
)
ENDED = re.compile(r"you left the (meeting|call)|the call has ended|meeting has ended|call ended for everyone|return to home screen", re.I)
INVALID = re.compile(r"check your meeting code|invalid video call name|this meeting code is invalid|meeting not found", re.I)
SIGN_IN = re.compile(r"sign in to join|to join this (call|meeting), sign in|use your google account", re.I)
ALONE = re.compile(r"you.re the only one here|no one else is here", re.I)


def classify(text: str) -> str | None:
    """Maps visible Meet text to a lifecycle status. Order matters: terminal states win."""
    for status, pattern in (("denied", DENIED), ("ended", ENDED), ("invalid", INVALID), ("sign_in_required", SIGN_IN), ("waiting", WAITING)):
        if pattern.search(text):
            return status
    return None


def button(page: Page, pattern: str):
    return page.get_by_role("button", name=re.compile(pattern, re.I))


async def visible(locator, timeout: float = 0) -> bool:
    try:
        if timeout:
            await locator.first.wait_for(state="visible", timeout=timeout * 1000)
            return True
        return await locator.first.is_visible()
    except PlaywrightError:
        return False


async def page_text(page: Page) -> str:
    try:
        return await page.locator("body").inner_text(timeout=2000)
    except PlaywrightError:
        return ""


async def in_call(page: Page) -> bool:
    return await visible(button(page, r"^leave call"))


async def dismiss_popups(page: Page) -> None:
    for name in (r"^got it$", r"^dismiss$", r"^close$", r"^no thanks$", r"^not now$"):
        locator = button(page, name)
        if await visible(locator):
            try:
                await locator.first.click(timeout=2000)
            except PlaywrightError:
                pass


async def ensure_devices_on(page: Page) -> None:
    """Meet remembers mute state per profile; make sure camera and mic are on."""
    for device in ("camera", "microphone"):
        locator = button(page, rf"^turn on {device}")
        if await visible(locator):
            try:
                await locator.first.click(timeout=3000)
                log.info("Turned on %s", device)
            except PlaywrightError as error:
                log.warning("Could not turn on %s: %s", device, error)


async def admit_waiting(page: Page) -> str | None:
    """Clicks Meet's "Admit" for one person asking to join. Returns their name ("" if unknown),
    or None when nobody is waiting. Only used when Cue hosts the meeting (the demo)."""
    locator = button(page, r"^admit$")
    if not await visible(locator):
        return None
    name = ""
    try:
        dialog = page.get_by_role("dialog").filter(has=locator.first)
        if await dialog.count():
            name = re.sub(r"\s+", " ", (await dialog.first.inner_text(timeout=1000)).split("\n")[0])[:80]
        await locator.first.click(timeout=3000)
    except PlaywrightError as error:
        log.warning("Could not admit a guest: %s", error)
        return None
    return name


# ---------------------------------------------------------------------------------------------
# Bot


@dataclass
class BotOptions:
    meeting_url: str
    name: str = "Cue"
    ws_url: str | None = None
    mock: bool = False
    captions: bool = True
    guest: bool = False
    profile: Path = DEFAULT_PROFILE
    browser: str = "auto"
    headless: bool = False
    join_timeout: float = 60.0
    admission_timeout: float = 600.0
    alone_timeout: float = 300.0
    wait_for_guest: float | None = None
    auto_admit: int = 0
    capture_audio: bool = False
    max_minutes: float = 240.0
    host_pattern: str = MEET_HOST_PATTERN
    extra_args: list[str] = field(default_factory=list)


class FaceBot:
    def __init__(self, options: BotOptions):
        self.o = options
        self.page: Page | None = None
        self.context: BrowserContext | None = None
        self.ws = None
        self.stopping = asyncio.Event()
        self.status = "starting"
        self.admitted_at: float | None = None
        self.exit_code = EXIT_OK
        self._temp_profile: str | None = None
        self.on_launched = None  # called once the browser is up (run_bot installs signal handlers here)

    # -- lifecycle ---------------------------------------------------------------------------

    async def run(self) -> int:
        async with async_playwright() as playwright:
            bridge = None
            try:
                try:
                    await self._launch(playwright)
                finally:
                    if self.on_launched:
                        self.on_launched()
                bridge = asyncio.create_task(self._bridge()) if self.o.ws_url else None
                try:
                    await self._join()
                    if self.status == "in_call":
                        await self._stay()
                except JoinError as error:
                    log.error("%s", error)
                    self.exit_code = error.code
                    await self._report(error.status, detail=str(error))
                except PlaywrightError as error:
                    # e.g. the Meet tab crashed or the browser was closed by hand
                    log.error("Browser error: %s", str(error).splitlines()[0])
                    self.exit_code = EXIT_JOIN_FAILED
                    await self._report("error", detail=str(error).splitlines()[0])
                finally:
                    await self._leave()
            finally:
                if bridge:
                    bridge.cancel()
                await self._close()
        return self.exit_code

    def request_stop(self, reason: str) -> None:
        if not self.stopping.is_set():
            log.info("Stopping: %s", reason)
            self.stopping.set()

    async def _launch(self, playwright) -> None:
        profile = self.o.profile
        if self.o.guest:
            self._temp_profile = tempfile.mkdtemp(prefix="cue-face-guest-")
            profile = Path(self._temp_profile)
        else:
            profile.mkdir(parents=True, exist_ok=True)
        channel = resolve_channel(self.o.browser)
        args = [
            "--use-fake-ui-for-media-stream",  # auto-accept the camera/mic prompt
            "--use-fake-device-for-media-stream",  # Meet sees a camera and mic; getUserMedia is ours
            "--autoplay-policy=no-user-gesture-required",  # AudioContext runs without a click
            "--disable-blink-features=AutomationControlled",
            "--disable-features=Translate,MediaRouter,DialMediaRouteProvider",
            "--no-first-run",
            "--no-default-browser-check",
            "--lang=en-US",
            "--window-size=1280,860",
            *self.o.extra_args,
        ]
        log.info("Launching %s (%s profile)", channel or "chromium", "guest" if self.o.guest else str(profile))
        self.context = await playwright.chromium.launch_persistent_context(
            str(profile),
            channel=channel,
            headless=self.o.headless,
            args=args,
            ignore_default_args=ignored_default_args(channel, self.o.guest),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            permissions=["camera", "microphone"],
            bypass_csp=True,  # lets the injected face run under Meet's CSP and Trusted Types
            # This process owns shutdown: it must leave the call before the browser goes away.
            handle_sigint=False,
            handle_sigterm=False,
            handle_sighup=False,
        )
        await self.context.expose_binding(EMIT_BINDING, self._on_face_emit)
        init = build_init_script(
            {"captions": self.o.captions, "mock": self.o.mock, "fps": 30, "captureAudio": self.o.capture_audio}, self.o.host_pattern
        )
        await self.context.add_init_script(init)
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        self.page.on("close", lambda _: self.request_stop("Meet tab closed"))
        self.page.on("crash", lambda _: log.error("The Meet tab crashed"))
        self.context.on("close", lambda _: self.request_stop("browser closed"))

    async def _join(self) -> None:
        page = self.page
        self.status = "joining"
        await self._report("joining")
        log.info("Opening %s", self.o.meeting_url)
        await page.goto(self.o.meeting_url, wait_until="domcontentloaded", timeout=self.o.join_timeout * 1000)
        if not await self._wait_for_face():
            raise JoinError("join_failed", "The face did not start inside Meet", EXIT_JOIN_FAILED)

        deadline = time.monotonic() + self.o.join_timeout
        join_button = button(page, r"^(join now|ask to join|join)$")
        while time.monotonic() < deadline and not self.stopping.is_set():
            await dismiss_popups(page)
            if await visible(join_button):
                break
            status = classify(await page_text(page))
            if status in ("denied", "invalid", "sign_in_required", "ended"):
                raise JoinError(status, f"Meet refused the join ({status})", EXIT_JOIN_FAILED)
            await asyncio.sleep(0.5)
        else:
            if self.stopping.is_set():
                return
            raise JoinError("join_failed", "No join button appeared; is the profile signed in and the link valid?", EXIT_JOIN_FAILED)

        name_box = page.get_by_role("textbox", name=re.compile(r"your name", re.I))
        if await visible(name_box):
            await name_box.first.fill(self.o.name)
            log.info("Joining as guest named %r", self.o.name)
        await ensure_devices_on(page)
        label = (await join_button.first.inner_text()).strip()
        await join_button.first.click()
        log.info("Clicked %r", label)
        await self._await_admission()

    async def _wait_for_face(self) -> bool:
        try:
            await self.page.wait_for_function("() => window.CueFace && window.CueFace.app && window.CueFace.app.frames > 0", timeout=15000)
            return True
        except PlaywrightError:
            return False

    async def _await_admission(self) -> None:
        page = self.page
        start = time.monotonic()
        announced_wait = False
        while not self.stopping.is_set():
            if await in_call(page):
                self.admitted_at = time.monotonic()
                self.status = "in_call"
                log.info("Admitted after %.1fs", self.admitted_at - start)
                await ensure_devices_on(page)
                await self._report("in_call")
                asyncio.create_task(self._confirm_video())
                return
            status = classify(await page_text(page))
            if status in ("denied", "ended", "invalid", "sign_in_required"):
                raise JoinError(status, f"Not admitted ({status})", EXIT_NOT_ADMITTED)
            if status == "waiting" and not announced_wait:
                announced_wait = True
                self.status = "waiting_admission"
                log.info("Waiting for someone in the meeting to admit Cue")
                await self._report("waiting_admission")
            if time.monotonic() - start > self.o.admission_timeout:
                raise JoinError("admission_timeout", f"Not admitted within {self.o.admission_timeout:.0f}s", EXIT_NOT_ADMITTED)
            await asyncio.sleep(0.5)

    async def _confirm_video(self) -> None:
        """Logs when Meet is really sending mascot frames: the 15s-after-admission check."""
        deadline = time.monotonic() + 30
        live = False
        while time.monotonic() < deadline and not self.stopping.is_set():
            try:
                stats = await self.page.evaluate("() => window.CueFace.outboundStats ? window.CueFace.outboundStats() : null")
            except PlaywrightError:
                return
            elapsed = time.monotonic() - (self.admitted_at or time.monotonic())
            if stats and stats["videoFramesSent"] > 0 and not live:
                live = True
                log.info("Mascot is live: first frames sent %.1fs after admission; audio packets %d", elapsed, stats["audioPacketsSent"])
                await self._report("video_live", seconds_after_admission=round(elapsed, 1))
            if live and stats["frameWidth"] >= 1280:
                # WebRTC starts small and ramps up as bandwidth estimates grow.
                log.info("Sending %dx%d, %.1fs after admission", stats["frameWidth"], stats["frameHeight"], elapsed)
                await self._report("video_full_resolution", seconds_after_admission=round(elapsed, 1), frame_width=stats["frameWidth"], frame_height=stats["frameHeight"])
                return
            await asyncio.sleep(0.5)
        if not live:
            log.warning("No outbound video frames 30s after admission; check the camera button in Meet")
        else:
            log.info("Still below 1280x720 after 30s; Meet may be limiting bandwidth or the tile size")

    async def _stay(self) -> None:
        page = self.page
        started = time.monotonic()
        ends_at = started + self.o.max_minutes * 60
        alone_since: float | None = None
        seen_guest = False
        admitted = 0
        while not self.stopping.is_set():
            if time.monotonic() > ends_at:
                self.request_stop("max duration reached")
                break
            text = await page_text(page)
            status = classify(text)
            if status in ("ended", "denied") or (not await in_call(page) and status is not None):
                log.info("Meeting is over for Cue (%s)", status)
                self.status = "left"
                await self._report("left", reason=status)
                return
            if admitted < self.o.auto_admit and (name := await admit_waiting(page)) is not None:
                admitted += 1
                seen_guest = True
                log.info("Admitted %s (%d of %d allowed)", name or "a guest", admitted, self.o.auto_admit)
                await self._report("admitted", detail=name)
            if ALONE.search(text):
                alone_since = alone_since or time.monotonic()
                if seen_guest and time.monotonic() - alone_since > self.o.alone_timeout:
                    self.request_stop("alone in the meeting")
            else:
                if not seen_guest:
                    log.info("Someone else is in the call")
                    await self._report("guest_present")
                seen_guest = True
                alone_since = None
            if not seen_guest and self.o.wait_for_guest and time.monotonic() - started > self.o.wait_for_guest:
                self.request_stop("nobody joined")
            try:
                await asyncio.wait_for(self.stopping.wait(), 1)
            except TimeoutError:
                pass

    async def _leave(self) -> None:
        page = self.page
        if not page or page.is_closed():
            return
        try:
            # Silence first, so a half-spoken sentence never lingers while we leave.
            await page.evaluate("() => window.CueFace && window.CueFace.app && window.CueFace.app.dispatch({type: 'stop'})")
            if await in_call(page):
                await button(page, r"^leave call").first.click(timeout=3000)
                log.info("Left the call")
                await asyncio.sleep(1)
                self.status = "left"
                await self._report("left", reason="bot_shutdown")
        except PlaywrightError as error:
            log.warning("Leaving the call failed: %s", error)

    async def _close(self) -> None:
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:  # noqa: BLE001 - shutting down regardless
                pass
        if self.context is not None:
            try:
                await self.context.close()
            except PlaywrightError:
                pass
        if self._temp_profile:
            shutil.rmtree(self._temp_profile, ignore_errors=True)

    # -- event bridge ------------------------------------------------------------------------

    async def _bridge(self) -> None:
        """Backend WebSocket <-> page. Reconnects with capped backoff while the bot runs."""
        from websockets.asyncio.client import connect
        from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI

        headers = {}
        if token := os.environ.get("CUE_FACE_WS_TOKEN"):
            headers["Authorization"] = f"Bearer {token}"
        delay = 0.5
        while not self.stopping.is_set():
            try:
                async with connect(self.o.ws_url, additional_headers=headers, max_size=MAX_FRAME, open_timeout=10) as ws:
                    self.ws = ws
                    delay = 0.5
                    log.info("Event socket connected")
                    await self._report(self.status)
                    async for frame in ws:
                        if isinstance(frame, bytes):
                            continue
                        await self._dispatch(frame)
            except InvalidURI:
                log.error("Invalid --ws URL; events are disabled")
                return
            except (OSError, ConnectionClosed, InvalidHandshake, TimeoutError) as error:
                log.warning("Event socket unavailable (%s); retrying in %.1fs", error.__class__.__name__, delay)
            finally:
                self.ws = None
            try:
                await asyncio.wait_for(self.stopping.wait(), delay)
            except TimeoutError:
                pass
            delay = min(delay * 2, 10)

    async def _dispatch(self, frame: str) -> None:
        if not self.page or self.page.is_closed():
            return
        try:
            accepted = await self.page.evaluate(
                "frame => window.CueFace && window.CueFace.app ? window.CueFace.app.dispatch(frame) : false", frame
            )
            if not accepted:
                log.warning("Face rejected an event: %s", frame[:160])
        except PlaywrightError as error:
            log.warning("Could not deliver event to the page: %s", error)

    async def _on_face_emit(self, _source, payload: str) -> None:
        await self._send(payload)

    async def _report(self, status: str, **extra) -> None:
        await self._send(json.dumps({"type": "bot_status", "status": status, "name": self.o.name, **extra}))

    async def _send(self, payload: str) -> None:
        if self.ws is None:
            return
        try:
            await self.ws.send(payload)
        except Exception as error:  # noqa: BLE001 - the bridge loop reconnects
            log.debug("Dropped outbound message: %s", error)


class JoinError(Exception):
    def __init__(self, status: str, message: str, code: int):
        super().__init__(message)
        self.status = status
        self.code = code


def ignored_default_args(channel: str | None, guest: bool) -> list[str]:
    """Playwright flags to drop. With a signed-in Chrome profile, Chrome must use the real macOS
    Keychain / OS password store: `face_bot.py login` encrypted the session cookies with it, and
    Playwright's mock keychain would make the account look signed out."""
    ignored = ["--enable-automation"]
    if channel == "chrome" and not guest:
        ignored += ["--use-mock-keychain", "--password-store=basic"]
    return ignored


def profile_in_use(profile: Path) -> int | None:
    """PID of a live Chrome holding the profile (Chrome's SingletonLock is "host-pid"), else None."""
    lock = profile / "SingletonLock"
    try:
        target = os.readlink(lock)
    except OSError:
        return None
    try:
        pid = int(target.rsplit("-", 1)[-1])
        os.kill(pid, 0)
    except (ValueError, ProcessLookupError):
        return None
    except PermissionError:
        pass
    return pid


def resolve_channel(choice: str) -> str | None:
    if choice == "chromium":
        return None
    if choice == "chrome" or any(Path(p).exists() for p in CHROME_PATHS):
        return "chrome"
    return None


def chrome_binary() -> str | None:
    for path in CHROME_PATHS:
        if Path(path).exists():
            return path
    return shutil.which("google-chrome") or shutil.which("chrome")


# ---------------------------------------------------------------------------------------------
# CLI


def login(profile: Path) -> int:
    """Opens a plain (not automated) Chrome window on the bot profile so a person can sign in to
    Cue's dedicated Google account. The bot never sees or stores the password."""
    profile.mkdir(parents=True, exist_ok=True)
    binary = chrome_binary()
    if not binary:
        print("Google Chrome was not found. Install Chrome, or sign in with --browser chromium on join.", file=sys.stderr)
        return EXIT_CONFIG
    print(f"Opening Chrome with the Cue bot profile at {profile}")
    print("Sign in to Cue's dedicated Google account, check that its display name is 'Cue', then quit Chrome.")
    subprocess.run(
        [binary, f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check", "https://accounts.google.com/"],
        check=False,
    )
    print("Chrome closed; the profile is ready for `face_bot.py join`.")
    return EXIT_OK


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true")
    # -v also works after the subcommand; SUPPRESS keeps it from resetting a -v given before it.
    verbose = argparse.ArgumentParser(add_help=False)
    verbose.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    login_cmd = sub.add_parser("login", parents=[verbose], help="sign in to Cue's Google account in the bot profile")
    login_cmd.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)

    join = sub.add_parser("join", parents=[verbose], help="join a Google Meet as Cue")
    join.add_argument("meeting_url")
    join.add_argument("--ws", dest="ws_url", help="backend WebSocket that sends contract events")
    join.add_argument("--mock", action="store_true", help="play the scripted demo inside the meeting")
    join.add_argument("--name", default="Cue", help="guest display name (signed-in joins use the account name)")
    join.add_argument("--guest", action="store_true", help="join without the signed-in profile, as a named guest")
    join.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    join.add_argument("--browser", choices=("auto", "chrome", "chromium"), default="auto")
    join.add_argument("--headless", action="store_true", help="not recommended: Meet often blocks headless browsers")
    join.add_argument("--no-captions", dest="captions", action="store_false")
    join.add_argument("--join-timeout", type=float, default=60)
    join.add_argument("--admission-timeout", type=float, default=600)
    join.add_argument("--alone-timeout", type=float, default=300, help="leave after being alone this long once someone has joined")
    join.add_argument("--wait-for-guest", type=float, default=None, help="leave if nobody else joins within this many seconds")
    join.add_argument("--auto-admit", type=int, default=0, help="when Cue hosts, admit up to N people who ask to join")
    join.add_argument("--capture-audio", action="store_true", help="stream meeting audio to the --ws backend as audio_in")
    join.add_argument("--max-minutes", type=float, default=240)
    join.add_argument("--host-pattern", default=MEET_HOST_PATTERN, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.command == "join":
        if not re.match(r"^(https://|http://(127\.0\.0\.1|localhost)[:/])", args.meeting_url):
            parser.error("meeting_url must be an https:// link (http:// only for localhost testing)")
        if args.ws_url and not re.match(r"^wss?://", args.ws_url):
            parser.error("--ws must be a ws:// or wss:// URL")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("websockets").setLevel(logging.INFO)  # -v would otherwise log every audio frame
    if args.command == "login":
        return login(args.profile)
    if not args.guest and (pid := profile_in_use(args.profile)):
        log.error(
            "Chrome (pid %d) is still using the bot profile %s. Quit that Chrome completely (Cmd-Q) and try again.",
            pid, args.profile,
        )
        return EXIT_CONFIG
    if not args.guest and not args.profile.exists():
        log.warning("Profile %s does not exist yet; run `face_bot.py login` first or pass --guest", args.profile)
    options = BotOptions(
        meeting_url=args.meeting_url,
        name=args.name,
        ws_url=args.ws_url,
        mock=args.mock,
        captions=args.captions,
        guest=args.guest,
        profile=args.profile,
        browser=args.browser,
        headless=args.headless,
        join_timeout=args.join_timeout,
        admission_timeout=args.admission_timeout,
        alone_timeout=args.alone_timeout,
        wait_for_guest=args.wait_for_guest,
        auto_admit=args.auto_admit,
        capture_audio=args.capture_audio,
        max_minutes=args.max_minutes,
        host_pattern=args.host_pattern,
    )
    return asyncio.run(run_bot(options))


async def run_bot(options: BotOptions) -> int:
    bot = FaceBot(options)
    loop = asyncio.get_running_loop()
    interrupted = False
    signals = (signal.SIGINT, signal.SIGTERM)

    def on_signal(signame: str) -> None:
        nonlocal interrupted
        if interrupted:
            log.warning("Second %s: exiting now", signame)
            os._exit(EXIT_INTERRUPTED)
        interrupted = True
        bot.request_stop(signame)

    def install_handlers() -> None:
        for sig in signals:
            try:
                loop.add_signal_handler(sig, on_signal, sig.name)
            except NotImplementedError:  # Windows
                pass

    # Ctrl-C in a terminal signals the whole process group. The Playwright driver and Chrome are
    # started while SIGINT/SIGTERM are ignored, so they inherit "ignore" and stay up long enough
    # for the bot to leave the call cleanly; this process then installs its own handlers.
    for sig in signals:
        try:
            signal.signal(sig, signal.SIG_IGN)
        except (ValueError, OSError):
            pass
    bot.on_launched = install_handlers
    code = await bot.run()
    return EXIT_INTERRUPTED if interrupted and code == EXIT_OK else code


if __name__ == "__main__":
    sys.exit(main())
